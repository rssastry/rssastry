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
warnings.filterwarnings("ignore")


class IndicatorEngine:

    def __init__(self, symbol: str, period: str = "60d"):
        self.symbol = symbol
        self.period = period
        self.df = None

    def fetch(self) -> bool:
        try:
            ticker = yf.Ticker(self.symbol)
            self.df = ticker.history(period=self.period, interval="1d")
            self.df.dropna(inplace=True)
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
                        "date": df.index[idx].strftime("%Y-%m-%d") if hasattr(df.index[idx], "strftime") else str(df.index[idx]),
                        "volume_ratio": round(float(day_volume_ratio), 2),
                        "rsi": round(float(rsi_day), 2),
                        "close": round(float(price_day), 2),
                        "ema21": round(float(curr_ema21), 2),
                        "ema50": round(float(curr_ema50), 2),
                    }

        buy_rule_passed = bullish_crossover_rule is not None
        sell_rule_passed = bearish_crossover_rule is not None
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

        # 52W
        high_52w      = high.iloc[-min(252, len(high)):].max()
        low_52w       = low.iloc[-min(252, len(low)):].min()
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