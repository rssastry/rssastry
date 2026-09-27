"""update_price_files.py — Keep raw_data/prices/*.csv up to date.

Every trading day the morning scan re-validates the NSE universe, and
that is the moment the local price files should be refreshed.  This
module fetches the completed daily OHLCV bars (yfinance with
``auto_adjust=False`` so the raw series stays comparable to the existing
history) and merges them into the per-symbol CSVs while preserving the
exact file format::

    Date,Adj Close,Close,High,Low,Open,Volume

Existing rows are copied byte-for-byte (no re-rendering, no float drift),
so only genuinely new dates are inserted.  Bars already present are never
duplicated; a mid-file gap is back-filled; symbols without a CSV yet are
back-filled with 5 years of history.  Line endings (CRLF) are preserved.

Usage:
    python update_price_files.py                 # update universe + ^NSEI benchmark
    python update_price_files.py -s RELIANCE,TCS # a subset (net-safe test)
    python update_price_files.py --dry-run       # report without writing
"""
import argparse
import os
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

from price_store import CSV_COLUMNS, PRICE_DIR, csv_path_for, seed_path_for
from screener import NSE_STOCKS
from fundamental_snapshots import resolve_provider_ticker

BENCHMARK_SYMBOLS = ["^NSEI"]

BACKFILL_PERIOD = "5y"
GAP_LOOKBACK_DAYS = 45   # fetch this many extra days to detect/repair gaps
STALE_DAYS = 40          # tail older than this => full re-download
POLITE_SLEEP = 0.05      # seconds between ticker calls

HEADER = ",".join(["Date"] + CSV_COLUMNS)


def _ist_wall_dates(index: pd.Index) -> pd.Index:
    """Return a tz-naive index of IST calendar dates (matches the CSVs)."""
    idx = pd.to_datetime(index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    return idx


def fetch_bars(symbol: str, start_date=None, end_exclusive=None,
               period=None) -> pd.DataFrame:
    """Fetch daily OHLCV with auto_adjust=False; multiple strategies.

    yfinance intermittently throttles specific symbols; each strategy is
    retried a few times and, if empty, the next strategy is attempted.
    """
    strategies = []
    if period:
        strategies.append({"period": period})
    else:
        strategies.append({"start_date": start_date,
                           "end_exclusive": end_exclusive})
        strategies.append({"period": "3mo"})      # start/end throttled?
        strategies.append({"period": "6mo"})

    last_error = None
    for strategy in strategies:
        for attempt in range(3):
            try:
                df = _fetch_once(symbol, **strategy)
                if df is not None:
                    return df
            except Exception as exc:  # network / rate-limit
                last_error = exc
            time.sleep(0.8 * (attempt + 1))
    if last_error is not None:
        raise last_error
    return pd.DataFrame()


def _fetch_once(symbol: str, start_date=None, end_exclusive=None,
                period=None) -> pd.DataFrame:
    """Single-attempt yfinance call, format-normalized; None if empty."""
    kwargs = {"interval": "1d", "auto_adjust": False, "timeout": 10}
    if period:
        kwargs["period"] = period
    if start_date is not None:
        kwargs["start"] = start_date
    if end_exclusive is not None:
        kwargs["end"] = end_exclusive
    df = yf.Ticker(resolve_provider_ticker(symbol)).history(**kwargs)
    if df is None or df.empty:
        return None
    df.index = _ist_wall_dates(df.index)
    df.index.name = "Date"
    df.index = df.index.normalize()
    cols = [c for c in CSV_COLUMNS if c in df.columns]
    df = df[cols]
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df["Volume"] = np.round(df["Volume"].astype(float)).astype("int64")
    df = df[~df.index.duplicated(keep="last")]
    return df.sort_index()


def _fmt_row_texts(df: pd.DataFrame):
    """Render rows as (iso_date, text_line) pairs, LF-normalized."""
    if df.empty:
        return []
    fmt = df.copy()
    fmt.index = fmt.index.strftime("%Y-%m-%d")
    text = fmt.to_csv(header=False, index=True).replace("\r", "")
    lines = [ln for ln in text.split("\n") if ln]
    return [(ln.split(",")[0], ln) for ln in lines]


def _read_text_lines(path: str):
    """Return (header_line_or_None, [body_lines]) with CRLF stripped."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    header = None
    body = []
    for ln in lines:
        if not ln:
            continue
        if header is None and ln.startswith("Date,"):
            header = ln
        else:
            body.append(ln)
    return header, body


def _atomic_write(path: str, lines):
    """Write CRLF-terminated lines atomically (temp file + rename)."""
    text = "\n".join(lines) + "\n"
    tmp = os.path.join(os.path.dirname(path),
                       f".{os.path.basename(path)}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace("\n", "\r\n"))
    os.replace(tmp, path)
def update_one(symbol: str, dry_run: bool = False) -> str:
    """Update one symbol's CSV. Returns a short status string."""
    path = csv_path_for(symbol)
    tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    if not os.path.exists(path) and os.path.exists(seed_path_for(symbol)):
        # Seed a fresh durable store (SA_DATA_DIR mount) from the git-tracked
        # CSV so the frozen history is preserved and only genuinely new bars
        # are appended below — never a full 5-year re-download.
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(seed_path_for(symbol), "rb") as src, \
                open(path, "wb") as dst:
            dst.write(src.read())

    if not os.path.exists(path):
        # Back-fill a symbol that has no CSV (and no seed) yet.
        fetched = fetch_bars(symbol, end_exclusive=tomorrow,
                             period=BACKFILL_PERIOD)
        if fetched.empty:
            return "failed:no-data"
        if dry_run:
            return f"backfill:{len(fetched)}"
        os.makedirs(PRICE_DIR, exist_ok=True)
        body = [txt for _, txt in _fmt_row_texts(fetched)]
        _atomic_write(path, [HEADER] + body)
        return f"backfill:{len(fetched)}"

    header, body = _read_text_lines(path)
    if not body:
        return "failed:unreadable"
    existing_dates = {ln.split(",")[0] for ln in body}
    last_iso = max(existing_dates)
    today = pd.Timestamp(date.today()).normalize()
    last_dt = pd.Timestamp(last_iso)

    if (today - last_dt).days > STALE_DAYS:
        fetched = fetch_bars(symbol, end_exclusive=tomorrow,
                             period=BACKFILL_PERIOD)
    else:
        window_start = (last_dt - pd.Timedelta(days=GAP_LOOKBACK_DAYS)
                        ).strftime("%Y-%m-%d")
        fetched = fetch_bars(symbol, start_date=window_start,
                             end_exclusive=tomorrow)
    if fetched.empty:
        return "unchanged"

    added = [(iso, txt) for iso, txt in _fmt_row_texts(fetched)
             if iso not in existing_dates]
    if not added:
        return "unchanged"

    new_isos = [iso for iso, _ in added]
    kind = "append" if all(iso > last_iso for iso in new_isos) else "merge"
    if dry_run:
        return f"{kind}:{len(added)}"

    lines = body + [txt for _, txt in added]
    lines.sort(key=lambda ln: ln.split(",")[0])  # stable keeps original order
    _atomic_write(path, ([header] if header else [HEADER]) + lines)
    return f"{kind}:{len(added)}"


def update_all(symbols=None, dry_run: bool = False) -> dict:
    """Update the whole universe (or the given symbols)."""
    import time
    symbols = list(symbols or (NSE_STOCKS + BENCHMARK_SYMBOLS))
    summary = {"updated": 0, "backfilled": 0, "merged": 0,
               "unchanged": 0, "failed": 0, "details": {}}
    for sym in symbols:
        try:
            status = update_one(sym, dry_run=dry_run)
        except Exception as exc:  # one bad symbol must not abort the rest
            status = f"failed:{type(exc).__name__}:{str(exc)[:80]}"
        summary["details"][sym] = status
        if status.startswith("append"):
            summary["updated"] += 1
        elif status.startswith("backfill"):
            summary["backfilled"] += 1
        elif status.startswith("merge"):
            summary["merged"] += 1
        elif status.startswith("unchanged"):
            summary["unchanged"] += 1
        else:
            summary["failed"] += 1
        if not dry_run and POLITE_SLEEP:
            time.sleep(POLITE_SLEEP)
    return summary


def update_all_price_files() -> dict:
    """Shortcut used by the scheduler hook in schedular.job_morning_scan."""
    return update_all()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Update raw_data/prices CSVs")
    ap.add_argument("-s", "--symbols", default=None,
                    help="comma-separated symbols (e.g. RELIANCE,TCS); "
                         "default: whole universe")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing files")
    args = ap.parse_args()

    sel = None
    if args.symbols:
        sel = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    res = update_all(symbols=sel, dry_run=args.dry_run)
    mode = "DRY-RUN" if args.dry_run else "RESULT"
    print(f"[{mode}] updated={res['updated']} backfilled={res['backfilled']} "
          f"merged={res['merged']} unchanged={res['unchanged']} "
          f"failed={res['failed']}")
    for sym, status in res["details"].items():
        if not status.startswith("unchanged"):
            print(f"  {sym}: {status}")