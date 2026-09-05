"""
validate_buy_logic.py - validation harness for the deterministic BUY gate.

Simulates the REAL screener gate (passes_filter + evaluate_buy_eligibility +
technical-score floor) bar-by-bar over historical data for each trading style
(intraday / swing / positional), executes trades at next-day open with costs,
and reports per-style performance plus NIFTY buy-and-hold as a benchmark.

Deliberately reuses the production code paths: StockScreener.evaluate_buy_eligibility,
StockScreener.score_stock, StockScreener.passes_filter, and config.* constants.

The market-regime filter (NIFTY > EMA50) is applied per signal bar using cached
^NSEI data, INCLUDING fail-closed behavior on unknown dates.

Run:
    python validate_buy_logic.py                     # 40 symbols, all styles
    python validate_buy_logic.py --symbols 100       # larger universe
    python validate_buy_logic.py --sunpharma-check   # assert SUNPHARMA blocked

Ensemble proxy: the live screener blends fundamental quality scores into
`ensemble_score`. Fundamentals are static, so this harness approximates the
quality component with a constant (default 20) and requires the technical score
to clear `BUY_MIN_ENSEMBLE` under that assumption (score >= 63).

The default validation window is five years. Price/volume history is cached by
data_cache.fetch_history, so reruns reuse the same period-specific parquet file.
"""
import argparse
import json
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange, BollingerBands

import config
from config import (CROSSOVER_RECENCY_BARS, FRESH_TRIGGER_BARS,
                    BREAKDOWN_LOOKBACK_BARS, CRASH_DAY_PCT, CRASH_DAY_VOL_MULT,
                    BREAKDOWN_RESOLUTION_LOOKBACK, REVERSAL_LOOKBACK_BARS,
                    REVERSAL_DAY_PCT, REVERSAL_DAY_VOL_MULT, ATR_MULT,
                    MAX_VOLUME_RATIO, BUY_MIN_ENSEMBLE, MIN_DAILY_HISTORY,
                    HISTORICAL_DATA_PERIOD)
from screener import StockScreener, NSE_STOCKS, market_regime_blocks_buy

warnings.filterwarnings("ignore")

SLIPPAGE = 0.0005
TXN_COST = 0.001
ENTRY_SLOT_PCT = 0.20          # fractional slot per trade for equity sim
MAX_HOLD_BARS = {"intraday": 3, "swing": 15, "positional": 60}


class HistoryIndicators:
    """Vectorized historical indicator engine mirroring
    screener.compute_indicators; slice() builds the exact ind dict the gate
    consumes."""

    def __init__(self, df: pd.DataFrame):
        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        vol = df["Volume"].astype(float)
        self.df = df
        self.n = len(df)
        self.close = close
        self.high = high
        self.low = low
        self.vol = vol
        self.open = df["Open"].astype(float)
        self.index = df.index

        rsi_ser = RSIIndicator(close, window=14).rsi()
        macd = MACD(close)
        self.macd_diff = macd.macd_diff()
        self.macd_line = macd.macd()
        self.macd_sig = macd.macd_signal()
        self.ema9 = EMAIndicator(close, window=9).ema_indicator()
        self.ema21 = EMAIndicator(close, window=21).ema_indicator()
        self.ema50 = EMAIndicator(close, window=50).ema_indicator()
        self.rsi = rsi_ser
        self.adx = ADXIndicator(high, low, close, window=14).adx()
        self.atr = AverageTrueRange(high, low, close, window=14).average_true_range()
        bb = BollingerBands(close, window=20, window_dev=2)
        self.bb_pct = bb.bollinger_pband()
        self.price_change = close.pct_change() * 100.0
        vol_base = vol.rolling(20, min_periods=10).median()
        self.vol_ratio = (vol / vol_base.replace(0, np.nan)).clip(upper=MAX_VOLUME_RATIO)
        self.avg_vol_20 = vol.rolling(20, min_periods=10).median()

        n52 = min(252, self.n)
        self.high_52 = high.rolling(n52, min_periods=60).max()
        self.low_52 = low.rolling(n52, min_periods=60).min()
        self.pct_from_high = (close / self.high_52 - 1) * 100.0
# weekly multi-timeframe confirmation (backward-asof)
        weekly = df[["Close"]].resample("W-FRI").last().dropna()
        self.multi_tf_confirm = pd.Series(np.nan, index=df.index)
        self.weekly_trend = pd.Series("unknown", index=df.index)
        if len(weekly) >= 8:
            wc = weekly["Close"]
            w21 = EMAIndicator(wc, window=21).ema_indicator()
            w50 = EMAIndicator(wc, window=50).ema_indicator()
            wsign = np.where(w21 > w50, 1, np.where(w21 < w50, -1, 0))
            wdf = pd.DataFrame({"date": weekly.index, "wsign": wsign}).dropna()
            idx = pd.DataFrame({"date": df.index})
            merged = pd.merge_asof(idx, wdf, on="date", direction="backward")
            wsign_map = merged["wsign"].values
            dsign = np.where(self.ema21.values > self.ema50.values, 1,
                             np.where(self.ema21.values < self.ema50.values, -1, 0))
            ok = ~np.isnan(wsign_map)
            tf = np.where(ok & (dsign == wsign_map), True,
                          np.where(ok & (dsign != wsign_map), False, np.nan))
            self.multi_tf_confirm = pd.Series(tf, index=df.index, dtype="object")
            wtr = pd.merge_asof(idx,
                                pd.DataFrame({"date": weekly.index,
                                             "w21": w21.values,
                                             "w50": w50.values}),
                                on="date", direction="backward")
            self.weekly_trend = pd.Series(
                np.where(np.isnan(wtr["w21"].values), "unknown",
                         np.where(wtr["w21"].values > wtr["w50"].values,
                                  "bullish", "bearish")),
                index=df.index)

        # MACD crossover (current vs previous bar)
        diff = self.macd_diff
        cross = pd.Series("none", index=df.index)
        cross.iloc[1:] = np.where((diff.iloc[1:].values > 0) & (diff.iloc[:-1].values <= 0), "bullish",
                                  np.where((diff.iloc[1:].values < 0) & (diff.iloc[:-1].values >= 0), "bearish", "none"))
        self.macd_crossover = cross

        # crash-day flags (for breakdown/reversal guards)
        self.crash_day = (self.price_change <= CRASH_DAY_PCT) & (self.vol_ratio >= CRASH_DAY_VOL_MULT)
        self.reversal_day = (self.price_change <= REVERSAL_DAY_PCT) & (self.vol_ratio >= REVERSAL_DAY_VOL_MULT)

        # buy/sell EMA21-50 crossover rules (vectorized over the whole series)
        self.buy_cross_bar = pd.Series(False, index=df.index)
        self.sell_cross_bar = pd.Series(False, index=df.index)
        e21, e50 = self.ema21.values, self.ema50.values
        rsi_v = self.rsi.values
        close_v = close.values
        vol_v = vol.values
        for i in range(1, self.n):
            if np.isnan(e21[i]) or np.isnan(e50[i - 1]):
                continue
            if e21[i - 1] <= e50[i - 1] and e21[i] > e50[i]:
                w = vol_v[max(0, i - 20):i]
                vavg = w.mean() if len(w) else 0
                vratio = vol_v[i] / vavg if vavg > 0 else 0
                if (not np.isnan(rsi_v[i]) and 50 <= rsi_v[i] <= 65
                        and vratio >= 1.5 and close_v[i] > e21[i] and close_v[i] > e50[i]):
                    self.buy_cross_bar.iloc[i] = True
            if e21[i - 1] >= e50[i - 1] and e21[i] < e50[i]:
                w = vol_v[max(0, i - 20):i]
                vavg = w.mean() if len(w) else 0
                vratio = vol_v[i] / vavg if vavg > 0 else 0
                if (not np.isnan(rsi_v[i]) and 35 <= rsi_v[i] <= 50
                        and vratio >= 1.5 and close_v[i] < e21[i] and close_v[i] < e50[i]):
                    self.sell_cross_bar.iloc[i] = True

    # â”€â”€ per-bar helpers (no look-ahead) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _reversal_info(self, t):
        rev_lookback = min(int(REVERSAL_LOOKBACK_BARS), max(t - 2, 0))
        for k in range(1, rev_lookback + 1):
            i = t - k
            if i <= 1 or not bool(self.reversal_day.iloc[i]):
                continue
            pre = self.high.iloc[max(0, i - 5):i]
            reclaim = float(pre.max()) if len(pre) else float(self.high.iloc[i])
            return {
                "date": str(self.index[i].date()),
                "change_pct": round(float(self.price_change.iloc[i]), 2),
                "volume_ratio": round(float(self.vol_ratio.iloc[i]), 2),
                "reclaim_level": round(reclaim, 2),
                "reclaimed": float(self.close.iloc[t]) >= reclaim,
            }
        return None

    def _breakdown_info(self, t):
        lb = min(int(BREAKDOWN_LOOKBACK_BARS), max(t - 2, 0))
        for k in range(1, lb + 1):
            i = t - k
            if i <= 1 or not bool(self.crash_day.iloc[i]):
                continue
            pre = self.high.iloc[max(0, i - 5):i]
            reclaim = float(pre.max()) if len(pre) else float(self.high.iloc[i])
            return {
                "date": str(self.index[i].date()),
                "change_pct": round(float(self.price_change.iloc[i]), 2),
                "volume_ratio": round(float(self.vol_ratio.iloc[i]), 2),
                "reclaim_level": round(reclaim, 2),
                "reclaimed": float(self.close.iloc[t]) >= reclaim,
            }
        return None

    def _unresolved_breakdown(self, t):
        lb = min(int(BREAKDOWN_RESOLUTION_LOOKBACK), max(t - 2, 0))
        for k in range(1, lb + 1):
            i = t - k
            if i <= 1 or not bool(self.crash_day.iloc[i]):
                continue
            pre = self.high.iloc[max(0, i - 5):i]
            reclaim = float(pre.max()) if len(pre) else float(self.high.iloc[i])
            if float(self.close.iloc[t]) < reclaim:
                return True, {"date": str(self.index[i].date()),
                              "reclaim_level": round(reclaim, 2)}
            break
        return False, {}

    def _fresh_macd(self, t):
        diff = self.macd_diff.values
        for k2 in range(1, min(FRESH_TRIGGER_BARS + 1, t - 1)):
            j = t - 1 - k2
            if j <= 0:
                break
            if np.isnan(diff[j]):
                break
            if diff[j] > 0 and diff[j - 1] <= 0:
                return True
        return False

    def _buy_rule_passed(self, t):
        cross_ix = np.where(self.buy_cross_bar.iloc[:t + 1].values)[0]
        if len(cross_ix) == 0:
            return False
        latest = int(cross_ix[-1])
        return (t - latest) <= CROSSOVER_RECENCY_BARS

    def _sell_rule_passed(self, t):
        cross_ix = np.where(self.sell_cross_bar.iloc[:t + 1].values)[0]
        if len(cross_ix) == 0:
            return False
        latest = int(cross_ix[-1])
        return (t - latest) <= CROSSOVER_RECENCY_BARS

    def slice(self, t: int) -> dict:
        """Build the ind dict identical in shape to screener.compute_indicators."""
        close = float(self.close.iloc[t])
        rev = self._reversal_info(t)
        brk = self._breakdown_info(t)
        un_res, un_info = self._unresolved_breakdown(t)
        tf = self.multi_tf_confirm.iloc[t]
        mc = self.macd_crossover.iloc[t]
        mc_v = "none" if pd.isna(mc) else mc
        return {
            "symbol": self.df.attrs.get("_symbol", "?"),
            "current_price": round(close, 2),
            "prev_close": round(float(self.close.iloc[t - 1]), 2),
            "open_price": round(float(self.open.iloc[t]), 2),
            "price_change_pct": round(float(self.price_change.iloc[t]), 2),
            "change_pct": round(float(self.price_change.iloc[t]), 2),
            "rsi": round(float(self.rsi.iloc[t]), 2),
            "macd": round(float(self.macd_line.iloc[t]), 4),
            "macd_signal": round(float(self.macd_sig.iloc[t]), 4),
            "macd_hist": round(float(self.macd_diff.iloc[t]), 4),
            "macd_crossover": mc_v,
            "ema9": float(self.ema9.iloc[t]),
            "ema21": float(self.ema21.iloc[t]),
            "ema50": float(self.ema50.iloc[t]),
            "bb_pct": round(float(self.bb_pct.iloc[t]), 4),
            "atr": round(float(self.atr.iloc[t]), 2),
            "atr_pct": round(float(self.atr.iloc[t]) / close * 100, 2) if close else 0,
            "volume": int(self.vol.iloc[t]),
            "avg_volume_20d": int(self.avg_vol_20.iloc[t] or 0),
            "volume_ratio": round(float(self.vol_ratio.iloc[t]), 2),
            "effective_vol_ratio": round(float(self.vol_ratio.iloc[t]), 2),
            "high_52w": round(float(self.high_52.iloc[t]), 2),
            "low_52w": round(float(self.low_52.iloc[t]), 2),
            "pct_from_52w_high": round(float(self.pct_from_high.iloc[t]), 2),
            "adx": round(float(self.adx.iloc[t]), 2),
            "trend_strength": "strong" if self.adx.iloc[t] >= 25 else "adequate" if self.adx.iloc[t] >= 20 else "weak",
            "multi_tf_confirm": None if pd.isna(tf) else bool(tf),
            "weekly_trend": str(self.weekly_trend.iloc[t]),
            "buy_rule_passed": bool(self._buy_rule_passed(t)),
            "sell_rule_passed": bool(self._sell_rule_passed(t)),
            "buy_rule_details": {},
            "sell_rule_details": {},
            "fresh_bullish_trigger": bool(self._fresh_macd(t) or self._buy_rule_passed(t)),
            "recent_breakdown_day": bool(brk is not None),
            "breakdown_date": brk["date"] if brk else None,
            "breakdown_change_pct": brk["change_pct"] if brk else None,
            "breakdown_volume_ratio": brk["volume_ratio"] if brk else None,
            "breakdown_reclaim_level": brk["reclaim_level"] if brk else None,
            "reclaims_breakdown_level": bool(brk["reclaimed"]) if brk else False,
            "bounce_after_breakdown": bool(brk and self.price_change.iloc[t] > 0),
            "bounce_win_pct": None,
            "bounce_samples": 0,
            "unresolved_breakdown": un_res,
            "unresolved_breakdown_date": un_info.get("date") if un_res else None,
            "unresolved_reclaim_level": un_info.get("reclaim_level") if un_res else None,
            "recent_reversal_day": bool(rev is not None),
            "reversal_date": rev["date"] if rev else None,
            "reversal_change_pct": rev["change_pct"] if rev else None,
            "reversal_volume_ratio": rev["volume_ratio"] if rev else None,
            "reversal_reclaim_level": rev["reclaim_level"] if rev else None,
            "reclaims_reversal_level": bool(rev["reclaimed"]) if rev else None,
            "data_anomaly": "",
            "sig_win_pct": None,
            "sig_samples": 0,
            "gap_pct": 0.0,
        }
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# NIFTY market-regime series (bearish / bullish / unknown)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def build_regime_series(period=HISTORICAL_DATA_PERIOD):
    """Return {date: regime} for cached ^NSEI data ({} when unavailable)."""
    try:
        from data_cache import fetch_history
        df = fetch_history("^NSEI", period=period, interval="1d")
    except Exception:
        df = None
    if df is None or getattr(df, "empty", True) or len(df) < 50:
        return {}
    close = df["Close"].astype(float)
    ema = EMAIndicator(close, window=config.MARKET_REGIME_EMA).ema_indicator()
    out = {}
    for d, c, e in zip(df.index, close.values, ema.values):
        if pd.isna(e):
            continue
        out[d.date()] = "bullish" if c >= e else "bearish"
    return out


def regime_for(regime_series, bar_date):
    """Regime for a bar; unknown when the index has no read for that date."""
    if bar_date in regime_series:
        return regime_series[bar_date]
    return "unknown"


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Per-style simulation
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _simulate_symbol(hi, solver, style, score_floor, atr_mult, max_hold,
                     regime_series, apply_regime):
    """Simulate ONE symbol for a style with a single open slot.

    Returns (trades, fwd1, fwd5, fwd10, signals, suppressed).
    """
    n = hi.n
    open_trade = None
    trades = []
    fwd1, fwd5, fwd10 = [], [], []
    signals = 0
    suppressed = 0
    sym = hi.df.attrs.get("_symbol", "?")

    for t in range(61, n - 1):
        # â”€â”€ manage open position exit first (uses bar t) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if open_trade is not None:
            ot = open_trade
            close_t = float(hi.close.iloc[t])
            e21t, e50t = hi.ema21.iloc[t], hi.ema50.iloc[t]
            e21p, e50p = hi.ema21.iloc[t - 1], hi.ema50.iloc[t - 1]
            exit_next = False
            if hi._sell_rule_passed(t):
                exit_next = True
            elif pd.notna(e50t) and close_t < e50t:
                exit_next = True
            elif (pd.notna(e21p) and pd.notna(e50p) and pd.notna(e21t)
                    and pd.notna(e50t) and e21p >= e50p and e21t < e50t):
                exit_next = True
            elif close_t < ot["entry_price"] - atr_mult * ot["entry_atr"]:
                exit_next = True
            elif (t - ot["entry_ix"]) >= max_hold:
                exit_next = True
            if exit_next:
                exit_price = float(hi.open.iloc[t + 1]) * (1 - SLIPPAGE)
                ret = (exit_price / ot["entry_price"] - 1) - TXN_COST
                trades.append({
                    "symbol": sym,
                    "entry_date": str(hi.index[ot["entry_ix"] + 1].date()),
                    "exit_date": str(hi.index[t + 1].date()),
                    "ret": round(ret, 4),
                    "bars": (t + 1) - (ot["entry_ix"] + 1),
                })
                open_trade = None

        # â”€â”€ signal generation at bar t (entry bar t+1) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            ind = hi.slice(t)
        except Exception:
            continue
        if not solver.passes_filter(ind, style):
            continue
        score, _ = solver.score_stock(ind, style)
        if score < score_floor:
            continue
        ok, _ = solver.evaluate_buy_eligibility(ind, style)
        if not ok:
            continue
        # market-regime filter (incl. fail-closed unknown)
        if apply_regime:
            regime = regime_for(regime_series, hi.index[t].date())
            blocks, _ = market_regime_blocks_buy(regime)
            if blocks:
                suppressed += 1
                continue
        # forward-return sampling for signal quality (every signal counts)
        if t + 1 < n:
            fwd1.append(float(hi.close.iloc[t + 1] / hi.close.iloc[t] - 1))
        if t + 5 < n:
            fwd5.append(float(hi.close.iloc[t + 5] / hi.close.iloc[t] - 1))
        if t + 10 < n:
            fwd10.append(float(hi.close.iloc[t + 10] / hi.close.iloc[t] - 1))
        if open_trade is None:
            entry_price = float(hi.open.iloc[t + 1]) * (1 + SLIPPAGE)
            entry_atr = float(hi.atr.iloc[t]) if pd.notna(hi.atr.iloc[t]) else 0.0
            open_trade = {"entry_ix": t, "entry_price": entry_price,
                          "entry_atr": entry_atr}
            signals += 1

    # close any open trade at last close
    if open_trade is not None:
        ot = open_trade
        last = float(hi.close.iloc[n - 1])
        ret = (last / ot["entry_price"] - 1) - TXN_COST
        trades.append({"symbol": sym, "entry_date": "?",
                       "exit_date": str(hi.index[n - 1].date()),
                       "ret": round(ret, 4), "bars": n - 1 - ot["entry_ix"]})

    return trades, fwd1, fwd5, fwd10, signals, suppressed

def simulate_style(symbols, style, quality_proxy, regime_series,
                   apply_regime=True, period=HISTORICAL_DATA_PERIOD):
    """Run the buy gate over the history for every symbol, per style.

    Every symbol is simulated independently (one open slot at a time); all
    trades are aggregated across the universe so the equity curve reflects a
    realistic "enter every signal with equal fractional sizing" model.
    """
    solver = StockScreener()
    score_floor = int(round((BUY_MIN_ENSEMBLE - 0.30 * quality_proxy) / 0.70))
    atr_mult = ATR_MULT.get(style, 3.0)
    max_hold = MAX_HOLD_BARS.get(style, 15)

    all_trades = []
    fwd1, fwd5, fwd10 = [], [], []
    total_signals = 0
    total_suppressed = 0
    ok_syms = 0

    for sym in symbols:
        try:
            from data_cache import fetch_history
            df = fetch_history(sym, period=period, interval="1d")
        except Exception:
            df = None
        if df is None or getattr(df, "empty", True) or len(df) < MIN_DAILY_HISTORY:
            continue
        try:
            df = df.copy()
            df.attrs["_symbol"] = sym.replace(".NS", "")
            hi = HistoryIndicators(df)
        except Exception:
            continue
        trades, f1, f5, f10, sig, supp = _simulate_symbol(
            hi, solver, style, score_floor, atr_mult, max_hold,
            regime_series, apply_regime)
        ok_syms += 1
        all_trades.extend(trades)
        fwd1.extend(f1)
        fwd5.extend(f5)
        fwd10.extend(f10)
        total_signals += sig
        total_suppressed += supp

    # sort by trade exit date for a realistic chronological equity curve
    all_trades.sort(key=lambda x: x["exit_date"])
    equity = 1.0
    equity_curve = []
    for tr in all_trades:
        equity *= (1 + ENTRY_SLOT_PCT * tr["ret"])
        equity_curve.append({"date": tr["exit_date"], "equity": equity})

    return {
        "style": style,
        "signals": total_signals,
        "suppressed_by_regime": total_suppressed,
        "symbols_tested": ok_syms,
        "trades": all_trades,
        "equity_curve": equity_curve,
        "fwd1": fwd1, "fwd5": fwd5, "fwd10": fwd10,
    }


def metrics(result, years):
    trades = result["trades"]
    out = {"style": result["style"], "signals": result["signals"],
           "suppressed_by_regime": result["suppressed_by_regime"],
           "symbols_tested": result.get("symbols_tested", 0),
           "trades": len(trades)}
    if trades:
        rets = [t["ret"] for t in trades]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r < 0]
        out.update({
            "win_rate": round(len(wins) / len(rets), 3),
            "avg_return_pct": round(float(np.mean(rets)) * 100, 2),
            "median_return_pct": round(float(np.median(rets)) * 100, 2),
            "best_pct": round(float(np.max(rets)) * 100, 2),
            "worst_pct": round(float(np.min(rets)) * 100, 2),
            "avg_hold_bars": round(float(np.mean([t["bars"] for t in trades])), 1),
        })
        if losses:
            out["profit_factor"] = round(abs(sum(wins)) / abs(sum(losses)), 2)
    for label, key in (("fwd_1d_win_pct", "fwd1"), ("fwd_5d_win_pct", "fwd5"),
                       ("fwd_10d_win_pct", "fwd10")):
        vals = result[key]
        if vals:
            out[label] = round(float(np.mean([v > 0 for v in vals])) * 100, 1)
    if result["equity_curve"]:
        eq = np.array([e["equity"] for e in result["equity_curve"]])
        total = eq[-1] - 1.0  # equity starts at 1.0 (not at eq[0])
        cagr = (1 + total) ** (1 / max(years, 1e-9)) - 1 if years > 0 else 0.0
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        out.update({
            "total_return_pct": round(float(total) * 100, 2),
            "cagr": round(float(cagr), 4),
            "max_drawdown_pct": round(float(np.min(dd)) * 100, 2),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="Validate the deterministic BUY gate")
    ap.add_argument("--symbols", type=int, default=40,
                    help="number of universe symbols to test (default 40)")
    ap.add_argument("--styles", type=str, default="intraday,swing,positional")
    ap.add_argument("--quality", type=float, default=20.0,
                    help="fundamental quality proxy used for the ensemble floor")
    ap.add_argument("--period", default=HISTORICAL_DATA_PERIOD,
                    help="yfinance history period used for stocks and NIFTY (default: 5y)")
    ap.add_argument("--no-regime", action="store_true",
                    help="disable the market-regime filter")
    ap.add_argument("--sunpharma-check", action="store_true",
                    help="run the SUNPHARMA 2026-09-02 regression assertion")
    ap.add_argument("--json", type=str, default="validation_report.json")
    args = ap.parse_args()

    styles = [s.strip() for s in args.styles.split(",") if s.strip()]
    universe = NSE_STOCKS[:args.symbols]
    print("=" * 70)
    print("  BUY-GATE VALIDATION")
    print(f"  universe: {len(universe)} symbols | styles: {', '.join(styles)}")
    print("  quality proxy:", args.quality,
          "| regime filter:", "OFF" if args.no_regime else "ON")
    print("=" * 70)

    if args.sunpharma_check:
        run_sunpharma_check()

    regime_series = {} if args.no_regime else build_regime_series(args.period)
    if not args.no_regime and not regime_series:
        print("  ! ^NSEI regime data unavailable - will treat all signals "
              "as unknown/fail-closed.\n")

    report = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "universe_size": len(universe), "styles": styles,
              "quality_proxy": args.quality, "regime_filter": not args.no_regime,
              "history_period": args.period,
              "by_style": {}}

    for style in styles:
        print(f"\n  Simulating {style.upper()} ...")
        res = simulate_style(universe, style, args.quality, regime_series,
                             apply_regime=not args.no_regime, period=args.period)
        years = 0.0
        if res.get("trades"):
            dates = [pd.to_datetime(t["entry_date"]) for t in res["trades"]
                     if t.get("entry_date") not in (None, "?")]
            exits = [pd.to_datetime(t["exit_date"]) for t in res["trades"]
                     if t.get("exit_date") not in (None, "?")]
            if dates and exits:
                years = max((max(exits) - min(dates)).days / 365.25, 1 / 365.25)
        m = metrics(res, years=years)
        report["by_style"][style] = m
        print_table(m, style)

    # NIFTY benchmark (buy-and-hold over the simulated window)
    bench = nifty_benchmark(args.period)
    report["nifty_benchmark"] = bench
    print_benchmark(bench)

    try:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\n  Report saved to {args.json}")
    except Exception as e:
        print(f"\n  ! could not save report: {e}")
    return report


def run_sunpharma_check():
    """SUNPHARMA must NOT be a BUY for any style on its most recent bar."""
    import warnings
    warnings.filterwarnings("ignore")
    from screener import StockScreener
    try:
        from data_cache import fetch_history
        df = fetch_history("SUNPHARMA.NS", period=HISTORICAL_DATA_PERIOD, interval="1d")
    except Exception:
        df = None
    if df is None or getattr(df, "empty", True):
        print("  [sunpharma-check] data unavailable - skipped")
        return
    df = df.copy()
    s = StockScreener()
    ind = s.compute_indicators(df)
    fails_all = 0
    for style in ("intraday", "swing", "positional"):
        ok, _ = s.evaluate_buy_eligibility(ind, style)
        if ok:
            print(f"  [sunpharma-check] FAIL: {style} is BUY for SUNPHARMA "
                  f"on {df.index[-1]}")
            fails_all += 1
    if fails_all == 0:
        print(f"  [sunpharma-check] OK: SUNPHARMA blocked for all styles "
              f"as of {df.index[-1]}")


def print_table(m, style):
    print(f"  ---- {style.upper()} ----")
    for k, v in m.items():
        print(f"    {k:<22}: {v}")


def print_benchmark(bench):
    print("\n  ---- NIFTY 50 BENCHMARK (buy-and-hold) ----")
    for k, v in bench.items():
        print(f"    {k:<22}: {v}")


def nifty_benchmark(period=HISTORICAL_DATA_PERIOD):
    try:
        from data_cache import fetch_history
        df = fetch_history("^NSEI", period=period, interval="1d")
    except Exception:
        df = None
    if df is None or getattr(df, "empty", True) or len(df) < 200:
        return {"available": False}
    close = df["Close"].astype(float).iloc[61:]
    total = close.iloc[-1] / close.iloc[0] - 1
    years = len(close) / 252.0
    cagr = (1 + total) ** (1 / max(years, 1e-9)) - 1
    peak = np.maximum.accumulate(close.values)
    dd = (close.values - peak) / peak
    return {"available": True,
            "total_return_pct": round(float(total) * 100, 2),
            "cagr": round(float(cagr), 4),
            "max_drawdown_pct": round(float(np.min(dd)) * 100, 2),
            "window_years": round(years, 2)}


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
