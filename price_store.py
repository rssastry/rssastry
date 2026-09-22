"""price_store.py — Read the raw 5-year price CSVs in raw_data/prices.

The CSVs are yfinance-style exports with the exact header
`Date,Adj Close,Close,High,Low,Open,Volume`, where `Adj Close` holds the
split-adjusted close and the OHLC columns hold raw prices.  This module
turns them into the *adjusted* frames the rest of the app expects (the
same normalization data_cache.fetch_history applies to live yfinance
data), so validation and backtests can run against a frozen, local,
point-in-time dataset without hammering the network.

Every function degrades gracefully (empty DataFrame) so callers can fall
back to data_cache.fetch_history when a symbol has no CSV yet.
"""
import os

import numpy as np
import pandas as pd

# Header and column order used by every file in raw_data/prices
CSV_COLUMNS = ["Adj Close", "Close", "High", "Low", "Open", "Volume"]

# Git-tracked copy of the frozen per-symbol CSVs (the "seed" / fallback that
# survives a fresh clone). Not writable on Render's ephemeral filesystem —
# runtime refreshes go to PRICE_DIR instead (see writable_price_dir).
REPO_PRICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "raw_data", "prices")


def _state_root() -> str:
    """Durable-state root from env SA_DATA_DIR ('' = working directory)."""
    root = os.environ.get("SA_DATA_DIR", "").strip()
    if root.lower() in ("0", "false", "no", "off"):
        root = ""
    return root


def writable_price_dir() -> str:
    """Directory where refreshed price CSVs are WRITTEN.

    With SA_DATA_DIR set (e.g. a Render Persistent Disk mounted at /var/data)
    price files live under that durable root; otherwise they live in the repo
    exactly as before. A fresh durable store is seeded from the git-tracked
    CSVs on first use (see update_price_files.update_one), so no history is
    lost when a new disk/machine is provisioned.
    """
    root = _state_root()
    if root:
        return os.path.join(root, "raw_data", "prices")
    return REPO_PRICE_DIR


# Canonical read/write directory for price CSVs.
PRICE_DIR = writable_price_dir()


def symbol_to_filename(symbol: str) -> str:
    """RELIANCE.NS -> RELIANCE.csv (also tolerates bare 'RELIANCE')."""
    bare = symbol.upper().removesuffix(".NS")
    return f"{bare}.csv"


def csv_path_for(symbol: str) -> str:
    return os.path.join(PRICE_DIR, symbol_to_filename(symbol))


def seed_path_for(symbol: str) -> str:
    """Read-only fallback to the git-tracked CSV (used when SA_DATA_DIR is set
    but the durable store has not been seeded for this symbol yet)."""
    return os.path.join(REPO_PRICE_DIR, symbol_to_filename(symbol))


def list_symbols() -> list:
    """Bare-symbol names for every CSV present (durable dir + repo seed)."""
    dirs = [PRICE_DIR]
    if PRICE_DIR != REPO_PRICE_DIR:
        dirs.append(REPO_PRICE_DIR)
    names = set()
    for directory in dirs:
        if os.path.isdir(directory):
            names.update(os.path.splitext(f)[0] for f in os.listdir(directory)
                         if f.lower().endswith(".csv"))
    return sorted(names)


def read_raw(symbol: str) -> pd.DataFrame:
    """Read the raw CSV as-is (unadjusted) with a Date index.

    Reads the durable copy when present, otherwise the git-tracked seed, so a
    freshly-provisioned durable store still answers from the committed CSVs.

    Returns an empty DataFrame when no file exists for the symbol.
    """
    path = csv_path_for(symbol)
    if not os.path.exists(path):
        path = seed_path_for(symbol)
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
    except Exception:
        return pd.DataFrame()
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date").sort_index()
    df.index.name = "Date"
    cols = [c for c in CSV_COLUMNS if c in df.columns]
    return df[cols]


def _resolve_window(period=None, start=None, end=None):
    """Return (start_dt, end_dt) bounds; yfinance-style end is EXCLUSIVE."""
    today = pd.Timestamp.today().normalize()
    start_dt = pd.Timestamp(start) if start else None
    end_dt = pd.Timestamp(end) if end else None

    if period and start_dt is None:
        period = (period or "").strip().lower()
        if period.endswith("y"):
            years = _to_float(period[:-1])
            if years:
                start_dt = today - pd.DateOffset(years=years)
        elif period.endswith("mo"):
            months = _to_float(period[:-2])
            if months:
                start_dt = today - pd.DateOffset(months=months)
        elif period.endswith("d"):
            days = _to_float(period[:-1])
            if days:
                start_dt = today - pd.Timedelta(days=days)
        elif period in ("max",):
            start_dt = None
    return start_dt, end_dt


def _to_float(text: str):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def load_adjusted(symbol: str, period=None, start=None, end=None,
                  interval="1d") -> pd.DataFrame:
    """Return an adjusted OHLCV frame from the CSV for symbol.

    Mirrors the output of data_cache.fetch_history (adjusted close applied
    to OHLC, numeric coercion, duplicate/NaN cleanup, anomaly marker) so a
    caller can swap sources without changing downstream math.

    Only daily data lives in the CSVs; non-daily intervals return empty.
    """
    if interval and str(interval).lower() not in ("1d", "daily", "d"):
        return pd.DataFrame()
    df = read_raw(symbol)
    if df.empty:
        return df

    # Apply the adjusted-close scaling identical to data_cache.fetch_history
    try:
        if "Adj Close" in df.columns and "Close" in df.columns:
            adj = df["Adj Close"].astype(float)
            raw_close = df["Close"].replace(0, pd.NA).astype(float)
            ratio = (adj / raw_close)
            ratio = ratio.replace([pd.NA, np.inf, -np.inf], np.nan)
            ratio = ratio.ffill().fillna(1.0)
            for col in ("Open", "High", "Low"):
                if col in df.columns:
                    df[col] = df[col].astype(float) * ratio
            df["Close"] = adj
    except Exception:
        pass

    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df.index.has_duplicates:
        df = df[~df.index.duplicated(keep="last")]
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)

    start_dt, end_dt = _resolve_window(period, start, end)
    if start_dt is not None:
        df = df[df.index >= start_dt]
    if end_dt is not None:
        df = df[df.index < end_dt]

    if len(df) >= 2:
        try:
            from data_cache import mark_data_anomaly
            mark_data_anomaly(df)
        except Exception:
            pass

    keep = [c for c in ("Open", "High", "Low", "Close", "Volume",
                        "data_anomaly_str") if c in df.columns]
    return df[keep]


def fetch_or_fallback(symbol: str, period=None, start=None, end=None,
                      interval="1d") -> pd.DataFrame:
    """Preferred source is the local CSV; fall back to data_cache."""
    df = load_adjusted(symbol, period=period, start=start, end=end,
                       interval=interval)
    if df is not None and len(df):
        return df
    try:
        from data_cache import fetch_history
        return fetch_history(symbol, period=period, start=start,
                             end=end, interval=interval)
    except Exception:
        return df