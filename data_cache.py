import os
import hashlib
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from config import CACHE_DIR, CACHE_TTL_HOURS

os.makedirs(CACHE_DIR, exist_ok=True)


def cache_path(symbol: str, period: str = None, start: str = None,
               end: str = None, interval: str = '1d'):
    """Return a cache key unique to the requested history range and interval."""
    safe = symbol.replace('/', '_').replace(':', '_')
    request = f"period={period}|start={start}|end={end}|interval={interval}"
    suffix = hashlib.sha256(request.encode("utf-8")).hexdigest()[:12]
    return os.path.join(CACHE_DIR, f"{safe}_{suffix}.parquet")


def detect_data_anomaly(df) -> str:
    """Return a human-readable reason if the OHLCV frame shows a likely
    corporate-action discontinuity (split / bonus / consolidation / data glitch).

    A >25% single-bar close move (or a >35% two-bar move) is not a normal NSE
    trading event — it is almost always a split/bonus where the provider flipped
    the adjustment basis mid-series (HINDCOPPER 2026-08-31: pre-split 1037.4 one
    morning, post-split 525.3 the same evening). Technicals computed on such a
    series are garbage: current_price, ATR, RSI, BBands are all meaningless.

    Returns '' when the data looks clean (or detection is impossible).
    """
    try:
        if df is None or getattr(df, "empty", True) or len(df) < 3:
            return ""
        close = df["Close"].astype(float)
        pct = close.pct_change() * 100.0
        last5 = pct.iloc[-5:]
        vals = last5.abs().dropna()
        if vals.empty:
            return ""
        max_jump = float(vals.max())
        max_twobar = 0.0
        last5p = last5.dropna()
        if len(last5p) >= 2:
            for i in range(1, len(last5p)):
                s = last5p.iloc[i - 1] + last5p.iloc[i]
                max_twobar = max(max_twobar, abs(float(s)))
        if max_twobar >= 35.0 or max_jump >= 25.0:
            arg = int(vals.values.argmax())
            # vals excludes the first NaN pct_change, so offset by 1
            bar_idx = max(0, len(pct) - len(vals) + arg)
            bar_date = str(df.index[bar_idx]) if bar_idx < len(df) else "recent"
            move = float(pct.iloc[bar_idx])
            return (f"Data anomaly: {move:+.1f}% single-bar price move near "
                    f"{bar_date} — likely split/bonus; corporate-action data "
                    f"discontinuity detected, indicators not trustworthy")
        cur = float(close.iloc[-1])
        if cur <= 0:
            return f"Data anomaly: last close ₹{cur} is non-positive — unusable data"
        return ""
    except Exception:
        return ""


def mark_data_anomaly(df) -> str:
    """Attach anomaly metadata to a frame as an attr and a stable column.

    The column survives `to_parquet`/`read_parquet`, so a cached frame carries
    the detection with it even after a process restart.
    """
    reason = detect_data_anomaly(df)
    try:
        if reason:
            df.attrs["data_anomaly"] = reason
            if "data_anomaly_str" not in df.columns:
                df["data_anomaly_str"] = reason
            else:
                df["data_anomaly_str"] = df["data_anomaly_str"].where(
                    df["data_anomaly_str"].notna(), reason)
        else:
            df.attrs["data_anomaly"] = ""
            if "data_anomaly_str" not in df.columns:
                df["data_anomaly_str"] = ""
            else:
                df["data_anomaly_str"] = df["data_anomaly_str"].fillna("")
    except Exception:
        pass
    return reason


def fetch_history(symbol: str, period: str = None, start: str = None, end: str = None, interval: str = '1d') -> pd.DataFrame:
    """Fetch OHLCV for a symbol with simple file cache that refreshes every CACHE_TTL_HOURS.
    If cache exists and is fresh, return cached DataFrame.
    Otherwise download and save to cache then return.
    """
    path = cache_path(symbol, period=period, start=start, end=end,
                      interval=interval)
    # check cache freshness
    if os.path.exists(path):
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        if datetime.now() - mtime < timedelta(hours=CACHE_TTL_HOURS):
            try:
                df = pd.read_parquet(path)
                if not getattr(df, "empty", True):
                    mark_data_anomaly(df)
                return df
            except Exception:
                pass
    # fetch
    try:
        ticker = yf.Ticker(symbol)
        if period:
            df = ticker.history(period=period, interval=interval)
        else:
            df = ticker.history(start=start, end=end, interval=interval)
        if df is None or df.empty:
            return pd.DataFrame()

        # normalize index timezone
        try:
            if getattr(df.index, 'tz', None) is not None:
                df.index = df.index.tz_convert(None)
                df.index = df.index.tz_localize(None)
        except Exception:
            try:
                df.index = df.index.tz_localize(None)
            except Exception:
                pass

        # apply adjusted close scaling if available to avoid corporate-action distortions
        try:
            if 'Adj Close' in df.columns and 'Close' in df.columns:
                adj = df['Adj Close'].astype(float)
                raw_close = df['Close'].replace(0, pd.NA).astype(float)
                ratio = adj / raw_close
                ratio.replace([pd.NA, float('inf')], method='ffill', inplace=True)
                ratio.fillna(1.0, inplace=True)
                # scale OHLC
                for col in ['Open', 'High', 'Low']:
                    if col in df.columns:
                        df[col] = (df[col].astype(float) * ratio).astype(float)
                df['Close'] = adj.astype(float)
        except Exception:
            pass

        # ensure numeric columns and drop rows with missing critical values
        try:
            for c in ['Open','High','Low','Close','Volume']:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors='coerce')
            df.dropna(subset=['Open','High','Low','Close'], inplace=True)
        except Exception:
            pass

        # remove duplicate indices
        try:
            if df.index.has_duplicates:
                df = df[~df.index.duplicated(keep='last')]
        except Exception:
            pass

        # corporate-action anomaly detection (split/bonus discontinuity). The
        # column is persisted so even a later cache reader sees the marker.
        try:
            mark_data_anomaly(df)
        except Exception:
            pass

        # save
        try:
            df.to_parquet(path, index=True)
        except Exception:
            pass
        return df
    except Exception:
        return pd.DataFrame()
