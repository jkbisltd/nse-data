# nse-data

Daily price history for the Nifty 200 and the main NSE indices, refreshed by GitHub Actions every weekday at 06:45 IST. It feeds the 08:00 IST morning-picks run, which can't download prices directly from its own environment.

## What's in `data/`

| File | Contents |
|---|---|
| `manifest.json` | When the refresh ran, the last trading date in the data, and any symbols that failed or are stale. Check this first. |
| `indicators_latest.csv` | One row per stock for the latest session: close, EMA 20/50/200, RSI(14), MACD(12,26,9), ADX(14) with +DI/−DI, ATR(14), Bollinger Bands(20,2), volume vs 20-day average, 52-week high/low, 20-day swing high/low, classic pivots, 1- and 3-month returns and relative strength vs Nifty 50. |
| `ohlcv/<SYMBOL>.csv` | About two years of daily Open, High, Low, Close, Adj Close, Volume. Symbols with characters like `&` use `_` in the file name (`M_M.csv`); `constituents.csv` maps them. |
| `index/<NAME>.csv` | The same for NIFTY50, BANKNIFTY, INDIAVIX and the sector indices. |
| `constituents.csv` | The Nifty 200 list used for the run, from niftyindices.com. |

## Reading it

Raw files are served from `https://raw.githubusercontent.com/jkbisltd/nse-data/main/data/...` while the repo is public.

## Running it

- **Automatically:** Mon–Fri at 01:15 UTC (06:45 IST). GitHub sometimes starts scheduled jobs a few minutes late.
- **By hand:** Actions → *Refresh NSE price history* → *Run workflow*.
- **Locally:** `pip install -r requirements.txt && python scripts/fetch_nse.py`

The run fails on purpose if fewer than 150 stocks download, so a bad day shows up as a red run instead of silently thin data.

Prices come from Yahoo Finance and are unofficial. Indicators use the standard definitions (Wilder smoothing for RSI, ATR and ADX).
