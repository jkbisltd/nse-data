"""Technical indicators computed from daily OHLCV with pandas only.

All functions take a DataFrame indexed by date with columns
Open, High, Low, Close, Volume (ascending order) and return Series.
Smoothing follows the standard definitions (Wilder for RSI, ATR, ADX).
"""
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain = wilder(d.clip(lower=0), n)
    loss = wilder(-d.clip(upper=0), n)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0)


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["Close"].shift()
    return pd.concat(
        [df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1
    ).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(df), n)


def adx(df: pd.DataFrame, n: int = 14):
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = wilder(true_range(df), n)
    plus_di = 100 * wilder(plus_dm, n) / tr
    minus_di = 100 * wilder(minus_dm, n) / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return wilder(dx, n), plus_di, minus_di


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def bollinger(close: pd.Series, n=20, k=2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    return mid - k * sd, mid, mid + k * sd


def snapshot(df: pd.DataFrame, bench: pd.Series | None = None) -> dict:
    """Latest-day indicator values for one stock."""
    df = df.dropna(subset=["Close"])
    if len(df) < 60:
        return {}
    c, v = df["Close"], df["Volume"]
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    r = rsi(c)
    a = atr(df)
    ad, pdi, mdi = adx(df)
    ml, ms, mh = macd(c)
    bl, bm, bu = bollinger(c)
    vavg20 = v.rolling(20).mean().shift(1)  # average of the 20 days BEFORE today
    last = df.iloc[-1]
    prev = df.iloc[-2]
    win = df.tail(252)

    def f(x, nd=2):
        x = x.iloc[-1] if isinstance(x, pd.Series) else x
        return None if x is None or pd.isna(x) else round(float(x), nd)

    out = {
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "open": f(last["Open"]), "high": f(last["High"]), "low": f(last["Low"]),
        "close": f(last["Close"]), "prev_close": f(prev["Close"]),
        "chg_pct": f((last["Close"] / prev["Close"] - 1) * 100),
        "volume": int(last["Volume"]) if not pd.isna(last["Volume"]) else None,
        "vol_ratio_20d": f(v.iloc[-1] / vavg20.iloc[-1]) if vavg20.iloc[-1] else None,
        "ema20": f(e20), "ema50": f(e50), "ema200": f(e200),
        "above_ema20": bool(c.iloc[-1] > e20.iloc[-1]) if not pd.isna(e20.iloc[-1]) else None,
        "above_ema50": bool(c.iloc[-1] > e50.iloc[-1]) if not pd.isna(e50.iloc[-1]) else None,
        "above_ema200": bool(c.iloc[-1] > e200.iloc[-1]) if not pd.isna(e200.iloc[-1]) else None,
        "golden_cross": bool(e50.iloc[-1] > e200.iloc[-1]) if not pd.isna(e200.iloc[-1]) else None,
        "rsi14": f(r), "rsi14_prev": f(r.iloc[-2]),
        "macd": f(ml, 3), "macd_signal": f(ms, 3), "macd_hist": f(mh, 3),
        "macd_hist_prev": f(mh.iloc[-2], 3),
        "macd_cross_up": bool(mh.iloc[-1] > 0 >= mh.iloc[-2]) if not pd.isna(mh.iloc[-2]) else None,
        "adx14": f(ad), "plus_di": f(pdi), "minus_di": f(mdi),
        "atr14": f(a), "atr_pct": f(a.iloc[-1] / c.iloc[-1] * 100),
        "bb_lower": f(bl), "bb_mid": f(bm), "bb_upper": f(bu),
        "bb_pctb": f((c.iloc[-1] - bl.iloc[-1]) / (bu.iloc[-1] - bl.iloc[-1]), 3),
        "high_52w": f(win["High"].max()), "low_52w": f(win["Low"].min()),
        "pct_from_52w_high": f((c.iloc[-1] / win["High"].max() - 1) * 100),
        "swing_high_20d": f(df["High"].tail(21).iloc[:-1].max()),
        "swing_low_20d": f(df["Low"].tail(21).iloc[:-1].min()),
        "ret_1m": f((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) > 22 else None,
        "ret_3m": f((c.iloc[-1] / c.iloc[-64] - 1) * 100) if len(c) > 64 else None,
    }
    # Classic floor pivots from the latest session (for the next session)
    p = (last["High"] + last["Low"] + last["Close"]) / 3
    out.update({
        "pivot": f(p), "r1": f(2 * p - last["Low"]), "s1": f(2 * p - last["High"]),
        "r2": f(p + (last["High"] - last["Low"])), "s2": f(p - (last["High"] - last["Low"])),
    })
    if bench is not None:
        b = bench.reindex(df.index).ffill()
        for label, k in (("rs_1m", 21), ("rs_3m", 63)):
            if len(c) > k + 1 and not pd.isna(b.iloc[-k - 1]):
                out[label] = f(((c.iloc[-1] / c.iloc[-k - 1]) / (b.iloc[-1] / b.iloc[-k - 1]) - 1) * 100)
    return out
