"""
scoring.py — Modular scoring functions extracted from screener logic
Provides: technical_score(indicators, style), buffett_score, rakesh_score wrappers,
and ensemble_score to combine them.
"""
from typing import Tuple, List, Dict
import strategies


def technical_score(ind: Dict, style: str) -> Tuple[int, List[str]]:
    score = 0
    signals = []

    try:
        if ind.get("ema9") and ind.get("ema21") and ind.get("ema50"):
            if ind["ema9"] > ind["ema21"] > ind["ema50"]:
                score += 20
                signals.append("Strong uptrend: EMA9 > EMA21 > EMA50")
            elif ind["ema9"] > ind["ema21"]:
                score += 12
                signals.append("Short-term bullish: EMA9 > EMA21")

        if ind.get("macd_hist", 0) > 0:
            score += 12
            signals.append("MACD histogram positive")

        if ind.get("current_price") and ind.get("ema21") and ind["current_price"] > ind["ema21"]:
            score += 8
            signals.append("Price above EMA21")

        if ind.get("buy_rule_passed"):
            score += 25
            date_label = ind.get("buy_rule_details", {}).get("date", "recent crossover")
            signals.append(f"EMA21/50 bullish crossover confirmed on {date_label}")

        if ind.get("sell_rule_passed"):
            score = max(score - 25, 0)
            date_label = ind.get("sell_rule_details", {}).get("date", "recent crossover")
            signals.append(f"EMA21/50 bearish crossover confirmed on {date_label}")

        rsi = ind.get("rsi")
        if rsi is not None:
            if 45 <= rsi <= 60:
                score += 15
                signals.append(f"RSI in sweet spot ({rsi})")
            elif 35 <= rsi < 45:
                score += 10
                signals.append(f"RSI recovering ({rsi})")
            elif 60 < rsi <= 70:
                score += 8
                signals.append(f"RSI strong momentum ({rsi})")

        if ind.get("price_change_pct", 0) > 0:
            score += 10
            signals.append(f"Positive day: +{ind.get('price_change_pct')}%")

        vol_ratio = ind.get("volume_ratio", 0)
        if vol_ratio >= 2.0:
            score += 20
            signals.append(f"Volume surge: {vol_ratio}x average")
        elif vol_ratio >= 1.5:
            score += 14
            signals.append(f"Above avg volume: {vol_ratio}x")
        elif vol_ratio >= 1.0:
            score += 7
            signals.append(f"Normal volume: {vol_ratio}x")

        bb_pct = ind.get("bb_pct")
        if bb_pct is not None:
            if 0.2 <= bb_pct <= 0.5:
                score += 15
                signals.append("Price in lower-mid Bollinger zone")
            elif bb_pct < 0.2:
                score += 10
                signals.append("Near lower Bollinger Band")

        if style == "intraday" and ind.get("atr_pct", 0) >= 1.5:
            score += 5
            signals.append(f"High intraday volatility (ATR {ind.get('atr_pct')}%)")
        if style == "positional" and ind.get("pct_from_52w_high", -999) > -20:
            score += 5
            signals.append("Near 52-week high")

    except Exception:
        # keep function robust — return partial score and any signals so far
        pass

    return min(int(round(score)), 100), signals


def buffett_score(ind: Dict, fundamentals: Dict) -> Tuple[int, List[str]]:
    # wrapper around existing strategies.score_buffett to keep API consistent
    try:
        s, reasons = strategies.score_buffett(ind, fundamentals)
        return s, reasons
    except Exception:
        return 0, []


def rakesh_score(ind: Dict, fundamentals: Dict) -> Tuple[int, List[str]]:
    try:
        s, reasons = strategies.score_rakesh(ind, fundamentals)
        return s, reasons
    except Exception:
        return 0, []


def ensemble_score(tech_score: int, buff_score: int, rakesh_score_v: int,
                   weights=(0.6, 0.2, 0.2)) -> int:
    t, b, r = weights
    try:
        ensemble = int(round(tech_score * t + buff_score * b + rakesh_score_v * r))
        return max(0, min(ensemble, 100))
    except Exception:
        return int(round(tech_score))
