"""validate_pilot.py — Historical study of the Tier-2 Pilot-Buy filters.

The pilot path (config.ENABLE_PILOT_BUYS) only matters on days when NIFTY
trades below its 50-day EMA -- the BUY-suppressed regime. This script replays
the ENTIRE frozen raw_data/prices history (network-free, point-in-time) and,
on exactly those days, measures whether stocks that would have satisfied the
pilot filters actually outperformed the index afterwards.

It is a NECESSARY-CONDITION study of the marginal filter set the pilot path
layered on top of the full deterministic gate (which is far stricter -- see
screener.evaluate_buy_eligibility + fundamental_buy_gate). Baselines are
computed for the suppressed universe and for the "above own 50d/200d EMAs"
subset, and the RS / volume thresholds are SWEPT so the data -- not intuition
-- picks the operating point.

Usage:
    python validate_pilot.py                  # full universe, live config
    python validate_pilot.py --symbols 60     # quick subset
    python validate_pilot.py --out validation_pilot.json
"""
import argparse
import json
from datetime import datetime

import numpy as np
import pandas as pd

from config import (ENABLE_PILOT_BUYS, PILOT_MIN_RS_VS_NIFTY,
                    PILOT_BREAKOUT_VOLUME_RATIO, PILOT_MIN_EPS_GROWTH,
                    PILOT_MIN_20D_TRADED_VALUE)
from price_store import list_symbols, load_adjusted

NIFTY_SYMBOL = "^NSEI"
WARMUP_BARS = 240            # 200d EMA + 21d RS need history first
FORWARD_BARS = (1, 5, 10)
MIN_SIGNAL_SAMPLE = 30

_EPS_CACHE: dict = {}


def expanding_ema(series: pd.Series, span: int) -> pd.Series:
    """Causal (expanding-window) EMA -- no look-ahead at any bar."""
    return series.astype(float).ewm(span=span, adjust=False).mean()


def _eps_growth_asof(symbol: str, when) -> float | None:
    """Point-in-time earningsGrowth (statements/backfill preferred)."""
    key = (symbol, str(when)[:10])
    if key in _EPS_CACHE:
        return _EPS_CACHE[key]
    value = None
    try:
        from fundamental_snapshots import load_snapshot_as_of
        snap = load_snapshot_as_of(symbol, when)
        if snap:
            g = snap.get("earningsGrowth", snap.get("earningsQuarterlyGrowth"))
            value = float(g) if g is not None else None
    except Exception:
        value = None
    _EPS_CACHE[key] = value
    return value


def study_one_symbol(symbol: str, nifty_c: pd.Series, nifty_ema50: pd.Series) -> dict:
    """Replay one symbol aligned to the shared NIFTY calendar.

    Stocks and ^NSEI are inner-joined ON DATES, so partial / extra stock bars
    (recent listings, missing sessions) can never misalign the regime mask.

    Returns one row per SUPPRESSED day (NIFTY < its 50-day EMA), raw and
    unfiltered by RS/volume -- the threshold sweep masks these afterwards.
    """
    df = load_adjusted(symbol, period="5y", interval="1d")
    if df is None or len(df) < WARMUP_BARS + 1:
        return {"symbol": symbol, "n": 0}

    combo = pd.DataFrame({
        "close":  df["Close"].astype(float),
        "high":   df["High"].astype(float),
        "vol":    df["Volume"].astype(float),
        "nclose": nifty_c.astype(float),
        "nema50": nifty_ema50.astype(float),
    }).dropna()
    if len(combo) < WARMUP_BARS + FORWARD_BARS[-1] + 1:
        return {"symbol": symbol, "n": 0}

    close = combo["close"]
    ema50 = expanding_ema(close, 50)
    ema200 = expanding_ema(close, 200)
    # Must match the live definition: the breakout bar is excluded from the
    # preceding 20-session mean-volume and median-value baselines.
    vol20 = combo["vol"].shift(1).rolling(20, min_periods=20).mean()
    vol_ratio = (combo["vol"] / vol20.replace(0, np.nan)).fillna(0.0).clip(upper=10.0)
    value20 = (combo["close"] * combo["vol"]).shift(1).rolling(20, min_periods=20).median()
    res10 = combo["high"].shift(1).rolling(10, min_periods=5).max()
    suppressed = (combo["nclose"] < combo["nema50"]).values
    stock_r21 = close / close.shift(21) - 1.0
    nifty_r21 = combo["nclose"] / combo["nclose"].shift(21) - 1.0

    c = close.values
    nc = combo["nclose"].values
    dates, rs, vr, ema_ok, res_ok, liquid_ok = [], [], [], [], [], []
    fw = {k: [] for k in FORWARD_BARS}
    nw = {k: [] for k in FORWARD_BARS}

    for i in range(WARMUP_BARS, len(c) - FORWARD_BARS[-1] - 1):
        if not suppressed[i]:
            continue
        a_emas = bool(c[i] > ema50.iloc[i] and c[i] > ema200.iloc[i])
        a_res = bool(c[i] > res10.iloc[i])
        sr = stock_r21.iloc[i]
        nr = nifty_r21.iloc[i]
        if not (np.isfinite(sr) and np.isfinite(nr)):
            continue
        dates.append(str(combo.index[i].date()) if hasattr(combo.index[i], "date")
                     else str(combo.index[i]))
        rs.append(float((1.0 + sr) / (1.0 + nr)))
        vr.append(float(vol_ratio.iloc[i]))
        ema_ok.append(a_emas)
        res_ok.append(a_res)
        liquid_ok.append(bool(value20.iloc[i] >= PILOT_MIN_20D_TRADED_VALUE))
        for k in FORWARD_BARS:
            fw[k].append(float(c[i + k] / c[i] - 1.0))
            nw[k].append(float(nc[i + k] / nc[i] - 1.0))
    return {
        "symbol": symbol,
        "n": len(dates),
        "dates": dates,
        "rs": np.array(rs),
        "vol_ratio": np.array(vr),
        "ema_ok": np.array(ema_ok),
        "res_ok": np.array(res_ok),
        "liquid_ok": np.array(liquid_ok),
        "f1": np.array(fw[1]), "f5": np.array(fw[5]), "f10": np.array(fw[10]),
        "n10": np.array(nw[10]),
    }


def _summarize(mask: np.ndarray, f5: np.ndarray, f10: np.ndarray,
               n10: np.ndarray) -> dict:
    n = int(mask.sum())
    if n == 0:
        return {"n_signals": 0}
    alpha = (1 + f10[mask]) / (1 + n10[mask]) - 1
    return {
        "n_signals": n,
        "win_pct_f5": round(float(np.nanmean(f5[mask] > 0) * 100), 2),
        "median_alpha_f10": round(float(np.nanmedian(alpha)), 3),
        "mean_alpha_f10": round(float(np.nanmean(alpha)), 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", type=int, default=None)
    ap.add_argument("--rs", nargs="*", type=float, default=[1.00, 1.10, 1.15])
    ap.add_argument("--vol", nargs="*", type=float, default=[1.0, 1.5])
    ap.add_argument("--min-signals", type=int, default=MIN_SIGNAL_SAMPLE)
    ap.add_argument("--out", default="validation_pilot.json")
    args = ap.parse_args()

    nifty = load_adjusted(NIFTY_SYMBOL, period="5y", interval="1d")
    if nifty is None or len(nifty) < WARMUP_BARS:
        print("No ^NSEI history available locally. Run update_price_files.py first.")
        return 1
    nifty_c = nifty["Close"].astype(float)
    nifty_ema50 = expanding_ema(nifty_c, 50)

    symbols = sorted(s for s in list_symbols() if s != NIFTY_SYMBOL)
    if args.symbols:
        symbols = symbols[: args.symbols]
    print(f"Pilot study: {len(symbols)} symbols x {len(nifty)} sessions "
          f"(NIFTY<EMA50 regime only).")

    # Pass 1: one replay per symbol keeping every suppressed-day row unfiltered
    # by RS/volume so the threshold sweep below is pure numpy masking.
    studies = [study_one_symbol(sym, nifty_c, nifty_ema50)
               for sym in symbols]

    base_f5, ema_f5 = [], []
    for st in studies:
        if st["n"] == 0:
            continue
        base_f5.extend(st["f5"].tolist())
        ema_f5.extend(st["f5"][st["ema_ok"]].tolist())

    rs_vals = sorted(set(float(r) for r in args.rs))
    vol_vals = sorted(set(float(v) for v in args.vol))
    alive = [st for st in studies if st["n"]]
    if not alive:
        print("\n[INFO] No NIFTY<EMA50 regime days matched in this subset/history.")
        print("  Nothing to validate (regime never suppressed, or subset too small).")
        return _finish_empty(args.out, args.min_signals)
    stacked = {k: np.concatenate([st[k] for st in alive])
               for k in ("rs", "vol_ratio", "ema_ok", "res_ok", "liquid_ok", "f5", "f10", "n10")}
    # Base = suppressed day AND price above own 50d/200d EMAs AND close above
    # the 10-session high (the breakout leg of the pilot filter set).
    base_cond = (stacked["ema_ok"] & stacked["res_ok"] & stacked["liquid_ok"]).astype(bool)

    sweep = {}
    for rs_t in rs_vals:
        for vol_t in vol_vals:
            mask = (base_cond & (stacked["vol_ratio"] >= vol_t)
                    & (stacked["rs"] >= rs_t))
            sweep[f"rs{rs_t:.2f}/vol{vol_t:.1f}"] = _summarize(
                mask, stacked["f5"], stacked["f10"], stacked["n10"])

    # Pinned cell = the LIVE config thresholds.
    pinned_key = (f"rs{PILOT_MIN_RS_VS_NIFTY:.2f}/"
                  f"vol{PILOT_BREAKOUT_VOLUME_RATIO:.1f}")
    if pinned_key not in sweep:
        pinned_mask = (base_cond
                       & (stacked["vol_ratio"] >= PILOT_BREAKOUT_VOLUME_RATIO)
                       & (stacked["rs"] >= PILOT_MIN_RS_VS_NIFTY))
        sweep[pinned_key] = _summarize(pinned_mask, stacked["f5"],
                                       stacked["f10"], stacked["n10"])
    return _finish(args, base_f5, ema_f5, sweep, pinned_key)


def _finish_empty(out: str, min_signals: int) -> int:
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "method": "No NIFTY<EMA50 regime days matched; nothing to validate.",
        "pinned_live_config": {"n_signals": 0},
        "sweep": {},
        "config": {"min_signal_sample": min_signals},
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"\nFull report: {out}")
    return 0


def _finish(args, base_f5: list, ema_f5: list, sweep: dict,
            pinned_key: str) -> int:
    base = {
        "universe_win_pct_f5": round(float(np.nanmean(np.array(base_f5) > 0) * 100), 2) if base_f5 else None,
        "universe_n": len(base_f5),
        "above_own_emas_win_pct_f5": round(float(np.nanmean(np.array(ema_f5) > 0) * 100), 2) if ema_f5 else None,
        "above_own_emas_n": len(ema_f5),
    }
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "method": "Necessary-condition replay of the pilot filters on frozen daily OHLCV. "
                  "Regime: NIFTY<EMA50 only. NOT a full strategy backtest: it excludes "
                  "the live deterministic gate, execution costs, exits and portfolio "
                  "constraints. Results cannot approve the live pilot path.",
        "config": {
            "ENABLE_PILOT_BUYS": ENABLE_PILOT_BUYS,
            "PILOT_MIN_RS_VS_NIFTY": PILOT_MIN_RS_VS_NIFTY,
            "PILOT_BREAKOUT_VOLUME_RATIO": PILOT_BREAKOUT_VOLUME_RATIO,
            "PILOT_MIN_EPS_GROWTH": PILOT_MIN_EPS_GROWTH,
            "PILOT_MIN_20D_TRADED_VALUE": PILOT_MIN_20D_TRADED_VALUE,
            "min_signal_sample": args.min_signals,
        },
        "baselines_suppressed_days": base,
        "pinned_live_config_key": pinned_key,
        "pinned_live_config": sweep.get(pinned_key),
        "sweep": sweep,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    pinned = sweep.get(pinned_key) or {"n_signals": 0}
    print("=" * 66)
    print("PILOT FILTER STUDY (NIFTY < EMA50 days only)")
    print("=" * 66)
    print(f"suppressed-universe    : win@5 {base['universe_win_pct_f5']}%  (n={base['universe_n']})")
    print(f"above-own-EMAs subset  : win@5 {base['above_own_emas_win_pct_f5']}%  (n={base['above_own_emas_n']})")
    print(f"\nLIVE config [{pinned_key}]:  n={pinned.get('n_signals', 0)}")
    print(f"  win@5 {pinned.get('win_pct_f5')}%   median alpha@10 {pinned.get('median_alpha_f10')}")
    print("\nSweep (win@5% / median alpha@10):")
    for k, v in sweep.items():
        print(f"  {k:<16} n={v.get('n_signals', 0):>5}  win@5 {v.get('win_pct_f5', '-'):>6}%  "
              f"alpha@10 {v.get('median_alpha_f10', '-')}")

    n_sig = int(pinned.get("n_signals", 0))
    if n_sig < args.min_signals:
        print(f"\n[WARN] Only {n_sig} pilot signal(s) (< {args.min_signals}) -- INCONCLUSIVE.")
        print("  Do not tune thresholds on this sample. Accumulate more regime days")
        print("  (or consciously lower a threshold) before trusting the pilot path.")
    else:
        base_win = float(base["above_own_emas_win_pct_f5"] or 0)
        lift = float(pinned.get("win_pct_f5", 0) or 0) - base_win
        print(f"\n[OK]   Pilot filters {'ADD' if lift >= 3 else 'did NOT add'} "
              f"{lift:+.1f}pp win@5 over the above-EMA baseline.")
        if lift < 3:
            print("  Re-tune via the sweep (validation_pilot.json) before shipping.")
    print(f"\nFull report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
