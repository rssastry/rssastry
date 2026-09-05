"""
indicators.py — Technical Indicator Engine
Computes all indicators needed for AI analysis
"""

import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, EMAIndicator, SMAIndicator, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator
import yfinance as yf
import warnings
from config import (BREAKDOWN_LOOKBACK_BARS, BREAKDOWN_RESOLUTION_LOOKBACK,
                    CRASH_DAY_PCT, CRASH_DAY_VOL_MULT,
                    FRESH_TRIGGER_BARS, BOUNCE_HIST_MIN_SAMPLES, MAX_VOLUME_RATIO)
warnings.filterwarnings("ignore")


def find_unresolved_breakdown(close, high, vol, index=None,
                              lookback=BREAKDOWN_LOOKBACK_BARS):
    """Scan completed bars for a high-volume crash day (pct <= CRASH_DAY_PCT and
    vol >= CRASH_DAY_VOL_MULT). If one exists within `lookback` bars AND the
    latest close is still below the pre-crash swing high (the reclaim level),
    return (True, info_dict).

    Unlike `recent_breakdown_day` (which expires after a couple of bars), an
    unresolved breakdown does NOT expire — the crash stays a cap on the stock
    until the price actually reclaims the broken level. This is exactly the
    HINDCOPPER trap: crashed 2026-08-24, the 2-bar guard expired, and the stock
    could be re-offered as a BUY while still ₹60 below the broken 586.75 high.
    """
    try:
        n = len(close)
        if n < (max(3, int(lookback)) + 2):
            return False, {}
        pct = close.pct_change() * 100.0
        base = vol.rolling(20, min_periods=10).median()
        vr = (vol / base.replace(0, np.nan)).fillna(0).clip(upper=MAX_VOLUME_RATIO)
        lookback = min(int(lookback), max(n - 2, 0))
        latest = float(close.iloc[-1])
        for k in range(1, lookback + 1):
            i = n - 1 - k
            if i <= 1:
                continue
            if (pct.iloc[i] <= CRASH_DAY_PCT and vr.iloc[i] >= CRASH_DAY_VOL_MULT):
                pre_win = high.iloc[max(0, i - 5):i]
                reclaim = float(pre_win.max()) if len(pre_win) else float(high.iloc[i])
                if latest < reclaim:
                    d = ""
                    if index is not None and i < len(index):
                        ts = index[i]
                        d = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)
                    return True, {
                        "date": d,
                        "change_pct": round(float(pct.iloc[i]), 2),
                        "volume_ratio": round(float(vr.iloc[i]), 2),
                        "reclaim_level": round(reclaim, 2),
                    }
                # A crash day exists but the price has reclaimed it -> resolved.
                break
    except Exception:
        pass
    return False, {}


def bounce_after_breakdown_stats(close, high, vol,
                                 crash_pct=CRASH_DAY_PCT,
                                 crash_vol_mult=CRASH_DAY_VOL_MULT,
                                 min_samples=BOUNCE_HIST_MIN_SAMPLES):
    """Empirical next-session continuation odds for the dead-cat-bounce setup.

    Mirrors `screener._bounce_after_breakdown_stats` so the analysis engine and
    the screener stay consistent: a breakdown day followed by an up session, then
    the % of those bounces that close higher again next session.
    """
    try:
        if close is None or len(close) < 40:
            return None, 0
        pct = close.pct_change() * 100.0
        base = vol.rolling(20, min_periods=10).median()
        vr = (vol / base.replace(0, np.nan)).clip(upper=MAX_VOLUME_RATIO)
        results, setups = [], 0
        for i in range(2, len(close) - 2):
            if not (pct.iloc[i] <= crash_pct and vr.iloc[i] >= crash_vol_mult):
                continue
            if not (close.iloc[i + 1] > close.iloc[i]):
                continue
            setups += 1
            results.append(1.0 if close.iloc[i + 2] > close.iloc[i + 1] else 0.0)
        n = len(results)
        if n < min_samples:
            return None, n
        return round(100.0 * sum(results) / n, 1), n
    except Exception:
        return None, 0


class IndicatorEngine:

    def __init__(self, symbol: str, period: str = "2y"):
        self.symbol = symbol
        self.period = period
        self.df = None
        self.data_anomaly = ""

    def fetch(self) -> bool:
        try:
            # use cached downloader if available
            try:
                from data_cache import fetch_history
                df = fetch_history(self.symbol, period=self.period, interval='1d')
            except Exception:
                ticker = yf.Ticker(self.symbol)
                df = ticker.history(period=self.period, interval="1d")

            if df is None or df.empty:
                return False

            # Data freshness check: warn if the last bar is stale (> 5 calendar days old)
            try:
                last_date = df.index[-1]
                if hasattr(last_date, "date"):
                    last_date = last_date.date()
                from datetime import date
                days_stale = (date.today() - last_date).days
                if days_stale > 5:
                    print(f"  ⚠ {self.symbol}: data is {days_stale} days stale "
                          f"(last bar {last_date})")
            except Exception:
                pass

            # apply adjusted close if present to avoid corporate-action distortions
            if 'Adj Close' in df.columns:
                try:
                    adj = df['Adj Close']
                    raw_close = df['Close']
                    # avoid division by zero
                    ratio = adj / raw_close.replace(0, np.nan)
                    ratio.fillna(method='ffill', inplace=True)
                    # scale OHLC by ratio to get adjusted OHLC
                    df['Open'] = (df['Open'] * ratio).astype(float)
                    df['High'] = (df['High'] * ratio).astype(float)
                    df['Low'] = (df['Low'] * ratio).astype(float)
                    df['Close'] = adj.astype(float)
                except Exception:
                    pass

            df.dropna(inplace=True)
            self.df = df
            # corporate-action anomaly flag (survives parquet round-trips)
            try:
                if "data_anomaly_str" in df.columns:
                    a = str(df["data_anomaly_str"].dropna().iloc[-1])
                    self.data_anomaly = a if a.lower() not in ("", "nan") else ""
                else:
                    self.data_anomaly = getattr(df, "attrs", {}).get("data_anomaly", "")
            except Exception:
                self.data_anomaly = ""
            return len(self.df) >= 20
        except Exception:
            return False

    def compute_all(self) -> dict:
        if self.df is None or len(self.df) < 20:
            return {}

        df    = self.df
        close = df["Close"]
        high  = df["High"]
        low   = df["Low"]
        vol   = df["Volume"]
        open_ = df["Open"]

        # Price
        current          = close.iloc[-1]
        prev             = close.iloc[-2]
        change_pct       = ((current - prev) / prev) * 100
        open_price       = open_.iloc[-1]
        gap_pct          = ((open_price - prev) / prev) * 100

        # RSI
        rsi = RSIIndicator(close, window=14).rsi()

        # MACD
        macd_obj  = MACD(close)
        macd_line = macd_obj.macd()
        macd_sig  = macd_obj.macd_signal()
        macd_hist = macd_obj.macd_diff()
        macd_cross = (
            "bullish" if (macd_hist.iloc[-1] > 0 and macd_hist.iloc[-2] <= 0) else
            "bearish" if (macd_hist.iloc[-1] < 0 and macd_hist.iloc[-2] >= 0) else
            "none"
        )

        # EMAs
        ema9   = EMAIndicator(close, window=9).ema_indicator()
        ema21  = EMAIndicator(close, window=21).ema_indicator()
        ema50  = EMAIndicator(close, window=50).ema_indicator()
        ema200 = EMAIndicator(close, window=min(200, len(close)-1)).ema_indicator()
        sma20  = SMAIndicator(close, window=20).sma_indicator()

        # Bollinger Bands
        bb         = BollingerBands(close, window=20, window_dev=2)
        bb_squeeze = (
            (bb.bollinger_hband().iloc[-1] - bb.bollinger_lband().iloc[-1])
            / bb.bollinger_mavg().iloc[-1] * 100
        )

        # ATR
        atr     = AverageTrueRange(high, low, close, window=14).average_true_range()
        atr_pct = (atr.iloc[-1] / current) * 100

        # Multi-timeframe (weekly) confirmation
        weekly_trend = 'unknown'
        multi_tf_confirm = False
        try:
            weekly = df[['Open','High','Low','Close','Volume']].resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
            if len(weekly) >= 20:
                w_close = weekly['Close']
                w_ema21 = EMAIndicator(w_close, window=21).ema_indicator()
                w_ema50 = EMAIndicator(w_close, window=50).ema_indicator()
                if w_ema21.iloc[-1] > w_ema50.iloc[-1]:
                    weekly_trend = 'bullish'
                elif w_ema21.iloc[-1] < w_ema50.iloc[-1]:
                    weekly_trend = 'bearish'
                else:
                    weekly_trend = 'neutral'
                # confirm if daily and weekly agree on direction
                if (ema21.iloc[-1] > ema50.iloc[-1] and w_ema21.iloc[-1] > w_ema50.iloc[-1]) or (
                    ema21.iloc[-1] < ema50.iloc[-1] and w_ema21.iloc[-1] < w_ema50.iloc[-1]):
                    multi_tf_confirm = True
        except Exception:
            weekly_trend = 'unknown'
            multi_tf_confirm = False

        # ADX
        adx_obj        = ADXIndicator(high, low, close, window=14)
        adx            = adx_obj.adx().iloc[-1]
        adx_pos        = adx_obj.adx_pos().iloc[-1]
        adx_neg        = adx_obj.adx_neg().iloc[-1]
        trend_strength = "strong" if adx > 25 else "weak"

        # Stochastic
        stoch   = StochasticOscillator(high, low, close)
        stoch_k = stoch.stoch().iloc[-1]
        stoch_d = stoch.stoch_signal().iloc[-1]

        # Volume
        avg_vol   = vol.iloc[-20:].mean()
        vol_ratio = vol.iloc[-1] / avg_vol if avg_vol > 0 else 0
        obv       = OnBalanceVolumeIndicator(close, vol).on_balance_volume()
        obv_trend = "rising" if obv.iloc[-1] > obv.iloc[-5] else "falling"

        # EMA 21/50 crossover rules
        bullish_crossover_rule = None
        bearish_crossover_rule = None
        for idx in range(1, len(df)):
            prev_ema21 = ema21.iloc[idx - 1]
            prev_ema50 = ema50.iloc[idx - 1]
            curr_ema21 = ema21.iloc[idx]
            curr_ema50 = ema50.iloc[idx]

            if prev_ema21 <= prev_ema50 and curr_ema21 > curr_ema50:
                vol_window = vol.iloc[max(0, idx - 20):idx]
                avg_vol_day = vol_window.mean() if len(vol_window) > 0 else 0
                day_volume_ratio = vol.iloc[idx] / avg_vol_day if avg_vol_day > 0 else 0
                rsi_day = rsi.iloc[idx]
                price_day = close.iloc[idx]
                above_both = price_day > curr_ema21 and price_day > curr_ema50

                if pd.notna(rsi_day) and 50 <= float(rsi_day) <= 65 and day_volume_ratio >= 1.5 and above_both:
                    bullish_crossover_rule = {
                        "bar_index": idx,
                        "date": df.index[idx].strftime("%Y-%m-%d") if hasattr(df.index[idx], "strftime") else str(df.index[idx]),
                        "volume_ratio": round(float(day_volume_ratio), 2),
                        "rsi": round(float(rsi_day), 2),
                        "close": round(float(price_day), 2),
                        "ema21": round(float(curr_ema21), 2),
                        "ema50": round(float(curr_ema50), 2),
                    }

            if prev_ema21 >= prev_ema50 and curr_ema21 < curr_ema50:
                vol_window = vol.iloc[max(0, idx - 20):idx]
                avg_vol_day = vol_window.mean() if len(vol_window) > 0 else 0
                day_volume_ratio = vol.iloc[idx] / avg_vol_day if avg_vol_day > 0 else 0
                rsi_day = rsi.iloc[idx]
                price_day = close.iloc[idx]
                below_both = price_day < curr_ema21 and price_day < curr_ema50

                if pd.notna(rsi_day) and 35 <= float(rsi_day) <= 50 and day_volume_ratio >= 1.5 and below_both:
                    bearish_crossover_rule = {
                        "bar_index": idx,
                        "date": df.index[idx].strftime("%Y-%m-%d") if hasattr(df.index[idx], "strftime") else str(df.index[idx]),
                        "volume_ratio": round(float(day_volume_ratio), 2),
                        "rsi": round(float(rsi_day), 2),
                        "close": round(float(price_day), 2),
                        "ema21": round(float(curr_ema21), 2),
                        "ema50": round(float(curr_ema50), 2),
                    }

        # require crossover to be recent (configurable) using TRADING BARS,
        # not calendar days (Friday -> Monday is one bar, not three days)
        from config import CROSSOVER_RECENCY_BARS
        if bullish_crossover_rule is not None:
            try:
                buy_rule_passed = (len(df) - 1 - bullish_crossover_rule["bar_index"]) <= CROSSOVER_RECENCY_BARS
            except Exception:
                buy_rule_passed = True
        else:
            buy_rule_passed = False

        # ── Breakdown / dead-cat-bounce awareness ─────────────────────
        # Identical logic to screener.compute_indicators so the Analyze page
        # and the AI analyst see the same bull-trap context as the screener.
        recent_breakdown_day = False
        breakdown_info = {}
        gap_pct_now = ((open_price - prev) / prev) * 100 if prev else 0.0
        pct_ser = close.pct_change() * 100.0
        vol_base = vol.rolling(20, min_periods=10).median()
        vol_ratio_ser = (vol / vol_base.replace(0, np.nan)).fillna(0).clip(upper=MAX_VOLUME_RATIO)
        lookback = min(int(BREAKDOWN_LOOKBACK_BARS), max(len(df) - 2, 0))
        for k in range(1, lookback + 1):
            i = len(df) - 1 - k
            if i <= 1:
                continue
            if (pct_ser.iloc[i] <= CRASH_DAY_PCT and vol_ratio_ser.iloc[i] >= CRASH_DAY_VOL_MULT):
                recent_breakdown_day = True
                pre_win = high.iloc[max(0, i - 5):i]
                breakdown_info = {
                    "date": df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i]),
                    "change_pct": round(float(pct_ser.iloc[i]), 2),
                    "volume_ratio": round(float(vol_ratio_ser.iloc[i]), 2),
                    "reclaim_level": round(float(pre_win.max()) if len(pre_win) else float(high.iloc[i]), 2),
                }
                break
        reclaim_needed = breakdown_info.get("reclaim_level") if recent_breakdown_day else None
        reclaims_breakdown_level = bool(reclaim_needed and current >= reclaim_needed)
        bounce_after_breakdown = bool(recent_breakdown_day and change_pct > 0)

        # ── Recent high-volume reversal guard (SUNPHARMA 2026-09-01) ──
        # Mirrors screener.compute_indicators: a distribution candle within
        # REVERSAL_LOOKBACK_BARS (that has not been reclaimed) warns that the
        # latest "positive day" may be a low-volume bounce into overhead supply.
        from config import REVERSAL_LOOKBACK_BARS, REVERSAL_DAY_PCT, REVERSAL_DAY_VOL_MULT
        recent_reversal_day = False
        reversal_info = {}
        rev_lookback = min(int(REVERSAL_LOOKBACK_BARS), max(len(df) - 3, 0))
        for k_r in range(1, rev_lookback + 1):
            i_r = len(df) - 1 - k_r
            if i_r <= 1:
                continue
            if (pct_ser.iloc[i_r] <= REVERSAL_DAY_PCT
                    and vol_ratio_ser.iloc[i_r] >= REVERSAL_DAY_VOL_MULT):
                pre_r_win = high.iloc[max(0, i_r - 5):i_r]
                reversal_info = {
                    "date": df.index[i_r].strftime("%Y-%m-%d") if hasattr(df.index[i_r], "strftime") else str(df.index[i_r]),
                    "change_pct": round(float(pct_ser.iloc[i_r]), 2),
                    "volume_ratio": round(float(vol_ratio_ser.iloc[i_r]), 2),
                    "reclaim_level": round(float(pre_r_win.max()) if len(pre_r_win) else float(high.iloc[i_r]), 2),
                }
                recent_reversal_day = True
                break
        reclaims_reversal_level = bool(
            reversal_info.get("reclaim_level")
            and current >= reversal_info["reclaim_level"]
        ) if recent_reversal_day else None
        fresh_macd = False
        hist_vals = macd_hist.values
        for k2 in range(1, min(FRESH_TRIGGER_BARS + 1, len(hist_vals) - 1)):
            j = len(hist_vals) - 1 - k2
            if j <= 0:
                break
            if hist_vals[j] > 0 and hist_vals[j - 1] <= 0:
                fresh_macd = True
                break
        fresh_bullish_trigger = bool(fresh_macd or buy_rule_passed)
        bounce_win_pct, bounce_samples = bounce_after_breakdown_stats(close, high, vol)
        day_range = max(float(high.iloc[-1]) - float(low.iloc[-1]), 1e-9)
        close_location = float((current - low.iloc[-1]) / day_range)

        # ── Persistent unresolved-breakdown guard ─────────────────────
        # Unlike `recent_breakdown_day` (2-bar expiry), this stays TRUE until
        # the price reclaims the broken swing high, so a crash stock cannot be
        # re-offered as BUY while below the broken level (HINDCOPPER 8/24 crash,
        # never reclaimed 586.75).
        unresolved_breakdown, unresolved_info = find_unresolved_breakdown(
            close, high, vol, index=df.index,
            lookback=BREAKDOWN_RESOLUTION_LOOKBACK)

        if bearish_crossover_rule is not None:
            try:
                sell_rule_passed = (len(df) - 1 - bearish_crossover_rule["bar_index"]) <= CROSSOVER_RECENCY_BARS
            except Exception:
                sell_rule_passed = True
        else:
            sell_rule_passed = False
        buy_rule_reason = (
            f"EMA21/50 bullish crossover confirmed on {bullish_crossover_rule['date']} with "
            f"{bullish_crossover_rule['volume_ratio']}x volume and RSI {bullish_crossover_rule['rsi']}"
            if bullish_crossover_rule else
            "No recent EMA21/50 bullish crossover met the volume/RSI/price confirmation"
        )
        sell_rule_reason = (
            f"EMA21/50 bearish crossover confirmed on {bearish_crossover_rule['date']} with "
            f"{bearish_crossover_rule['volume_ratio']}x volume and RSI {bearish_crossover_rule['rsi']}"
            if bearish_crossover_rule else
            "No recent EMA21/50 bearish crossover met the volume/RSI/price confirmation"
        )

        # Pivot Points
        pivot = (high.iloc[-1] + low.iloc[-1] + close.iloc[-1]) / 3
        r1    = 2 * pivot - low.iloc[-1]
        s1    = 2 * pivot - high.iloc[-1]
        r2    = pivot + (high.iloc[-1] - low.iloc[-1])
        s2    = pivot - (high.iloc[-1] - low.iloc[-1])

        # 52W — only meaningful with >= 252 trading sessions
        n_52w = min(252, len(high))
        high_52w      = high.iloc[-n_52w:].max()
        low_52w       = low.iloc[-n_52w:].min()
        pct_from_high = ((current - high_52w) / high_52w) * 100

        # Candlestick patterns
        body         = abs(close.iloc[-1] - open_.iloc[-1])
        candle_range = high.iloc[-1] - low.iloc[-1]
        is_doji      = body < (candle_range * 0.1)
        is_hammer    = (
            (low.iloc[-1] < min(open_.iloc[-1], close.iloc[-1]) - 2 * body)
            and (high.iloc[-1] - max(open_.iloc[-1], close.iloc[-1]) < body)
        )
        is_bullish_engulf = (
            (close.iloc[-1] > open_.iloc[-2])
            and (open_.iloc[-1] < close.iloc[-2])
            and (close.iloc[-1] > open_.iloc[-1])
        )
        candle_pattern = (
            "doji"              if is_doji else
            "hammer"            if is_hammer else
            "bullish_engulfing" if is_bullish_engulf else
            "none"
        )

        # Overall signal score
        bull_signals = sum([
            rsi.iloc[-1] < 65,
            macd_hist.iloc[-1] > 0,
            ema9.iloc[-1] > ema21.iloc[-1],
            current > ema50.iloc[-1],
            vol_ratio > 1.2,
            obv_trend == "rising",
            adx > 20,
        ])
        overall = (
            "bullish" if bull_signals >= 5 else
            "bearish" if bull_signals <= 2 else
            "neutral"
        )

        return {
            # Price
            "symbol":            self.symbol.replace(".NS", ""),
            "current_price":     round(current, 2),
            "open_price":        round(open_price, 2),
            "prev_close":        round(prev, 2),
            "change_pct":        round(change_pct, 2),
            "gap_pct":           round(gap_pct, 2),
            "high_today":        round(high.iloc[-1], 2),
            "low_today":         round(low.iloc[-1], 2),
            # RSI
            "rsi":               round(rsi.iloc[-1], 2),
            "rsi_prev":          round(rsi.iloc[-2], 2),
            # MACD
            "macd":              round(macd_line.iloc[-1], 4),
            "macd_signal":       round(macd_sig.iloc[-1], 4),
            "macd_hist":         round(macd_hist.iloc[-1], 4),
            "macd_crossover":    macd_cross,
            # EMAs
            "ema9":              round(ema9.iloc[-1], 2),
            "ema21":             round(ema21.iloc[-1], 2),
            "ema50":             round(ema50.iloc[-1], 2),
            "ema200":            round(ema200.iloc[-1], 2),
            "sma20":             round(sma20.iloc[-1], 2),
            # Bollinger
            "bb_upper":          round(bb.bollinger_hband().iloc[-1], 2),
            "bb_lower":          round(bb.bollinger_lband().iloc[-1], 2),
            "bb_mid":            round(bb.bollinger_mavg().iloc[-1], 2),
            "bb_pct":            round(bb.bollinger_pband().iloc[-1], 4),
            "bb_squeeze_pct":    round(bb_squeeze, 2),
            # ATR
            "atr":               round(atr.iloc[-1], 2),
            "atr_pct":           round(atr_pct, 2),
            # Multi-timeframe
            "weekly_trend":      weekly_trend,
            "multi_tf_confirm":  multi_tf_confirm,
            # ADX
            "adx":               round(adx, 2),
            "adx_pos":           round(adx_pos, 2),
            "adx_neg":           round(adx_neg, 2),
            "trend_strength":    trend_strength,
            # Stochastic
            "stoch_k":           round(stoch_k, 2),
            "stoch_d":           round(stoch_d, 2),
            # Volume
            "volume":            int(vol.iloc[-1]),
            "avg_volume_20d":    int(avg_vol),
            "volume_ratio":      round(vol_ratio, 2),
            "obv_trend":         obv_trend,
            # EMA crossover rules
            "buy_rule_passed":   buy_rule_passed,
            "buy_rule_reason":   buy_rule_reason,
            "buy_rule_details":  bullish_crossover_rule or {},
            "sell_rule_passed":  sell_rule_passed,
            "sell_rule_reason":  sell_rule_reason,
            "sell_rule_details": bearish_crossover_rule or {},
            # Support / Resistance
            "pivot":             round(pivot, 2),
            "resistance_1":      round(r1, 2),
            "resistance_2":      round(r2, 2),
            "support_1":         round(s1, 2),
            "support_2":         round(s2, 2),
            # 52W
            "high_52w":          round(high_52w, 2),
            "low_52w":           round(low_52w, 2),
            "pct_from_52w_high": round(pct_from_high, 2),
            # Candle
            "candle_pattern":    candle_pattern,
            # Overall
            "overall_signal":    overall,
            "bull_signal_count": bull_signals,
            # ── Breakdown / dead-cat-bounce awareness ──────────────────
            "recent_breakdown_day":    recent_breakdown_day,
            "breakdown_date":          breakdown_info.get("date"),
            "breakdown_change_pct":    breakdown_info.get("change_pct"),
            "breakdown_volume_ratio":  breakdown_info.get("volume_ratio"),
            "breakdown_reclaim_level": reclaim_needed,
            "reclaims_breakdown_level": reclaims_breakdown_level,
            "bounce_after_breakdown":  bounce_after_breakdown,
            "fresh_bullish_trigger":   fresh_bullish_trigger,
            "bounce_win_pct":          bounce_win_pct,
            "bounce_samples":          bounce_samples,
            # ── Persistent unresolved-breakdown (until reclaim) ────────
            "unresolved_breakdown":        unresolved_breakdown,
            "unresolved_breakdown_date":   unresolved_info.get("date"),
            "unresolved_reclaim_level":    unresolved_info.get("reclaim_level"),
            # ── Recent high-volume reversal (SUNPHARMA 2026-09-01) ───────
            "recent_reversal_day":         recent_reversal_day,
            "reversal_date":               reversal_info.get("date"),
            "reversal_change_pct":         reversal_info.get("change_pct"),
            "reversal_volume_ratio":       reversal_info.get("volume_ratio"),
            "reversal_reclaim_level":      reversal_info.get("reclaim_level"),
            "reclaims_reversal_level":     reclaims_reversal_level,
            # ── Corporate-action data anomaly ──────────────────────────
            "data_anomaly":                self.data_anomaly,
            "gap_pct":                 round(gap_pct_now, 2),
            "close_location":          round(close_location, 3),
            # Raw OHLCV for AI prompt
            "ohlcv_30d": df[["Open","High","Low","Close","Volume"]].tail(30).to_dict()
        }


if __name__ == "__main__":
    engine = IndicatorEngine("RELIANCE.NS")
    if engine.fetch():
        data = engine.compute_all()
        for k, v in data.items():
            if k != "ohlcv_30d":
                print(f"  {k:<22}: {v}")