"""
market_breadth.py - Market context layer: breadth, participation, regime.

The screener currently reduces market regime to one test (NIFTY vs its EMA50).
A Sr. analyst reads the tape more broadly. This module adds the context the
"bible" needs to judge whether the regime call is trustworthy:

  - breadth_pct_above_ema21 / _ema50 : what fraction of the universe is above
    its own medium/long trend. A rising index with shrinking breadth is a
    narrow, fragile tape (leadership risk); falling index but rising breadth
    happens at reversals.
  - advance_decline_ratio                : median sign of 5-bar returns.
  - avg_pct_from_52w_high                : how far off cycle highs the
    universe sits on average (mean-reversion headroom / overhead supply).
  - volatility_regime                    : NIFTY 20-bar realized-vol percentile
    over the trailing window (low / normal / high).
  - sector_breadth                       : the same breadth metric, bucketed by
    sector using the latest point-in-time fundamental snapshot.
  - relative_movers                      : top/bottom 5-bar performers.

Everything runs ONLY from the frozen raw_data/prices CSVs (no network), so the
snapshot is reproducible and cheap. Output: market_snapshot.json.

CLI:
    python market_breadth.py [--out market_snapshot.json] [--symbols TCS,INFY]
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from price_store import list_symbols, load_adjusted
import paths

NIFTY_SYMBOL = "^NSEI"
VOL_WINDOW = 20
VOL_HISTORY = 250
SNAPSHOT_DIR = paths.dir_path(os.path.join("data_cache", "fundamental_snapshots"))


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def _sector_for(symbol: str) -> str | None:
    """Latest point-in-time snapshot sector for a bare symbol, if any."""
    path = os.path.join(SNAPSHOT_DIR, f"{symbol}.jsonl")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            sector = None
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                values = record.get("values") or {}
                if values.get("sector"):
                    sector = values["sector"]
            return sector
    except OSError:
        return None


def _one_symbol_stats(symbol: str) -> dict | None:
    df = load_adjusted(symbol, period=None, interval="1d")
    if df is None or df.empty or len(df) < 60:
        return None
    close = df["Close"].astype(float)
    e21 = ema(close, 21)
    e50 = ema(close, 50)
    last = close.iloc[-1]
    n52 = min(252, len(close))
    high_52 = df["High"].astype(float).tail(n52).max()
    ret5 = close.iloc[-1] / close.iloc[-6] - 1 if len(close) >= 6 else 0.0
    return {
        "symbol": symbol,
        "above_ema21": bool(last > e21.iloc[-1]),
        "above_ema50": bool(last > e50.iloc[-1]),
        "pct_from_52w_high": round((last / high_52 - 1) * 100, 2) if high_52 else None,
        "ret_5d_pct": round(ret5 * 100, 2),
    }


def market_breadth(symbols=None) -> dict:
    """Breadth / participation statistics over the local universe."""
    if symbols is None:
        symbols = [s for s in list_symbols() if s != NIFTY_SYMBOL]
    stats = []
    for symbol in symbols:
        row = _one_symbol_stats(symbol)
        if row:
            stats.append(row)
    n = len(stats) or 1
    above_21 = sum(1 for s in stats if s["above_ema21"])
    above_50 = sum(1 for s in stats if s["above_ema50"])
    decliners = sum(1 for s in stats if s["ret_5d_pct"] < 0)
    distances = [s["pct_from_52w_high"] for s in stats
                 if s["pct_from_52w_high"] is not None]
    return {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe_scanned": len(stats),
        "breadth_pct_above_ema21": round(100.0 * above_21 / n, 1),
        "breadth_pct_above_ema50": round(100.0 * above_50 / n, 1),
        "advance_ratio_5d": round(1.0 - decliners / n, 3),
        "decliners_5d": decliners,
        "advancers_5d": n - decliners,
        "avg_pct_from_52w_high": round(float(np.mean(distances)), 2) if distances else None,
        "median_pct_from_52w_high": round(float(np.median(distances)), 2) if distances else None,
    }


def volatility_regime(symbol: str = NIFTY_SYMBOL) -> dict:
    """NIFTY 20-bar realized-vol percentile -> low/normal/high label."""
    df = load_adjusted(symbol, period=None, interval="1d")
    empty = {"symbol": symbol, "regime": "unknown", "vol_20d": None,
             "percentile": None, "basis_bars": 0}
    if df is None or df.empty or len(df) < VOL_WINDOW * 2:
        return empty
    ret = df["Close"].astype(float).pct_change().dropna() * 100.0
    vol = ret.rolling(VOL_WINDOW).std().dropna()
    if vol.empty:
        return empty
    hist = vol.tail(VOL_HISTORY)
    current = float(vol.iloc[-1])
    percentile = float((hist <= current).mean())
    if percentile < 0.30:
        label = "low"
    elif percentile <= 0.70:
        label = "normal"
    else:
        label = "high"
    return {
        "symbol": symbol,
        "regime": label,
        "vol_20d": round(current, 3),
        "median_vol_20d": round(float(hist.median()), 3),
        "percentile": round(percentile, 3),
        "basis_bars": int(len(hist)),
    }


def sector_breadth() -> dict:
    """Breadth bucketed by sector (uses latest PIT snapshot sector)."""
    sector_rows = {}
    for symbol in [s for s in list_symbols() if s != NIFTY_SYMBOL]:
        sector = _sector_for(symbol) or "Unknown"
        row = _one_symbol_stats(symbol)
        if not row:
            continue
        sector_rows.setdefault(sector, {"scanned": 0, "above_50": 0})
        sector_rows[sector]["scanned"] += 1
        if row["above_ema50"]:
            sector_rows[sector]["above_50"] += 1
    out = {}
    for sector, counts in sorted(sector_rows.items()):
        out[sector] = {
            "scanned": counts["scanned"],
            "breadth_pct_above_ema50": round(
                100.0 * counts["above_50"] / counts["scanned"], 1),
        }
    return out


def relative_movers(n: int = 10, symbols=None) -> dict:
    """Top/bottom 5-bar performers over the local universe."""
    if symbols is None:
        symbols = [s for s in list_symbols() if s != NIFTY_SYMBOL]
    rows = []
    for symbol in symbols:
        row = _one_symbol_stats(symbol)
        if row:
            rows.append(row)
    rows.sort(key=lambda r: r["ret_5d_pct"], reverse=True)
    return {"leaders": rows[:n], "laggards": rows[-n:][::-1]}


def build_market_snapshot(out: str = None, symbols=None) -> dict:
    out = out or paths.path("market_snapshot.json")
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "local raw_data/prices CSVs (frozen, reproducible)",
        "breadth": market_breadth(symbols=symbols),
        "volatility_regime": volatility_regime(),
        "sector_breadth": sector_breadth(),
        "relative_movers": relative_movers(symbols=symbols),
    }
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, default=str)
    return snapshot


def _print_snapshot(snapshot: dict):
    b = snapshot["breadth"]
    v = snapshot["volatility_regime"]
    print("=" * 66)
    print("MARKET CONTEXT SNAPSHOT")
    print("=" * 66)
    print(f"Universe scanned      : {b['universe_scanned']} symbols")
    print(f"Above EMA21 breadth   : {b['breadth_pct_above_ema21']}%")
    print(f"Above EMA50 breadth   : {b['breadth_pct_above_ema50']}%")
    print(f"Advance ratio (5d)    : {b['advance_ratio_5d']}  "
          f"({b['advancers_5d']} up / {b['decliners_5d']} down)")
    print(f"Avg distance from 52wH: {b['avg_pct_from_52w_high']}%")
    print(f"NIFTY vol regime      : {v['regime'].upper()} "
          f"(20d vol {v['vol_20d']} @ p{v['percentile']*100:.0f})")
    print("-" * 66)
    print("Top leaders (5d):")
    for row in snapshot["relative_movers"]["leaders"][:6]:
        print(f"  {row['symbol']:<16} {row['ret_5d_pct']:+.2f}%  "
              f"EMA21={'Y' if row['above_ema21'] else 'N'}  "
              f"from52wH={row['pct_from_52w_high']}%")
    print("Laggards (5d):")
    for row in snapshot["relative_movers"]["laggards"][:6]:
        print(f"  {row['symbol']:<16} {row['ret_5d_pct']:+.2f}%  "
              f"EMA21={'Y' if row['above_ema21'] else 'N'}  "
              f"from52wH={row['pct_from_52w_high']}%")
    print("-" * 66)
    print("Sector breadth (above EMA50):")
    for sector, s in sorted(snapshot["sector_breadth"].items(),
                            key=lambda kv: -kv[1]["breadth_pct_above_ema50"]):
        print(f"  {sector:<24} {s['breadth_pct_above_ema50']:>5.1f}%  "
              f"(n={s['scanned']})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="market_snapshot.json")
    ap.add_argument("--symbols", default=None,
                    help="comma-separated subset (default: full local universe)")
    args = ap.parse_args()
    symbols = ([s.strip() for s in args.symbols.split(",") if s.strip()]
               if args.symbols else None)
    snapshot = build_market_snapshot(out=args.out, symbols=symbols)
    _print_snapshot(snapshot)
    print(f"\nSaved: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())