"""Daily NSE price-history refresh.

Downloads ~2 years of daily OHLCV for the Nifty 200 constituents and the
main NSE indices from Yahoo Finance, writes one CSV per symbol, and a
snapshot of standard technical indicators for every stock.

Outputs (all under data/):
  constituents.csv          symbol, company, industry, yahoo ticker, file name
  ohlcv/<FILE>.csv          Date,Open,High,Low,Close,Adj Close,Volume
  index/<NAME>.csv          same columns, for NIFTY50, BANKNIFTY, INDIAVIX, ...
  indicators_latest.csv     one row per stock, latest-day indicators
  manifest.json             run time, last trading date, success/failure counts
"""
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from indicators import snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OHLCV = DATA / "ohlcv"
INDEX = DATA / "index"

CONSTITUENT_URLS = [
    "https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
]
INDICES = {
    "NIFTY50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "INDIAVIX": "^INDIAVIX",
    "NIFTYIT": "^CNXIT",
    "NIFTYPHARMA": "^CNXPHARMA",
    "NIFTYAUTO": "^CNXAUTO",
    "NIFTYMETAL": "^CNXMETAL",
    "NIFTYFMCG": "^CNXFMCG",
    "NIFTYREALTY": "^CNXREALTY",
    "NIFTYENERGY": "^CNXENERGY",
    "NIFTYMIDCAP100": "NIFTY_MIDCAP_100.NS",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,text/plain,*/*",
    "Referer": "https://www.niftyindices.com/",
}
PERIOD = "2y"


def safe_name(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", sym)


def load_constituents() -> pd.DataFrame:
    for url in CONSTITUENT_URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = [c.strip() for c in df.columns]
            if "Symbol" in df.columns and len(df) >= 150:
                print(f"constituents: {len(df)} from {url}")
                return df
        except Exception as e:  # try next source
            print(f"constituents: {url} failed: {e}")
    prev = DATA / "constituents.csv"
    if prev.exists():
        print("constituents: using previously saved list")
        return pd.read_csv(prev)
    raise SystemExit("Could not load the Nifty 200 list from any source")


def clean(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    cols = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in df.columns]
    df = df[cols].dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "Date"
    return df.round(4)


def download(tickers: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    raw = yf.download(
        tickers, period=PERIOD, interval="1d", group_by="ticker",
        auto_adjust=False, threads=True, progress=False,
    )
    for t in tickers:
        try:
            sub = raw[t] if len(tickers) > 1 else raw
            sub = clean(sub)
            if len(sub):
                out[t] = sub
        except Exception:
            pass
    missing = [t for t in tickers if t not in out]
    for t in missing:  # retry one at a time
        for attempt in range(2):
            try:
                sub = clean(yf.download(t, period=PERIOD, interval="1d",
                                        auto_adjust=False, progress=False))
                if len(sub):
                    out[t] = sub
                    break
            except Exception:
                pass
            time.sleep(2)
    return out


def main() -> None:
    OHLCV.mkdir(parents=True, exist_ok=True)
    INDEX.mkdir(parents=True, exist_ok=True)

    cons = load_constituents()
    cons["yahoo"] = cons["Symbol"].astype(str).str.strip() + ".NS"
    cons["file"] = cons["Symbol"].astype(str).str.strip().map(safe_name) + ".csv"
    keep = [c for c in ["Company Name", "Industry", "Symbol", "Series", "ISIN Code", "yahoo", "file"] if c in cons.columns]
    cons[keep].to_csv(DATA / "constituents.csv", index=False)

    idx = download(list(INDICES.values()))
    for name, t in INDICES.items():
        if t in idx:
            idx[t].to_csv(INDEX / f"{name}.csv")
    bench = idx.get("^NSEI", pd.DataFrame()).get("Close")

    prices = download(cons["yahoo"].tolist())
    rows, failed = [], []
    for _, row in cons.iterrows():
        df = prices.get(row["yahoo"])
        if df is None:
            failed.append(row["Symbol"])
            continue
        df.to_csv(OHLCV / row["file"])
        snap = snapshot(df, bench)
        if snap:
            rows.append({"symbol": row["Symbol"], "company": row.get("Company Name"),
                         "industry": row.get("Industry"), **snap})

    ind = pd.DataFrame(rows).sort_values("symbol")
    ind.to_csv(DATA / "indicators_latest.csv", index=False)

    last_dates = ind["date"].value_counts()
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Yahoo Finance via yfinance (NSE, .NS tickers)",
        "universe": "Nifty 200",
        "last_trading_date": last_dates.index[0] if len(last_dates) else None,
        "nifty50_last_date": bench.index[-1].strftime("%Y-%m-%d") if bench is not None and len(bench) else None,
        "stocks_ok": len(rows),
        "stocks_failed": failed,
        "stale_symbols": ind.loc[ind["date"] != last_dates.index[0], "symbol"].tolist() if len(last_dates) else [],
        "indices_ok": [n for n, t in INDICES.items() if t in idx],
    }
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    if len(rows) < 150:
        raise SystemExit(f"Only {len(rows)} stocks downloaded; failing so the run is visible")


if __name__ == "__main__":
    main()
