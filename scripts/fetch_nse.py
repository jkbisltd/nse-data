--- fetch_nse.py	2026-09-28 06:02:25.737101455 +0000
+++ fetch_nse_fixed.py	2026-09-28 06:03:01.149302550 +0000
@@ -56,6 +56,20 @@
     "Referer": "https://www.niftyindices.com/",
 }
 PERIOD = "2y"
+MIN_INDEX_ROWS = 200  # fewer rows than this means Yahoo gave us a stub, not history
+
+# Names used in NSE's daily all-indices archive, for indices Yahoo serves badly.
+NSE_INDEX_NAMES = {
+    "NIFTYAUTO": "Nifty Auto",
+    "NIFTYMETAL": "Nifty Metal",
+    "NIFTYFMCG": "Nifty FMCG",
+    "NIFTYREALTY": "Nifty Realty",
+    "NIFTYENERGY": "Nifty Energy",
+    "NIFTYMIDCAP100": "Nifty Midcap 100",
+    "NIFTYIT": "Nifty IT",
+    "NIFTYPHARMA": "Nifty Pharma",
+}
+NSE_ALL_INDICES_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"
 
 
 def safe_name(sym: str) -> str:
@@ -120,6 +134,51 @@
     return out
 
 
+def merge_history(path: Path, new: pd.DataFrame) -> pd.DataFrame:
+    """Combine what is already on disk with the new download, newest value wins.
+    A thin download can then never wipe out existing history."""
+    if path.exists():
+        old = pd.read_csv(path, index_col="Date", parse_dates=["Date"])
+        new = pd.concat([old, new])
+        new = new[~new.index.duplicated(keep="last")].sort_index()
+    return new
+
+
+def nse_index_history(names: list[str], days: int = 760) -> dict[str, pd.DataFrame]:
+    """Backfill daily OHLC for the given index names from NSE's per-day archive
+    file (one CSV per trading day listing every index)."""
+    wanted = {NSE_INDEX_NAMES[n].lower(): n for n in names if n in NSE_INDEX_NAMES}
+    rows: dict[str, list] = {n: [] for n in wanted.values()}
+    sess = requests.Session()
+    sess.headers.update({**HEADERS, "Referer": "https://www.nseindia.com/"})
+    end = pd.Timestamp.today().normalize()
+    for d in pd.bdate_range(end - pd.Timedelta(days=days), end):
+        try:
+            r = sess.get(NSE_ALL_INDICES_URL.format(d=d), timeout=20)
+            if r.status_code != 200 or "Index Name" not in r.text[:200]:
+                continue  # holiday or not published yet
+            day = pd.read_csv(io.StringIO(r.text))
+            day.columns = [c.strip() for c in day.columns]
+        except Exception:
+            continue
+        for _, x in day.iterrows():
+            n = wanted.get(str(x["Index Name"]).strip().lower())
+            if not n:
+                continue
+            num = lambda c: pd.to_numeric(x.get(c), errors="coerce")
+            close = num("Closing Index Value")
+            rows[n].append({"Date": d, "Open": num("Open Index Value"),
+                            "High": num("High Index Value"), "Low": num("Low Index Value"),
+                            "Close": close, "Adj Close": close, "Volume": num("Volume")})
+        time.sleep(0.3)  # be polite to NSE
+    out = {}
+    for n, r in rows.items():
+        if r:
+            out[n] = pd.DataFrame(r).set_index("Date").dropna(subset=["Close"]).round(4)
+            print(f"index backfill: {n} {len(out[n])} rows from NSE archive")
+    return out
+
+
 def main() -> None:
     OHLCV.mkdir(parents=True, exist_ok=True)
     INDEX.mkdir(parents=True, exist_ok=True)
@@ -133,7 +192,18 @@
     idx = download(list(INDICES.values()))
     for name, t in INDICES.items():
         if t in idx:
+            idx[t] = merge_history(INDEX / f"{name}.csv", idx[t])
+    short = [n for n, t in INDICES.items() if len(idx.get(t, [])) < MIN_INDEX_ROWS]
+    if short:
+        print(f"indices with thin history, backfilling from NSE: {short}")
+        for name, df in nse_index_history(short).items():
+            t = INDICES[name]
+            idx[t] = merge_history(INDEX / f"{name}.csv", df) if t not in idx else \
+                pd.concat([df, idx[t]])[lambda z: ~z.index.duplicated(keep="last")].sort_index()
+    for name, t in INDICES.items():
+        if t in idx:
             idx[t].to_csv(INDEX / f"{name}.csv")
+    indices_short = [n for n, t in INDICES.items() if len(idx.get(t, [])) < MIN_INDEX_ROWS]
     bench = idx.get("^NSEI", pd.DataFrame()).get("Close")
 
     prices = download(cons["yahoo"].tolist())
@@ -162,7 +232,8 @@
         "stocks_ok": len(rows),
         "stocks_failed": failed,
         "stale_symbols": ind.loc[ind["date"] != last_dates.index[0], "symbol"].tolist() if len(last_dates) else [],
-        "indices_ok": [n for n, t in INDICES.items() if t in idx],
+        "indices_ok": [n for n, t in INDICES.items() if t in idx and n not in indices_short],
+        "indices_short": indices_short,
     }
     (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2))
     print(json.dumps(manifest, indent=2))
