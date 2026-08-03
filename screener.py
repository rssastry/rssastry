"""
screener.py — NSE/BSE Stock Screener
Filters ~2000 stocks down to 50-80 high-potential candidates
Supports: Intraday / Swing / Positional trading styles
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator
from ta.volatility import BollingerBands, AverageTrueRange
import warnings
import json
import os

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# NSE Stock Universe (Top 200 liquid stocks)
# ─────────────────────────────────────────────
NSE_STOCKS = [
    # NIFTY 50
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "BHARTIARTL.NS",
    "ICICIBANK.NS", "KOTAKBANK.NS", "SBIN.NS", "HINDUNILVR.NS", "ITC.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS",
    "BAJFINANCE.NS", "WIPRO.NS", "HCLTECH.NS", "ULTRACEMCO.NS", "NESTLEIND.NS",
    "POWERGRID.NS", "NTPC.NS", "SUNPHARMA.NS", "TATAMOTORS.NS", "ADANIENT.NS",
    "ADANIPORTS.NS", "COALINDIA.NS", "ONGC.NS", "JSWSTEEL.NS", "TATASTEEL.NS",
    "TECHM.NS", "INDUSINDBK.NS", "BAJAJFINSV.NS", "GRASIM.NS", "HINDALCO.NS",
    "CIPLA.NS", "DRREDDY.NS", "BRITANNIA.NS", "EICHERMOT.NS", "BPCL.NS",
    "TATACONSUM.NS", "APOLLOHOSP.NS", "DIVISLAB.NS", "HEROMOTOCO.NS", "SBILIFE.NS",
    "HDFCLIFE.NS", "BAJAJ-AUTO.NS", "SHRIRAMFIN.NS", "M&M.NS", "LTIM.NS",

    # NIFTY NEXT 50 / MidCap
    "ADANIGREEN.NS", "ADANITRANS.NS", "AMBUJACEM.NS", "AUROPHARMA.NS", "BANDHANBNK.NS",
    "BERGEPAINT.NS", "BIOCON.NS", "BOSCHLTD.NS", "CHOLAFIN.NS", "COLPAL.NS",
    "CUMMINSIND.NS", "DABUR.NS", "DLF.NS", "ESCORTS.NS", "FEDERALBNK.NS",
    "GAIL.NS", "GODREJCP.NS", "GODREJPROP.NS", "HAVELLS.NS", "HINDPETRO.NS",
    "IDFCFIRSTB.NS", "IGL.NS", "INDHOTEL.NS",
    "INDUSTOWER.NS", "IRCTC.NS", "JUBLFOOD.NS", "LICI.NS", "LUPIN.NS",
    "MARICO.NS", "MOTHERSON.NS", "MPHASIS.NS", "MRF.NS", "MUTHOOTFIN.NS",
    "NAUKRI.NS", "NMDC.NS", "OBEROIRLTY.NS", "OFSS.NS", "PAGEIND.NS",
    "PERSISTENT.NS", "PETRONET.NS", "PIDILITIND.NS", "PIIND.NS", "PNB.NS",
    "POLYCAB.NS", "SAIL.NS", "SIEMENS.NS", "SRF.NS", "TORNTPHARM.NS",
    "TRENT.NS", "TVSMOTOR.NS", "UPL.NS",
    "VEDL.NS", "VOLTAS.NS", "ZOMATO.NS", "NYKAA.NS",

    # Additional liquid mid-caps
    "ABCAPITAL.NS", "ALKEM.NS", "ASTRAL.NS",
    "AUBANK.NS", "BALKRISIND.NS", "BATAINDIA.NS", "BHEL.NS",
    "CANFINHOME.NS", "CONCOR.NS", "CROMPTON.NS",
    "DEEPAKNTR.NS", "GLENMARK.NS", "GRANULES.NS",
    "HAPPSTMNDS.NS", "HINDCOPPER.NS", "IDBI.NS",
    "INDIAMART.NS", "INDIGO.NS", "IOC.NS",
    "JKCEMENT.NS", "JSWENERGY.NS", "KAJARIACER.NS",
    "LAURUSLABS.NS", "LICHSGFIN.NS", "LTTS.NS", "MANAPPURAM.NS",
    "MCX.NS", "METROPOLIS.NS", "NATCOPHARM.NS", "NAVINFLUOR.NS",
    "NBCC.NS", "NLCINDIA.NS", "OLECTRA.NS",
    "PVRINOX.NS", "RAMCOCEM.NS", "RATNAMANI.NS",
    "MPHASIS.NS", "NUVOCO.NS", "RAIN.NS",
]

# ─────────────────────────────────────────────
# Screening Criteria by Trading Style
# ─────────────────────────────────────────────
SCREEN_CRITERIA = {
    "intraday": {
        "min_price": 50, "max_price": 10000,
        "min_volume": 1000000,
        "rsi_min": 40, "rsi_max": 65,
        "max_price_change_pct": 5,
        "min_atr_pct": 0.8,
    },
    "swing": {
        "min_price": 100, "max_price": 8000,
        "min_volume": 500000,
        "rsi_min": 35, "rsi_max": 65,
        "max_price_change_pct": 8,
        "min_atr_pct": 0.5,
    },
    "positional": {
        "min_price": 50, "max_price": 15000,
        "min_volume": 200000,
        "rsi_min": 30, "rsi_max": 60,
        "max_price_change_pct": 10,
        "min_atr_pct": 0.3,
    }
}


class StockScreener:

    def __init__(self):
        self.results = []
        self.scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch_stock_data(self, symbol: str, period: str = "60d"):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval="1d")
            if df.empty or len(df) < 20:
                return None
            df.dropna(inplace=True)
            return df
        except Exception:
            return None

    def compute_indicators(self, df) -> dict:
        close = df["Close"]
        high  = df["High"]
        low   = df["Low"]
        vol   = df["Volume"]

        rsi       = RSIIndicator(close, window=14).rsi().iloc[-1]
        macd_obj  = MACD(close)
        macd_hist = macd_obj.macd_diff().iloc[-1]
        ema9      = EMAIndicator(close, window=9).ema_indicator().iloc[-1]
        ema21     = EMAIndicator(close, window=21).ema_indicator().iloc[-1]
        ema50     = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
        bb        = BollingerBands(close, window=20, window_dev=2)
        bb_pct    = bb.bollinger_pband().iloc[-1]
        atr       = AverageTrueRange(high, low, close, window=14).average_true_range().iloc[-1]
        current   = close.iloc[-1]
        atr_pct   = (atr / current) * 100
        avg_vol   = vol.iloc[-20:].mean()
        vol_ratio = vol.iloc[-1] / avg_vol if avg_vol > 0 else 0
        prev_close= close.iloc[-2]
        price_change_pct = ((current - prev_close) / prev_close) * 100
        high_52w  = high.iloc[-252:].max() if len(high) >= 252 else high.max()

        ema21_series = EMAIndicator(close, window=21).ema_indicator()
        ema50_series = EMAIndicator(close, window=50).ema_indicator()
        rsi_series = RSIIndicator(close, window=14).rsi()
        bullish_crossover_rule = None
        bearish_crossover_rule = None
        for idx in range(1, len(df)):
            prev_ema21 = ema21_series.iloc[idx - 1]
            prev_ema50 = ema50_series.iloc[idx - 1]
            curr_ema21 = ema21_series.iloc[idx]
            curr_ema50 = ema50_series.iloc[idx]

            if prev_ema21 <= prev_ema50 and curr_ema21 > curr_ema50:
                vol_window = vol.iloc[max(0, idx - 20):idx]
                avg_vol_day = vol_window.mean() if len(vol_window) > 0 else 0
                day_volume_ratio = vol.iloc[idx] / avg_vol_day if avg_vol_day > 0 else 0
                rsi_day = rsi_series.iloc[idx]
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
                rsi_day = rsi_series.iloc[idx]
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
        low_52w   = low.iloc[-252:].min()  if len(low)  >= 252 else low.min()
        pct_from_52w_high = ((current - high_52w) / high_52w) * 100

        return {
            "current_price":      round(current, 2),
            "prev_close":         round(prev_close, 2),
            "price_change_pct":   round(price_change_pct, 2),
            "rsi":                round(rsi, 2),
            "macd_hist":          round(macd_hist, 4),
            "ema9":               round(ema9, 2),
            "ema21":              round(ema21, 2),
            "ema50":              round(ema50, 2),
            "bb_upper":           round(bb.bollinger_hband().iloc[-1], 2),
            "bb_lower":           round(bb.bollinger_lband().iloc[-1], 2),
            "bb_mid":             round(bb.bollinger_mavg().iloc[-1], 2),
            "bb_pct":             round(bb_pct, 4),
            "atr":                round(atr, 2),
            "atr_pct":            round(atr_pct, 2),
            "volume":             int(vol.iloc[-1]),
            "avg_volume_20d":     int(avg_vol),
            "volume_ratio":       round(vol_ratio, 2),
            "high_52w":           round(high_52w, 2),
            "low_52w":            round(low_52w, 2),
            "pct_from_52w_high":  round(pct_from_52w_high, 2),
            "support":            round(low.iloc[-10:].min(), 2),
            "resistance":         round(high.iloc[-10:].max(), 2),
            "buy_rule_passed":    buy_rule_passed,
            "buy_rule_details":   bullish_crossover_rule or {},
            "sell_rule_passed":   sell_rule_passed,
            "sell_rule_details":  bearish_crossover_rule or {},
        }

    def score_stock(self, ind: dict, style: str):
        score   = 0
        signals = []

        if ind["ema9"] > ind["ema21"] > ind["ema50"]:
            score += 20
            signals.append("Strong uptrend: EMA9 > EMA21 > EMA50")
        elif ind["ema9"] > ind["ema21"]:
            score += 12
            signals.append("Short-term bullish: EMA9 > EMA21")

        if ind["macd_hist"] > 0:
            score += 12
            signals.append("MACD histogram positive")

        if ind["current_price"] > ind["ema21"]:
            score += 8
            signals.append("Price above EMA21")

        if ind.get("buy_rule_passed", False):
            score += 25
            details = ind.get("buy_rule_details", {})
            date_label = details.get("date", "recent crossover")
            signals.append(f"EMA21/50 bullish crossover confirmed on {date_label}")

        if ind.get("sell_rule_passed", False):
            score = max(score - 25, 0)
            details = ind.get("sell_rule_details", {})
            date_label = details.get("date", "recent crossover")
            signals.append(f"EMA21/50 bearish crossover confirmed on {date_label}")

        rsi = ind["rsi"]
        if 45 <= rsi <= 60:
            score += 15
            signals.append(f"RSI in sweet spot ({rsi})")
        elif 35 <= rsi < 45:
            score += 10
            signals.append(f"RSI recovering ({rsi})")
        elif 60 < rsi <= 70:
            score += 8
            signals.append(f"RSI strong momentum ({rsi})")

        if ind["price_change_pct"] > 0:
            score += 10
            signals.append(f"Positive day: +{ind['price_change_pct']}%")

        if ind["volume_ratio"] >= 2.0:
            score += 20
            signals.append(f"Volume surge: {ind['volume_ratio']}x average")
        elif ind["volume_ratio"] >= 1.5:
            score += 14
            signals.append(f"Above avg volume: {ind['volume_ratio']}x")
        elif ind["volume_ratio"] >= 1.0:
            score += 7
            signals.append(f"Normal volume: {ind['volume_ratio']}x")

        if 0.2 <= ind["bb_pct"] <= 0.5:
            score += 15
            signals.append("Price in lower-mid Bollinger zone")
        elif ind["bb_pct"] < 0.2:
            score += 10
            signals.append("Near lower Bollinger Band")

        if style == "intraday" and ind["atr_pct"] >= 1.5:
            score += 5
            signals.append(f"High intraday volatility (ATR {ind['atr_pct']}%)")
        if style == "positional" and ind["pct_from_52w_high"] > -20:
            score += 5
            signals.append("Near 52-week high")

        return min(score, 100), signals

    def passes_filter(self, ind: dict, style: str) -> bool:
        c = SCREEN_CRITERIA[style]
        p = ind["current_price"]
        return (
            c["min_price"] <= p <= c["max_price"]
            and ind["avg_volume_20d"] >= c["min_volume"]
            and c["rsi_min"] <= ind["rsi"] <= c["rsi_max"]
            and abs(ind["price_change_pct"]) <= c["max_price_change_pct"]
            and ind["atr_pct"] >= c["min_atr_pct"]
            and ind["pct_from_52w_high"] >= -45
        )

    def screen(self, styles=["intraday","swing","positional"], top_n=10) -> dict:
        print(f"\n{'='*55}")
        print(f"  NSE/BSE Stock Screener — {self.scan_time}")
        print(f"  Scanning {len(NSE_STOCKS)} stocks...")
        print(f"{'='*55}\n")

        all_results = {style: [] for style in styles}
        total = len(NSE_STOCKS)

        for i, symbol in enumerate(NSE_STOCKS, 1):
            print(f"  [{i:>3}/{total}] Scanning {symbol:<22}", end="\r")
            df = self.fetch_stock_data(symbol)
            if df is None:
                continue
            try:
                ind = self.compute_indicators(df)
            except Exception:
                continue

            for style in styles:
                if self.passes_filter(ind, style):
                    score, signals = self.score_stock(ind, style)
                    if score >= 30:
                        all_results[style].append({
                            "symbol":    symbol.replace(".NS", ""),
                            "yf_symbol": symbol,
                            "style":     style,
                            "score":     score,
                            "signals":   signals,
                            **ind
                        })

        final = {}
        for style in styles:
            sorted_stocks = sorted(all_results[style],
                                   key=lambda x: x["score"], reverse=True)
            final[style] = sorted_stocks[:top_n]

        self._print_results(final)
        self._save_results(final)
        return final

    def _print_results(self, results: dict):
        for style, stocks in results.items():
            print(f"\n{'─'*55}")
            print(f"  TOP {len(stocks)} — {style.upper()} PICKS")
            print(f"{'─'*55}")
            if not stocks:
                print("  No stocks passed the filter today.")
                continue
            print(f"  {'#':<3} {'Symbol':<14} {'Price':>8} {'RSI':>6} {'Vol Ratio':>10} {'Score':>7}")
            print(f"  {'─'*52}")
            for i, s in enumerate(stocks, 1):
                print(f"  {i:<3} {s['symbol']:<14} "
                      f"Rs.{s['current_price']:>7.2f} "
                      f"{s['rsi']:>6.1f} "
                      f"{s['volume_ratio']:>9.1f}x "
                      f"{s['score']:>6}/100")
        print(f"\n  Scan complete. Results saved to screener_results.json\n")

    def _save_results(self, results: dict):
        output = {"scan_time": self.scan_time, "results": results}
        with open("screener_results.json", "w") as f:
            json.dump(output, f, indent=2, default=str)


if __name__ == "__main__":
    screener = StockScreener()
    screener.screen(styles=["intraday","swing","positional"], top_n=10)