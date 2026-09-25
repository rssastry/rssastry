"""
screener.py — NSE/BSE Stock Screener
Filters ~2000 stocks down to 50-80 high-potential candidates
Supports: Intraday / Swing / Positional trading styles
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange
import warnings
import json
import os
from collections import Counter
import strategies
import paths
from fundamental_snapshots import resolve_provider_ticker, merge_fundamental_snapshots

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
    "HDFCLIFE.NS", "BAJAJ-AUTO.NS", "SHRIRAMFIN.NS", "M&M.NS",

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
    "NUVOCO.NS", "RAIN.NS",

    # NIFTY MIDCAP 100 constituents not already above (~50-symbol expansion,
    # 2026-09-09 NSE index components) — broadens the candidate pool and the
    # fundamental validation sample with liquid, well-covered names.
    "360ONE.NS", "APLAPOLLO.NS", "ASHOKLEY.NS", "ATGL.NS",
    "BANKINDIA.NS", "BDL.NS", "BHARATFORG.NS", "BLUESTARCO.NS",
    "BSE.NS", "COCHINSHIP.NS", "COFORGE.NS", "COROMANDEL.NS",
    "DIXON.NS", "EXIDEIND.NS", "FORTIS.NS", "GMRAIRPORT.NS",
    "GODFRYPHLP.NS", "GROWW.NS", "GVT&D.NS", "HUDCO.NS",
    "ICICIAMC.NS", "ICICIGI.NS", "IDEA.NS", "INDIANB.NS",
    "IREDA.NS", "KALYANKJIL.NS", "KEI.NS", "KPITTECH.NS",
    "LENSKART.NS", "LGEINDIA.NS", "LTF.NS", "M&MFIN.NS",
    "MANKIND.NS", "MFSL.NS", "MOTILALOFS.NS", "NATIONALUM.NS",
    "NHPC.NS", "OIL.NS", "PATANJALI.NS", "PAYTM.NS",
    "PHOENIXLTD.NS", "POLICYBZR.NS", "POWERINDIA.NS", "PREMIERENE.NS",
    "PRESTIGE.NS", "RADICO.NS", "RVNL.NS", "SBICARD.NS",
    "SUPREMEIND.NS", "SUZLON.NS", "SWIGGY.NS", "TATACOMM.NS",
    "TATAELXSI.NS", "TATAINVEST.NS", "TIINDIA.NS", "VMM.NS",
    "WAAREEENER.NS", "YESBANK.NS",
]

# Deduplicate while preserving order
NSE_STOCKS = list(dict.fromkeys(NSE_STOCKS))

# config
from config import (CROSSOVER_RECENCY_BARS, MAX_VOLUME_RATIO, MIN_DAILY_HISTORY,
                    BREAKDOWN_LOOKBACK_BARS, CRASH_DAY_PCT, CRASH_DAY_VOL_MULT,
                    FRESH_TRIGGER_BARS, BOUNCE_HIST_MIN_SAMPLES,
                    ATR_MULT, BUY_MIN_ENSEMBLE,
                    MAX_STOP_DISTANCE_PCT_BY_STYLE, BREAKDOWN_RESOLUTION_LOOKBACK,
                    VOLUME_CONFIRMATION_MARGIN, REVERSAL_LOOKBACK_BARS,
                    REVERSAL_DAY_PCT, REVERSAL_DAY_VOL_MULT,
                    MARKET_REGIME_FAIL_CLOSED, MIN_TECHNICAL_SCORE_FOR_BUY,
                    MIN_FUNDAMENTAL_DATA_POINTS_FOR_BUY,
                    MIN_FUNDAMENTAL_QUALITY_FOR_BUY,
                    MAX_FUNDAMENTAL_DEBT_TO_EQUITY, MAX_FUNDAMENTAL_PE,
                    ADX_MIN_FOR_BUY, ADX_STRONG_FOR_NO_TRIGGER,
                    VOLUME_CONFIRMATION_MARGIN_BY_STYLE,
                    ALLOW_DAILY_BAR_INTRADAY_BUY,
                    REQUIRE_COMPLETED_DAILY_BAR_FOR_BUY,
                    ENABLE_PILOT_BUYS, PILOT_POSITION_SCALE,
                    PILOT_RS_LOOKBACK_BARS, PILOT_MIN_RS_VS_NIFTY,
                    PILOT_BREAKOUT_VOLUME_RATIO, PILOT_MIN_EPS_GROWTH,
                    PILOT_MIN_20D_TRADED_VALUE,
                    ALLOW_BREAKOUT_TRIGGER, BREAKOUT_TRIGGER_VOL_RATIO,
                    BREAKOUT_TRIGGER_LOOKBACK_BARS)
from indicators import find_unresolved_breakdown

# ─────────────────────────────────────────────
# Screening Criteria by Trading Style
# Per-share price is not an affordability or quality measure. Position sizing
# and maximum loss determine affordability.
# ─────────────────────────────────────────────
SMALL_INVESTOR_MAX_PRICE = float("inf")

SCREEN_CRITERIA = {
    "short_term": {
        "min_price": 20, "max_price": SMALL_INVESTOR_MAX_PRICE,
        "min_volume": 1000000,
        "rsi_min": 40, "rsi_max": 65,
        "max_price_change_pct": 5,
        "min_atr_pct": 0.8,
        "min_volume_ratio": 1.2,
    },
    # "intraday" is an alias for "short_term" (1-3 day swing using daily bars)
    "intraday": {
        "min_price": 20, "max_price": SMALL_INVESTOR_MAX_PRICE,
        "min_volume": 1000000,
        "rsi_min": 40, "rsi_max": 65,
        "max_price_change_pct": 5,
        "min_atr_pct": 0.8,
        "min_volume_ratio": 1.2,
    },
    "swing": {
        "min_price": 20, "max_price": SMALL_INVESTOR_MAX_PRICE,
        "min_volume": 500000,
        "rsi_min": 35, "rsi_max": 65,
        "max_price_change_pct": 8,
        "min_atr_pct": 0.5,
        "min_volume_ratio": 1.0,
    },
    "positional": {
        "min_price": 20, "max_price": SMALL_INVESTOR_MAX_PRICE,
        "min_volume": 200000,
        "rsi_min": 30, "rsi_max": 60,
        "max_price_change_pct": 10,
        "min_atr_pct": 0.3,
        # Positional was 0.8x until SUNPHARMA 2026-09-02: a +0.14% bounce on
        # 0.8x volume bought under a fresh high-volume reversal was offered as
        # BUY and faded. Every style now needs at least average volume backed
        # up by the VOLUME_CONFIRMATION_MARGIN surplus check in the BUY gate.
        "min_volume_ratio": 1.0,
    }
}


def check_earnings_risk(symbol: str) -> dict:
    """Check if a symbol has an earnings announcement within the blackout window.

    Returns {"days_to_earnings": int|None, "earnings_date": str|None, "risk": bool}
    """
    from config import EARNINGS_BLACKOUT_DAYS
    try:
        ticker = yf.Ticker(resolve_provider_ticker(symbol))
        cal = ticker.calendar
        if cal is None or cal.empty:
            return {"days_to_earnings": None, "earnings_date": None, "risk": False}
        # yfinance calendar may be a DataFrame or dict
        earnings_date = None
        if isinstance(cal, dict):
            earnings_date = cal.get("Earnings Date")
        elif hasattr(cal, "get"):
            earnings_date = cal.get("Earnings Date")
        if earnings_date is None and hasattr(cal, "index"):
            try:
                if "Earnings Date" in cal.index:
                    earnings_date = cal.loc["Earnings Date"]
            except Exception:
                pass
        if earnings_date is None:
            return {"days_to_earnings": None, "earnings_date": None, "risk": False}
        # earnings_date may be a list of dates
        if isinstance(earnings_date, (list, tuple)) and len(earnings_date) > 0:
            earnings_date = earnings_date[0]
        if hasattr(earnings_date, "date"):
            earnings_date = earnings_date.date()
        from datetime import date
        if isinstance(earnings_date, date):
            days = (earnings_date - date.today()).days
            return {
                "days_to_earnings": days,
                "earnings_date": str(earnings_date),
                "risk": abs(days) <= EARNINGS_BLACKOUT_DAYS,
            }
        return {"days_to_earnings": None, "earnings_date": str(earnings_date), "risk": False}
    except Exception:
        return {"days_to_earnings": None, "earnings_date": None, "risk": False}


def check_market_regime() -> dict:
    """Check NIFTY 50 market regime using EMA50.

    Returns {"regime": "bullish"/"bearish"/"neutral", "nifty_price": float, "nifty_ema50": float}
    """
    try:
        from config import MARKET_REGIME_EMA
        ticker = yf.Ticker("^NSEI")
        df = ticker.history(period="1y", interval="1d")
        if df is None or df.empty or len(df) < MARKET_REGIME_EMA:
            return {"regime": "unknown", "nifty_price": None, "nifty_ema50": None}
        close = df["Close"]
        ema50 = EMAIndicator(close, window=MARKET_REGIME_EMA).ema_indicator().iloc[-1]
        price = close.iloc[-1]
        regime = "bullish" if price >= ema50 else "bearish"
        return {"regime": regime, "nifty_price": round(float(price), 2), "nifty_ema50": round(float(ema50), 2)}
    except Exception:
        return {"regime": "unknown", "nifty_price": None, "nifty_ema50": None}


def market_regime_blocks_buy(regime: str,
                             fail_closed: bool = MARKET_REGIME_FAIL_CLOSED) -> tuple[bool, str]:
    """Pure rule: should BUYs be suppressed for this regime?

    Bearish always blocks. Unknown blocks UNDER FAIL-CLOSED policy: if the NIFTY
    index data cannot confirm a supportive tape, the system must not issue fresh
    BUYs (the old code silently passed "unknown" through — SUNPHARMA was offered
    as BUY on 2026-09-02 while the regime read "unknown").

    Returns (block_buy, reason_to_record).
    """
    if regime == "bearish":
        return True, "Market regime filter: NIFTY below EMA50"
    if regime == "unknown":
        if fail_closed:
            return True, (
                "Market regime unknown (NIFTY data unavailable) — "
                "BUY suppressed under fail-closed policy"
            )
        return False, ""
    return False, ""


def fundamental_buy_gate(fundamentals: dict, quality_score: float,
                         sector: str = None) -> tuple[bool, list[str]]:
    """Require enough current fundamental evidence for an actionable BUY."""
    if not fundamentals:
        return False, ["Fundamental data unavailable — WATCHLIST only"]

    evidence_keys = (
        "returnOnEquity", "returnOnCapitalEmployed", "debtToEquity",
        "freeCashflow", "profitMargins", "operatingMargins", "trailingPE",
        "forwardPE", "priceToBook", "earningsGrowth",
        "earningsQuarterlyGrowth",
    )
    evidence = [key for key in evidence_keys if fundamentals.get(key) is not None]
    failures = []
    if len(evidence) < MIN_FUNDAMENTAL_DATA_POINTS_FOR_BUY:
        failures.append(
            f"Only {len(evidence)} fundamental data points available "
            f"({MIN_FUNDAMENTAL_DATA_POINTS_FOR_BUY} required) — WATCHLIST only"
        )
    if float(quality_score or 0) < MIN_FUNDAMENTAL_QUALITY_FOR_BUY:
        failures.append(
            f"Fundamental quality score {quality_score:.1f} below "
            f"{MIN_FUNDAMENTAL_QUALITY_FOR_BUY} — WATCHLIST only"
        )

    def numeric(*keys):
        for key in keys:
            value = fundamentals.get(key)
            if isinstance(value, (int, float)) and np.isfinite(value):
                return float(value)
        return None

    roe = numeric("returnOnEquity")
    roce = numeric("returnOnCapitalEmployed")
    margins = numeric("profitMargins", "operatingMargins")
    fcf = numeric("freeCashflow")
    debt = numeric("debtToEquity")
    pe = numeric("forwardPE", "trailingPE")

    # A senior review needs an actual engine of returns, not only technical
    # momentum and a blended score whose missing fields may be neutral.
    if not any(value is not None and value > 0 for value in (roe, roce, margins, fcf)):
        failures.append("No positive profitability or cash-flow evidence — WATCHLIST only")
    sector_thresholds = strategies.get_sector_thresholds(sector)
    max_debt = sector_thresholds.get("debt_max", MAX_FUNDAMENTAL_DEBT_TO_EQUITY)
    max_pe = sector_thresholds.get("pe_max", MAX_FUNDAMENTAL_PE)
    if debt is not None and debt > max_debt:
        failures.append(
            f"Debt-to-equity {debt:.2f} is too high "
            f"(> {max_debt:g} for {sector or 'unknown sector'}) — WATCHLIST only"
        )
    if pe is not None and pe > max_pe:
        failures.append(
            f"Forward/trailing P/E {pe:.1f} is excessive "
            f"(> {max_pe:g} for {sector or 'unknown sector'}) — WATCHLIST only"
        )
    return not failures, failures


def pilot_gate_eligible(failed_checks: list, anomaly: bool,
                        enabled: bool = ENABLE_PILOT_BUYS) -> bool:
    """Pilot path may run ONLY when the market-regime filter is the SOLE
    failure of an otherwise fully-qualified candidate."""
    return bool(enabled) and not anomaly and len(failed_checks) == 0


def _stock_return(close, lookback_bars: int = 21) -> float | None:
    """Simple trailing return over ``lookback_bars`` completed bars."""
    try:
        series = pd.Series(close).astype(float).dropna()
        if len(series) < lookback_bars + 1:
            return None
        return float(series.iloc[-1] / series.iloc[-(lookback_bars + 1)] - 1.0)
    except Exception:
        return None


def _nifty_return(lookback_bars: int = 21) -> float | None:
    """21-bar (≈1-month) return of the ^NSEI index; None when unavailable."""
    try:
        from data_cache import fetch_history
        df = fetch_history("^NSEI", period="1y", interval="1d")
        if df is None or getattr(df, "empty", True):
            return None
        return _stock_return(df["Close"], lookback_bars)
    except Exception:
        return None


def pilot_conditions_met(ind: dict, fundamentals: dict,
                         nifty_return: float | None, close=None,
                         high=None) -> tuple:
    """Stricter stock-level filters required to upgrade a candidate to a
    PILOT BUY while NIFTY is confirmed below its 50-day EMA.

    The candidate must already pass the ENTIRE normal buy gate — this only
    decides whether the sole ``market regime`` failure may be overridden.

    Returns (approved, failures, advisory_notes).
    """
    failures: list[str] = []
    notes: list[str] = []
    # The current provider does not supply a point-in-time earnings-surprise
    # history or sector-index return series, so do not imply those overlays pass.
    notes.append("Earnings-surprise and sector-tailwind data not evaluated")
    price = float(ind.get("current_price", 0) or 0)

    # 1) The stock's OWN trend must be healthy (price above its 200d & 50d EMAs).
    ema50 = ind.get("ema50")
    ema200 = ind.get("ema200")
    if ema50 is None or ema200 is None:
        failures.append("50/200-day EMA unavailable for pilot check")
    else:
        if price <= float(ema50):
            failures.append("Price below its own 50-day EMA")
        if price <= float(ema200):
            failures.append("Price below its own 200-day EMA")
        else:
            notes.append("price above own 200d/50d EMAs")

    # 2) Price-relative strength vs NIFTY. This is an indexed-price ratio,
    # not a mathematically ambiguous "multiple of returns" in a falling market.
    stock_ret = _stock_return(close, PILOT_RS_LOOKBACK_BARS) if close is not None else None
    if stock_ret is None:
        failures.append("Relative strength data unavailable (insufficient price history)")
    elif nifty_return is None:
        failures.append("NIFTY benchmark data unavailable — relative strength cannot be computed")
    else:
        rs = (1.0 + float(stock_ret)) / (1.0 + float(nifty_return))
        if rs < PILOT_MIN_RS_VS_NIFTY:
            failures.append(
                f"Fails RS filter (≈{rs:.2f}x NIFTY < {PILOT_MIN_RS_VS_NIFTY:.2f}x required)"
            )
        else:
            notes.append(f"price RS vs NIFTY ≈{rs:.2f}x")

    # 3) High-volume breakout confirmation: volume ≥ 150% of the 20d average AND
    #    close above the PRIOR 10-session high (the resistance that existed at
    #    yesterday's close -- ind['resistance_1'] includes TODAY's bar, whose
    #    high is by definition >= close, so it can never confirm a breakout).
    if not ind.get("daily_bar_complete", False):
        failures.append(
            "Pilot requires a completed daily breakout bar; intraday volume is not confirmed"
        )
    traded_value = float(ind.get("median_traded_value_20d", 0) or 0)
    if traded_value < PILOT_MIN_20D_TRADED_VALUE:
        failures.append(
            f"Fails liquidity filter (20d median traded value ₹{traded_value:,.0f} < "
            f"₹{PILOT_MIN_20D_TRADED_VALUE:,.0f})"
        )
    eff_vol = float(ind.get("effective_vol_ratio", ind.get("volume_ratio", 0)) or 0)
    prior_breakout = False
    if high is not None:
        try:
            hs = pd.Series(high).astype(float).dropna()
            if len(hs) >= 11:
                prior_res = float(hs.iloc[-11:-1].max())
                prior_breakout = price > prior_res
        except Exception:
            prior_breakout = False
    if eff_vol >= PILOT_BREAKOUT_VOLUME_RATIO and prior_breakout:
        notes.append(f"high-volume breakout ({eff_vol:.2f}x prior-20-session average volume)")
    else:
        failures.append(
            f"Fails breakout-volume condition (volume {eff_vol:.2f}x < "
            f"{PILOT_BREAKOUT_VOLUME_RATIO:.2f}x of 20d avg and/or close not above "
            "the prior 10-session high)"
        )

    # 4) Fundamental overlay — require EPS growth when the provider reports it.
    growth = fundamentals.get("earningsGrowth")
    if growth is None:
        growth = fundamentals.get("earningsQuarterlyGrowth")
    if growth is not None:
        try:
            growth = float(growth)
            if growth < PILOT_MIN_EPS_GROWTH:
                failures.append(
                    f"EPS growth {growth*100:.1f}% below {PILOT_MIN_EPS_GROWTH*100:.0f}% floor"
                )
            else:
                notes.append(f"EPS growth {growth*100:.1f}%")
        except Exception:
            notes.append("EPS growth n/a (advisory)")
    else:
        notes.append("EPS growth n/a (advisory)")

    return not failures, failures, notes


def _historical_signal_win_rate(close: pd.Series, bb_pband_ser: pd.Series,
                                rsi_ser: pd.Series, min_samples: int = 20) -> tuple:
    """Empirical next-session win rate for the CURRENT stretched setup.

    The live signal often is: close ABOVE the upper Bollinger band (BB% > 1)
    with RSI in a trending-but-not-exhausted zone and a positive session.
    That pattern is a classic breakout-FADE on range-bound names. This
    measures how often such a bar is followed by an UP session.

    Returns (win_pct, n_samples); win_pct is None when n < min_samples.
    """
    try:
        if close is None or bb_pband_ser is None or rsi_ser is None:
            return None, 0
        s = pd.DataFrame({
            "close":  close,
            "bb":     bb_pband_ser,
            "rsi":    rsi_ser,
        }).dropna()
        # live-bar conditions (mirrors the KOTAK-style stretched setup)
        day_chg = s["close"].pct_change()
        setup = (
            (s["bb"] > 1.0)
            & (s["rsi"] >= 55) & (s["rsi"] <= 68)
            & (day_chg > 0.004)
        )
        nxt = s["close"].shift(-1) / s["close"] - 1
        sub = nxt[setup].dropna()
        n = int(len(sub))
        if n < min_samples:
            return None, n
        return round(100 * float((sub > 0).mean()), 1), n
    except Exception:
        return None, 0


def _bounce_after_breakdown_stats(close: pd.Series, high: pd.Series,
                                  vol: pd.Series, crash_pct: float,
                                  crash_vol_mult: float,
                                  min_samples: int = BOUNCE_HIST_MIN_SAMPLES):
    """Empirical continuation odds for the dead-cat-bounce setup.

    A "breakdown day" (daily move <= crash_pct with vol >= crash_vol_mult x the
    20-day median volume) followed by an UP session is a bounce. This returns the
    % of such bounces that CLOSE HIGHER on the next session (continuation). A low
    value means the bounce usually fades — the setup deserves WATCHLIST, not BUY.
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
            # down day found — require the next session to be an up bounce
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


def _risk_adjusted_expected_value(ind: dict, style: str) -> tuple[float, str | None]:
    """Return a rough expectancy estimate and a reason string for weak setups.

    We approximate expected value as:
      EV ≈ p_win * reward_to_risk - p_loss
    where reward_to_risk is style-specific and adjusted for ATR stop width.
    This is intentionally simple, but it is a useful guardrail for historical fade setups.
    """
    try:
        win = ind.get("sig_win_pct")
        samples = int(ind.get("sig_samples", 0) or 0)
        if win is None or samples < 20:
            return None, None

        price = float(ind.get("current_price", 0) or 0)
        atr = float(ind.get("atr", 0) or 0)
        if price <= 0 or atr <= 0:
            return None, None

        rr_map = {"intraday": 2.0, "short_term": 2.4, "swing": 3.0, "positional": 3.5}
        rr = float(rr_map.get(style, 3.0))
        stop_pct = float(ATR_MULT.get(style, 2.5)) * atr / price * 100.0
        p_win = max(0.0, min(float(win) / 100.0, 1.0))
        p_loss = 1.0 - p_win
        ev = (p_win * rr) - p_loss

        # A wider stop compresses expected value materially.
        if stop_pct > 6.0:
            ev -= (stop_pct - 6.0) * 0.03
        if ev < 0.15:
            return round(ev, 3), f"Expected value weak: win rate {win:.0f}% with ATR stop ~{stop_pct:.1f}%"
        if ev < 0.3:
            return round(ev, 3), f"Expected value marginal: win rate {win:.0f}% with ATR stop ~{stop_pct:.1f}%"
        return round(ev, 3), None
    except Exception:
        return None, None


def inherit_strict_style_failures(style_failures: dict, style: str) -> list:
    """Propagate structural failures from stricter styles to a looser style.

    Structural failures (trend alignment, momentum, breakdown/reversal context,
    fresh-trigger) are style-independent. Volume thresholds and the ATR
    stop-distance cap are intentionally style-specific and are NOT propagated.
    (SUNPHARMA 2026-09-02 was rejected intraday for volume but still offered as
    a positional BUY — inherited structural/context failures must force the
    looser style to WATCHLIST too.)

    Accepts a dict mapping style -> list of failure strings, e.g.
    {"intraday": [...]} and the target style "swing"/"positional".
    """
    stricter = {
        "swing": ["intraday", "short_term"],
        "positional": ["intraday", "short_term", "swing"],
    }.get(style, [])
    inherited = []
    for st in stricter:
        for f in style_failures.get(st, []):
            if ("ATR stop" in f or "Volume confirmation" in f
                    or "Intraday BUY requires intraday candles" in f
                    or f in inherited):
                continue
            inherited.append(f)
    return inherited


class StockScreener:

    def __init__(self):
        self.results = []
        self.scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch_stock_data(self, symbol: str, period: str = "2y"):
        try:
            # Use the SAME cached/downloaded pipeline as the analysis engine
            # (data_cache.fetch_history) so the screener and the AI analyst can
            # never disagree on price because one padded raw and the other
            # adjusted OHLCV (HINDCOPPER 2026-08-31: 1037.4 vs 525.3).
            try:
                from data_cache import fetch_history
                df = fetch_history(symbol, period=period, interval='1d')
            except Exception:
                ticker = yf.Ticker(resolve_provider_ticker(symbol))
                df = ticker.history(period=period, interval="1d")
            if df is None or getattr(df, 'empty', True) or len(df) < MIN_DAILY_HISTORY:
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
        macd_line = macd_obj.macd().iloc[-1]
        macd_sig  = macd_obj.macd_signal().iloc[-1]
        macd_hist_series = macd_obj.macd_diff()
        macd_hist = macd_hist_series.iloc[-1]
        macd_crossover = (
            "bullish" if macd_hist_series.iloc[-1] > 0 and macd_hist_series.iloc[-2] <= 0 else
            "bearish" if macd_hist_series.iloc[-1] < 0 and macd_hist_series.iloc[-2] >= 0 else
            "none"
        )
        ema9      = EMAIndicator(close, window=9).ema_indicator().iloc[-1]
        ema21     = EMAIndicator(close, window=21).ema_indicator().iloc[-1]
        ema50     = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
        ema200    = EMAIndicator(close, window=min(200, max(len(close) - 1, 3))).ema_indicator().iloc[-1]
        bb        = BollingerBands(close, window=20, window_dev=2)
        bb_pband_ser = bb.bollinger_pband()
        bb_pct    = bb_pband_ser.iloc[-1]
        atr       = AverageTrueRange(high, low, close, window=14).average_true_range().iloc[-1]
        current   = close.iloc[-1]
        atr_pct   = (atr / current) * 100
        # Signal-bar volume is compared with the preceding 20 completed bars.
        # Including the signal bar in its own baseline understates a real spike.
        prior_vol = vol.iloc[-21:-1]
        avg_vol = prior_vol.mean() if len(prior_vol) >= 20 else 0
        vol_ratio = vol.iloc[-1] / avg_vol if avg_vol > 0 else 0
        # cap extreme ratios
        try:
            vol_ratio = min(float(vol_ratio), MAX_VOLUME_RATIO)
        except Exception:
            vol_ratio = 0

        # ── Partial-day volume handling ─────────────────────────────
        # If the last bar is today (market open), the current day's volume
        # is incomplete and will make volume_ratio artificially low.
        # Use the previous complete day's volume ratio for confirmation.
        vol_ratio_prev_day = 0.0
        daily_bar_complete = True
        try:
            last_date = df.index[-1]
            if hasattr(last_date, "date"):
                last_date = last_date.date()
            from datetime import date, time
            ist_now = datetime.now(ZoneInfo("Asia/Kolkata"))
            is_today = (last_date == ist_now.date())
            # A daily bar is reliable only after the NSE close buffer. A prior
            # trading date is naturally complete (weekends/holidays included).
            daily_bar_complete = (not is_today) or (
                ist_now.weekday() < 5 and ist_now.time() >= time(15, 40)
            )
            if is_today and not daily_bar_complete and len(vol) >= 2:
                prev_vol = vol.iloc[-2]
                prev_base = vol.iloc[-22:-2].mean() if len(vol) >= 22 else 0
                vol_ratio_prev_day = prev_vol / prev_base if prev_base > 0 else 0
                vol_ratio_prev_day = min(float(vol_ratio_prev_day), MAX_VOLUME_RATIO)
        except Exception:
            vol_ratio_prev_day = 0.0
        # Use the more reliable (complete-day) ratio for eligibility checks
        effective_vol_ratio = vol_ratio_prev_day if vol_ratio_prev_day > 0 else vol_ratio
        # New-high breakout context: close above the PRIOR 10-session high on
        # strong volume (optional swing trigger; see ALLOW_BREAKOUT_TRIGGER).
        prior_high = high.iloc[-(BREAKOUT_TRIGGER_LOOKBACK_BARS + 1):-1].max()
        volume_breakout = bool(
            current > prior_high and effective_vol_ratio >= BREAKOUT_TRIGGER_VOL_RATIO
        )
        prior_value = (close.iloc[-21:-1] * vol.iloc[-21:-1]).dropna()
        median_traded_value_20d = prior_value.median() if len(prior_value) >= 20 else 0
        prev_close= close.iloc[-2]
        price_change_pct = ((current - prev_close) / prev_close) * 100

        # ── Breakdown / dead-cat-bounce awareness ─────────────────────
        # A high-volume breakdown day followed by an up-day bounce is scored
        # positively by the momentum rules (+Volume surge, +Positive day), but
        # unless the bounce reclaims the broken swing high AND carries a fresh
        # bullish trigger it is a classic bull trap. Detect and expose it here
        # so scoring, eligibility, AI prompt and dashboard can all react.
        recent_breakdown_day = False
        breakdown_info = {}
        open_price_now   = float(df["Open"].iloc[-1])
        gap_pct          = ((open_price_now - prev_close) / prev_close) * 100 if prev_close else 0.0
        pct_ser          = close.pct_change() * 100.0
        vol_base         = vol.rolling(20, min_periods=10).median()
        vol_ratio_ser    = (vol / vol_base.replace(0, np.nan)).fillna(0).clip(upper=MAX_VOLUME_RATIO)
        lookback         = min(int(BREAKDOWN_LOOKBACK_BARS), max(len(df) - 2, 0))
        for k in range(1, lookback + 1):
            i = len(df) - 1 - k
            if i <= 1:
                continue
            if (pct_ser.iloc[i] <= CRASH_DAY_PCT and vol_ratio_ser.iloc[i] >= CRASH_DAY_VOL_MULT):
                recent_breakdown_day = True
                pre_win = high.iloc[max(0, i - 5):i]
                breakdown_info = {
                    "date":          df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i]),
                    "change_pct":    round(float(pct_ser.iloc[i]), 2),
                    "volume_ratio":  round(float(vol_ratio_ser.iloc[i]), 2),
                    "reclaim_level": round(float(pre_win.max()) if len(pre_win) else float(high.iloc[i]), 2),
                }
                break
        reclaim_needed = breakdown_info.get("reclaim_level") if recent_breakdown_day else None
        reclaims_breakdown_level = bool(reclaim_needed and current >= reclaim_needed)
        bounce_after_breakdown   = bool(recent_breakdown_day and price_change_pct > 0)

        # ── Recent high-volume reversal guard (SUNPHARMA 2026-09-01) ──
        # A distribution candle (<= REVERSAL_DAY_PCT on >= REVERSAL_DAY_VOL_MULT
        # volume) close to the signal bar means the "positive day" that follows
        # is usually a low-volume bounce back into overhead supply. Unless the
        # latest close reclaims the broken swing high, the gate must treat it
        # as WATCHLIST. Unlike the breakdown guard (2-bar, -4% crash) this
        # catches milder -2% reversals within REVERSAL_LOOKBACK_BARS bars.
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
                    "date":          df.index[i_r].strftime("%Y-%m-%d") if hasattr(df.index[i_r], "strftime") else str(df.index[i_r]),
                    "change_pct":    round(float(pct_ser.iloc[i_r]), 2),
                    "volume_ratio":  round(float(vol_ratio_ser.iloc[i_r]), 2),
                    "reclaim_level": round(float(pre_r_win.max()) if len(pre_r_win) else float(high.iloc[i_r]), 2),
                }
                recent_reversal_day = True
                break
        reclaims_reversal_level = bool(
            reversal_info.get("reclaim_level")
            and current >= reversal_info["reclaim_level"]
        ) if recent_reversal_day else None

        # fresh MACD bullish cross within the last FRESH_TRIGGER_BARS
        fresh_macd = False
        hist_vals  = macd_hist_series.values
        for k2 in range(1, min(FRESH_TRIGGER_BARS + 1, len(hist_vals) - 1)):
            j = len(hist_vals) - 1 - k2
            if j <= 0:
                break
            if hist_vals[j] > 0 and hist_vals[j - 1] <= 0:
                fresh_macd = True
                break

        # empirical continuation stats for this exact setup on this symbol
        bounce_win_pct, bounce_samples = _bounce_after_breakdown_stats(
            close, high, vol, CRASH_DAY_PCT, CRASH_DAY_VOL_MULT,
            min_samples=BOUNCE_HIST_MIN_SAMPLES)
        day_range = max(float(high.iloc[-1]) - float(low.iloc[-1]), 1e-9)
        close_location = float((current - low.iloc[-1]) / day_range)

        # ── Persistent unresolved-breakdown (until reclaim) ─────────────
        # Same guarantee as the analysis engine: a high-volume crash stays a
        # cap on the stock until the broken swing high is reclaimed.
        unresolved_breakdown, unresolved_info = find_unresolved_breakdown(
            close, high, vol, index=df.index,
            lookback=BREAKDOWN_RESOLUTION_LOOKBACK)

        # corporate-action anomaly flag from the shared data pipeline
        data_anomaly = ""
        try:
            if "data_anomaly_str" in df.columns:
                _a = str(df["data_anomaly_str"].dropna().iloc[-1])
                data_anomaly = _a if _a.lower() not in ("", "nan") else ""
        except Exception:
            pass
        adx = ADXIndicator(high, low, close, window=14).adx().iloc[-1]
        obv = (np.sign(close.diff()).fillna(0) * vol).cumsum()
        obv_trend = "rising" if len(obv) >= 5 and obv.iloc[-1] > obv.iloc[-5] else "falling"
        bull_signal_count = sum([
            ema9 > ema21, current > ema50, macd_hist > 0, adx >= 20,
            vol_ratio >= 1.0, price_change_pct > 0,
        ])
        # 52-week high/low — only meaningful with >= 252 trading sessions
        n_52w = min(252, len(high))
        high_52w  = high.iloc[-n_52w:].max()
        low_52w   = low.iloc[-n_52w:].min()

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
                rsi_day = rsi_series.iloc[idx]
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

        # require the crossover to be recent (last trading bars) to avoid stale signals.
        # Uses TRADING BARS, not calendar days (Friday -> Monday is one bar).
        if bullish_crossover_rule is not None:
            try:
                buy_rule_passed = (len(df) - 1 - bullish_crossover_rule["bar_index"]) <= CROSSOVER_RECENCY_BARS
            except Exception:
                buy_rule_passed = True
        else:
            buy_rule_passed = False

        if bearish_crossover_rule is not None:
            try:
                sell_rule_passed = (len(df) - 1 - bearish_crossover_rule["bar_index"]) <= CROSSOVER_RECENCY_BARS
            except Exception:
                sell_rule_passed = True
        else:
            sell_rule_passed = False
        pct_from_52w_high = ((current - high_52w) / high_52w) * 100

        # A BUY needs a fresh trigger: a MACD bullish cross in the last
        # FRESH_TRIGGER_BARS, or a fresh EMA21/50 crossover (buy_rule_passed).
        fresh_bullish_trigger = bool(fresh_macd or buy_rule_passed)

        # Multi-timeframe confirmation for the daily setup.
        weekly_trend = 'unknown'
        multi_tf_confirm = False
        try:
            weekly = df[['Open','High','Low','Close','Volume']].resample('W-FRI').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna()
            if len(weekly) >= 8:
                w_close = weekly['Close']
                w_ema21 = EMAIndicator(w_close, window=21).ema_indicator()
                w_ema50 = EMAIndicator(w_close, window=50).ema_indicator()
                if w_ema21.iloc[-1] > w_ema50.iloc[-1]:
                    weekly_trend = 'bullish'
                elif w_ema21.iloc[-1] < w_ema50.iloc[-1]:
                    weekly_trend = 'bearish'
                else:
                    weekly_trend = 'neutral'
                if (ema21 > ema50 and w_ema21.iloc[-1] > w_ema50.iloc[-1]) or (
                    ema21 < ema50 and w_ema21.iloc[-1] < w_ema50.iloc[-1]):
                    multi_tf_confirm = True
        except Exception:
            weekly_trend = 'unknown'
            multi_tf_confirm = False

        # Empirical validation of the LIVE stretched-breakout setup
        sig_win_pct, sig_n = _historical_signal_win_rate(close, bb_pband_ser, rsi_series)

        return {
            "current_price":      round(current, 2),
            "prev_close":         round(prev_close, 2),
            "open_price":         round(float(df["Open"].iloc[-1]), 2),
            "price_change_pct":   round(price_change_pct, 2),
            "change_pct":         round(price_change_pct, 2),
            "rsi":                round(rsi, 2),
            "rsi_prev":           round(float(rsi_series.iloc[-2]), 2),
            "macd":               round(float(macd_line), 4),
            "macd_signal":        round(float(macd_sig), 4),
            "macd_hist":          round(macd_hist, 4),
            "macd_crossover":     macd_crossover,
            "weekly_trend":       weekly_trend,
            "multi_tf_confirm":   multi_tf_confirm,
            "adx":                round(float(adx), 2),
            "trend_strength":     "strong" if adx >= 25 else "adequate" if adx >= 20 else "weak",
            "obv_trend":          obv_trend,
            "candle_pattern":     "none",
            "bull_signal_count":  bull_signal_count,
            "overall_signal":     "bullish" if bull_signal_count >= 4 else "neutral" if bull_signal_count >= 3 else "bearish",
            "ema9":               round(ema9, 2),
            "ema21":              round(ema21, 2),
            "ema50":              round(ema50, 2),
            "ema200":             round(ema200, 2),
            "bb_upper":           round(bb.bollinger_hband().iloc[-1], 2),
            "bb_lower":           round(bb.bollinger_lband().iloc[-1], 2),
            "bb_mid":             round(bb.bollinger_mavg().iloc[-1], 2),
            "bb_pct":             round(bb_pct, 4),
            "atr":                round(atr, 2),
            "atr_pct":            round(atr_pct, 2),
            "volume":             int(vol.iloc[-1]),
            "avg_volume_20d":     int(avg_vol),
            "volume_ratio":       round(vol_ratio, 2),
            "effective_vol_ratio": round(effective_vol_ratio, 2),
            "prior_10_sessions_high": round(float(prior_high), 2),
            "volume_breakout":   volume_breakout,
            "daily_bar_complete": daily_bar_complete,
            "median_traded_value_20d": round(float(median_traded_value_20d), 2),
            "high_52w":           round(high_52w, 2),
            "low_52w":            round(low_52w, 2),
            "pct_from_52w_high":  round(pct_from_52w_high, 2),
            "support":            round(low.iloc[-10:].min(), 2),
            "support_1":          round(low.iloc[-10:].min(), 2),
            "support_2":          round(low.iloc[-20:].min(), 2),
            "resistance":         round(high.iloc[-10:].max(), 2),
            "resistance_1":       round(high.iloc[-10:].max(), 2),
            "resistance_2":       round(high.iloc[-20:].max(), 2),
            "buy_rule_passed":    buy_rule_passed,
            "buy_rule_details":   bullish_crossover_rule or {},
            "sell_rule_passed":   sell_rule_passed,
            "sell_rule_details":  bearish_crossover_rule or {},
            "sig_win_pct":        sig_win_pct,
            "sig_samples":        sig_n,
            "data_as_of":         str(df.index[-1]),

            # ── Breakdown / dead-cat-bounce awareness ──────────────────
            "recent_breakdown_day":   recent_breakdown_day,
            "breakdown_date":         breakdown_info.get("date"),
            "breakdown_change_pct":   breakdown_info.get("change_pct"),
            "breakdown_volume_ratio": breakdown_info.get("volume_ratio"),
            "breakdown_reclaim_level": reclaim_needed,
            "reclaims_breakdown_level": reclaims_breakdown_level,
            "bounce_after_breakdown": bounce_after_breakdown,
            "fresh_bullish_trigger":  fresh_bullish_trigger,
            "bounce_win_pct":         bounce_win_pct,
            "bounce_samples":         bounce_samples,
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
            "data_anomaly":                data_anomaly,
            "gap_pct":                round(gap_pct, 2),
            "close_location":         round(close_location, 3),
        }

    def score_stock(self, ind: dict, style: str):
        score   = 0
        signals = []

        # Recent price action is a critical risk gate. Weak closes should not be rewarded.
        price_change_pct = ind.get("price_change_pct", 0)
        if price_change_pct < -1.0:
            score -= 20
            signals.append(f"Recent weakness: {price_change_pct:.2f}%")
        elif price_change_pct < 0:
            score -= 8
            signals.append(f"Minor weakness: {price_change_pct:.2f}%")
        elif price_change_pct > 0:
            score += 10
            signals.append(f"Positive day: +{price_change_pct:.2f}%")

        if ind.get("macd_crossover") == "bearish":
            score -= 15
            signals.append("MACD bearish crossover")
        elif ind.get("macd_hist", 0) > 0:
            score += 12
            signals.append("MACD histogram positive")

        if ind.get("adx", 0) < 20:
            score -= 12
            signals.append(f"Weak trend: ADX {ind.get('adx', 0)} below 20")
        elif ind.get("adx", 0) < 25:
            score -= 5
            signals.append(f"Trend still soft: ADX {ind.get('adx', 0)}")

        if ind["ema9"] > ind["ema21"] > ind["ema50"]:
            score += 20
            signals.append("Strong uptrend: EMA9 > EMA21 > EMA50")
        elif ind["ema9"] > ind["ema21"]:
            score += 12
            signals.append("Short-term bullish: EMA9 > EMA21")

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

        # Exhaustion guard: beyond ~52w-hot there is little room left; buying
        # momentum at the top of a range is how the KOTAK-style fades happen.
        if rsi >= 70:
            score -= 10
            signals.append(f"RSI overbought ({rsi}) — entry near exhaustion")
        elif rsi > 68:
            score -= 5
            signals.append(f"RSI in hot zone ({rsi}) — reduced upside room")

        # Use effective volume ratio (handles partial-day volume during market hours)
        eff_vol = ind.get("effective_vol_ratio", ind.get("volume_ratio", 0))
        if eff_vol >= 2.0:
            score += 20
            signals.append(f"Volume surge: {eff_vol}x average")
        elif eff_vol >= 1.5:
            score += 14
            signals.append(f"Above avg volume: {eff_vol}x")
        elif eff_vol >= 1.0:
            score += 7
            signals.append(f"Normal volume: {eff_vol}x")

        if 0.2 <= ind["bb_pct"] <= 0.5:
            score += 15
            signals.append(f"Price in lower-mid Bollinger zone (BB% {ind['bb_pct']})")
        elif ind["bb_pct"] < 0.2:
            score += 10
            signals.append(f"Near lower Bollinger Band (BB% {ind['bb_pct']})")
        elif ind["bb_pct"] > 1.0:
            # A close ABOVE the upper band (BB%>1) is a stretched, mean-reverting
            # state. On range-bound names it is a breakout-FADE, not momentum.
            score -= 10
            signals.append(f"Stretched above upper Bollinger (BB% {ind['bb_pct']}) — breakout-fade risk")
        elif ind["bb_pct"] > 0.8:
            # Near the upper band there is little headroom; the ideal entry zone
            # for INTRADAY/SWING is lower-mid band, not the stretched top.
            score -= 5
            signals.append(f"Close to upper band (BB% {ind['bb_pct']}) — limited upside room")

        # ── Dead-cat-bounce discount ──────────────────────────────────
        # A positive-day up-move after a high-volume breakdown day only earns
        # its momentum points when the bounce reclaimed the broken swing high
        # AND carries a fresh bullish trigger (MACD/EMA cross). Otherwise the
        # +Volume surge / +Positive day awards imply a bull-trap structure and
        # are neutralized below (the setup often fades the next sessions).
        if ind.get("recent_breakdown_day"):
            reclaimed = ind.get("reclaims_breakdown_level", False)
            fresh = ind.get("fresh_bullish_trigger", False)
            if not (reclaimed and fresh):
                score -= 25
                signals.append("Dead-cat bounce: up-day after breakdown without "
                               "reclaim + fresh trigger")
            elif not fresh:
                score -= 10
            bw = ind.get("bounce_win_pct")
            bs = ind.get("bounce_samples", 0)
            if bw is not None and bs >= BOUNCE_HIST_MIN_SAMPLES and bw < 45:
                score -= 10
                signals.append(f"Bounce-fade history: continuation only {bw:.0f}% "
                               f"({bs} samples)")
        elif ind.get("price_change_pct", 0) < 0 and eff_vol >= 1.5:
            # high-volume down day without a preceding crash: warn, do not award
            score -= 10
            signals.append("High-volume down day — distribution risk")

        # Fresh-trigger discipline outside the breakdown case: an otherwise
        # rolling stock without a fresh MACD/EMA cross is a momentum "drift" —
        # mark it explicitly so the AI and users know the candle, not a trigger.
        if not ind.get("recent_breakdown_day"):
            if (not ind.get("fresh_bullish_trigger", False)
                    and not ind.get("macd_crossover") == "bullish"):
                signals.append("No fresh bullish crossover — drift, not a trigger")

        # Empirical fade check: a stretched above-band setup that historically
        # does NOT deliver next-day gains on this symbol gets discounted.
        sig_win = ind.get("sig_win_pct")
        sig_n = ind.get("sig_samples", 0)
        if sig_win is not None and sig_n >= 20 and sig_win < 50:
            score -= 12
            signals.append(f"Breakout-fade history: setup wins next day only {sig_win:.0f}% ({sig_n} sessions)")

        # Risk-adjusted expectancy gate: a system with weak historical success and
        # a wide ATR stop is not a buy just because it looks good on a single day.
        ev, ev_reason = _risk_adjusted_expected_value(ind, style)
        if ev is not None:
            if ev < 0.15:
                score -= 15
                signals.append(ev_reason)
            elif ev < 0.3:
                score -= 8
                if ev_reason:
                    signals.append(ev_reason)

        if style in ("intraday", "short_term") and ind["atr_pct"] >= 1.5:
            score += 5
            signals.append(f"High short-term volatility (ATR {ind['atr_pct']}%)")
        if style == "positional" and ind["pct_from_52w_high"] > -20:
            score += 5
            signals.append("Near 52-week high")

        return min(max(score, 0), 100), signals

    def passes_filter(self, ind: dict, style: str) -> bool:
        c = SCREEN_CRITERIA[style]
        p = ind["current_price"]
        # price_change_pct is the canonical key; tolerate the change_pct-only
        # shape produced by IndicatorEngine.compute_all (defensive — a missing
        # key must never take down the whole Analyze page as a KeyError).
        price_move = ind.get("price_change_pct", ind.get("change_pct", 0)) or 0
        return (
            c["min_price"] <= p <= c["max_price"]
            and ind["avg_volume_20d"] >= c["min_volume"]
            and c["rsi_min"] <= ind["rsi"] <= c["rsi_max"]
            and abs(price_move) <= c["max_price_change_pct"]
            and ind["atr_pct"] >= c["min_atr_pct"]
            and ind["pct_from_52w_high"] >= -45
        )

    def evaluate_buy_eligibility(self, ind: dict, style: str) -> tuple[bool, list[str]]:
        """Deterministic, auditable buy gate. AI commentary cannot override it."""
        c = SCREEN_CRITERIA[style]
        failures = []
        if not (ind["ema9"] > ind["ema21"] > ind["ema50"]):
            failures.append("EMA trend is not aligned (EMA9 > EMA21 > EMA50)")
        if ind["current_price"] <= ind["ema21"]:
            failures.append("Price is not above EMA21")
        if ind.get("macd_hist", 0) <= 0 or ind.get("macd_crossover") == "bearish":
            failures.append("MACD momentum is not bullish")
        if ind.get("adx", 0) < ADX_MIN_FOR_BUY:
            failures.append(f"Trend strength is weak (ADX {ind.get('adx', 0)})")
        # Use effective volume ratio (handles partial-day volume during market hours).
        # Two layers: the raw minimum must be STRICTLY exceeded (no boundary pass),
        # then a confirmation-margin check — a ratio only marginally above the
        # floor is not real volume confirmation. (SUNPHARMA 2026-09-02 printed a
        # 0.8x bounce that exactly met the old 0.8x positional floor and was
        # offered as BUY; it faded the next session.)
        eff_vol = float(ind.get("effective_vol_ratio", ind.get("volume_ratio", 0)) or 0)
        min_vol = float(c["min_volume_ratio"])
        if eff_vol <= min_vol:
            failures.append(f"Volume confirmation below {min_vol:g}x average")
        volume_margin = VOLUME_CONFIRMATION_MARGIN_BY_STYLE.get(
            style, VOLUME_CONFIRMATION_MARGIN
        )
        if eff_vol > min_vol and eff_vol < min_vol * volume_margin:
            failures.append(
                f"Volume confirmation is marginal ({eff_vol:.2f}x vs "
                f"{min_vol:g}x minimum with {volume_margin:g}x buffer)"
            )
        if ind.get("price_change_pct", 0) < -1:
            failures.append("Recent daily price weakness exceeds 1%")
        # Weekly / multi-timeframe confirmation — a daily signal fighting the
        # weekly trend is a lower-conviction trade. For a STRONG recommendation
        # the weekly trend must agree (daily & weekly EMA21/50 on the same side).
        # Missing data is treated as UNKNOWN, not a hard fail, so a no-data / partial
        # object does not get rejected by default. Only explicit disagreement fails.
        tf_confirm = ind.get("multi_tf_confirm")
        if tf_confirm is False:
            failures.append(
                "Weekly trend does not confirm the daily setup (multi-TF disagreement)"
            )
        # ── Fresh-trigger requirement ────────────────────────────────
        # A BUY must be anchored to a real bullish ignition: a fresh MACD line
        # bullish cross (within FRESH_TRIGGER_BARS) or a fresh EMA21/50 crossover.
        # A stock that is merely "above its EMAs with a slightly positive session"
        # but has no cross is a drift trade with no edge. Positional allows a
        # strong-trend exception: ADX>=25, real volume and weekly confirmation.
        fresh_trigger = bool(ind.get("fresh_bullish_trigger", False))
        # Optional alternative ignition: a high-volume NEW-HIGH breakout (close
        # above the prior 10-session high on >= BREAKOUT_TRIGGER_VOL_RATIO
        # volume) may ignite swing/short-term entries when enabled (in line with
        # the pilot-buy discipline, this is OFF until validated on frozen history).
        breakout_trigger = bool(
            ALLOW_BREAKOUT_TRIGGER
            and ind.get("volume_breakout", False)
            and style in ("short_term", "swing"))
        has_trigger = fresh_trigger or breakout_trigger
        if style in ("intraday", "short_term", "swing"):
            if not has_trigger:
                needs = "MACD line cross or EMA21/50 crossover"
                if ALLOW_BREAKOUT_TRIGGER:
                    needs += " or a high-volume new-high breakout (>= " \
                             f"{BREAKOUT_TRIGGER_VOL_RATIO:g}x vol above prior resistance)"
                failures.append(
                    f"No fresh bullish trigger within lookback (need {needs}) "
                    "— drift without ignition"
                )
        elif not has_trigger:
            strong_trend = float(ind.get("adx", 0) or 0) >= ADX_STRONG_FOR_NO_TRIGGER
            strong_vol = eff_vol >= 1.0
            tf_ok = ind.get("multi_tf_confirm") is not False
            if not (strong_trend and strong_vol and tf_ok):
                failures.append(
                    "No fresh bullish trigger and trend too weak for a positional BUY "
                    f"(need ADX>={ADX_STRONG_FOR_NO_TRIGGER}, volume>=1.0x and weekly confirmation)"
                )
        # Stop-distance cap: if the ATR stop sits too far below entry, one
        # adverse day (or a gap) inflicts an outsized loss. HINDCOPPER
        # (2026-08-21, swing BUY @ 560, stop ~₹499.8 ≈ 10.5% away) then printed a
        # -7.2% crash day that never stopped the position out. Cap it.
        price = ind.get("current_price", 0) or 0
        atr = ind.get("atr", 0) or 0
        atr_mult = ATR_MULT.get(style, 2.5)
        stop_pct = (atr_mult * atr / price) * 100 if (atr > 0 and price > 0) else 0.0
        cap = MAX_STOP_DISTANCE_PCT_BY_STYLE.get(style, 8.0)
        if stop_pct > cap:
            failures.append(
                f"ATR stop distance too wide ({stop_pct:.1f}% > {cap:.1f}% cap) — "
                f"a single bad day risks {stop_pct:.0f}% of the position"
            )
        # Persistent unresolved-breakdown guard — a high-volume crash that has
        # NOT been reclaimed blocks BUY regardless of how many bars have passed
        # since the crash (HINDCOPPER crashed 2026-08-24, still below 586.75).
        if ind.get("unresolved_breakdown"):
            lvl = ind.get("unresolved_reclaim_level")
            d = ind.get("unresolved_breakdown_date")
            lvl_txt = f" (still below ₹{lvl})" if lvl else ""
            failures.append(
                f"Unresolved high-volume breakdown {d or 'recently'}{lvl_txt} — "
                f"price never reclaimed the broken swing high; WATCHLIST only"
            )
        # Stretched breakout guard: a close ABOVE the upper Bollinger (BB%>1)
        # is mean-reversion territory. Require that the momentum is confirmed
        # by a fresh EMA21/50 crossover, otherwise it is a breakout-FADE.
        if ind.get("bb_pct", 0) > 1.0 and not ind.get("buy_rule_passed", False):
            failures.append(
                f"Price stretched above upper Bollinger (BB% {ind.get('bb_pct')}) "
                "without EMA21/50 crossover confirmation — breakout-fade risk"
            )
        # Exhaustion guard for short-term entries
        rsi_now = ind.get("rsi", 0)
        if rsi_now >= 70:
            failures.append(f"RSI overbought ({rsi_now}) — no entry headroom")
        # Empirical fade check — this symbol's own history says the setup fades
        if ind.get("sig_samples", 0) >= 20 and ind.get("sig_win_pct") is not None \
                and ind.get("sig_win_pct") < 45:
            failures.append(
                f"Historical fade: this stretched setup wins next session only "
                f"{ind.get('sig_win_pct')}% ({ind.get('sig_samples')} samples)"
            )

        ev, ev_reason = _risk_adjusted_expected_value(ind, style)
        if ev is not None and ev < 0.15:
            failures.append(ev_reason or "Expected value is too weak for a new BUY")
        # ── Dead-cat-bounce guard ─────────────────────────────────────
        # After a high-volume breakdown day, a one-off up-day rally that has
        # NOT reclaimed the broken swing high is a bull trap — participants buy
        # the bounce, institutions distribute into it, price fades. Require:
        #   1) the broken swing high to be reclaimed, and
        #   2) a fresh bullish trigger (MACD cross / fresh EMA21-50 cross)
        # to upgrade the setup to BUY. Otherwise it remains a WATCHLIST.
        if ind.get("recent_breakdown_day"):
            lvl = ind.get("breakdown_reclaim_level")
            if not ind.get("reclaims_breakdown_level", False):
                lvl_txt = f" (reclaim ₹{lvl})" if lvl else ""
                failures.append(
                    f"Bounce after high-volume breakdown — price below broken swing "
                    f"high{lvl_txt}; no reclaim confirmation"
                )
            if not ind.get("fresh_bullish_trigger", False):
                failures.append(
                    "Bounce after breakdown lacks a fresh MACD/EMA bullish "
                    "crossover — WATCHLIST only, not a confirmed BUY"
                )
            bw = ind.get("bounce_win_pct")
            bs = ind.get("bounce_samples", 0)
            if bw is not None and bs >= BOUNCE_HIST_MIN_SAMPLES and bw < 45:
                failures.append(
                    f"Historical bounce-fade: after similar setups the next-session "
                    f"continuation is only {bw}% ({bs} samples)"
                )
        # ── Recent high-volume reversal guard (SUNPHARMA 2026-09-01) ──
        # A distribution candle within REVERSAL_LOOKBACK_BARS that has NOT been
        # reclaimed means the signal bar is a low-volume bounce into overhead
        # supply. The exact SUNPHARMA shape: -2.8% on 2.3x volume at the 1984.8
        # swing high on 2026-09-01, then a +0.14% on 0.8x volume on 09-02 was
        # offered as positional BUY — the next session faded -0.8%.
        if ind.get("recent_reversal_day"):
            r_lvl = ind.get("reversal_reclaim_level")
            if not ind.get("reclaims_reversal_level", False):
                lvl_txt = f" (reclaim ₹{r_lvl})" if r_lvl else ""
                d_txt = ind.get("reversal_date", "recently")
                r_chg = ind.get("reversal_change_pct")
                r_vr = ind.get("reversal_volume_ratio")
                failures.append(
                    f"Recent high-volume reversal {d_txt}: {r_chg}% on {r_vr}x volume"
                    f"{lvl_txt} NOT reclaimed — low-volume bounce into overhead supply"
                )
        return not failures, failures

    def screen(self, styles=["intraday","swing","positional"], top_n=10) -> dict:
        print(f"\n{'='*55}")
        print(f"  NSE/BSE Stock Screener — {self.scan_time}")
        print(f"  Scanning {len(NSE_STOCKS)} stocks...")
        print(f"{'='*55}\n")

        # Market regime filter — do not allow new buys in a bearish market
        market_regime = check_market_regime()
        regime = market_regime.get("regime", "unknown")
        print(f"  Market regime: {regime.upper()}")
        if regime == "bearish":
            print("  ⚠ NIFTY below EMA50 — new BUY signals suppressed (market-regime filter).")
        elif regime == "unknown" and MARKET_REGIME_FAIL_CLOSED:
            print("  ⚠ NIFTY regime UNKNOWN (index data unavailable) — BUY signals "
                  "suppressed under fail-closed policy.")
        print()

        # 21-bar NIFTY return consumed only by the optional pilot-buy path.
        nifty_r21 = None
        try:
            nifty_r21 = _nifty_return(PILOT_RS_LOOKBACK_BARS)
        except Exception:
            nifty_r21 = None

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

            # fetch fundamentals (yfinance.info) once per symbol and compute strategy scores.
            # The live-info dict is unit-broken for `debtToEquity` on NSE tickers and often
            # drops ROE/ROCE/FCF, so the deterministic gate and quality scorers consume the
            # BEST-AVAILABLE merge: unit-correct annual-statement quality metrics + fresh
            # live valuation (P/E, P/B, sector). No threshold is relaxed — only the data.
            try:
                ticker_obj = yf.Ticker(resolve_provider_ticker(symbol))
                live_info = ticker_obj.info or {}
            except Exception:
                live_info = {}

            try:
                from fundamental_snapshots import record_snapshot
                record_snapshot(symbol, live_info)
            except Exception:
                pass

            fundamentals = merge_fundamental_snapshots(symbol, live_info)

            sector = (fundamentals.get('sector') or '')

            buff_score, buff_reasons = strategies.score_buffett(ind, fundamentals, sector=sector)
            graham_score, graham_reasons = strategies.score_graham(ind, fundamentals, sector=sector)
            lynch_score, lynch_reasons = strategies.score_lynch(ind, fundamentals)
            templeton_score, templeton_reasons = strategies.score_templeton(ind, fundamentals)
            greenblatt_score, greenblatt_reasons = strategies.score_greenblatt(ind, fundamentals, sector=sector)
            marks_score, marks_reasons = strategies.score_marks(ind, fundamentals)
            rakesh_score, rakesh_reasons = strategies.score_rakesh(ind, fundamentals)
            try:
                fundamentals['symbol'] = symbol
                roce_score, roce_reasons, roce_metrics = strategies.score_roce_reinvest(ind, fundamentals, sector=sector)
            except Exception:
                roce_score, roce_reasons, roce_metrics = 0, ["roce scorer failed"], {"roce": None, "reinvest": None}

            # ── Cross-style consistency ────────────────────────────────
            # Track per-style eligibility failures per symbol. A structural
            # rejection (trend, momentum, breakdown/reversal, trigger) in a
            # stricter style must not be re-offered by a looser style — the
            # SUNPHARMA 2026-09-02 shape was intraday WATCHLIST becoming a
            # positional BUY.
            style_failures = {}

            for style in styles:
                    if self.passes_filter(ind, style):
                        score, signals = self.score_stock(ind, style)

                        # Technical setup drives a trade; fundamentals are a
                        # bounded quality overlay. Weights sum to exactly one.
                        quality_score = (buff_score + graham_score + greenblatt_score + roce_score) / 4
                        ensemble_score = int(round(score * 0.70 + quality_score * 0.30))

                        if ensemble_score >= BUY_MIN_ENSEMBLE:
                            is_buy, failed_checks = self.evaluate_buy_eligibility(ind, style)

                            if REQUIRE_COMPLETED_DAILY_BAR_FOR_BUY and not ind.get("daily_bar_complete", False):
                                is_buy = False
                                failed_checks = list(failed_checks) + [
                                    "Daily bar is incomplete — BUY deferred until post-close confirmation"
                                ]

                            min_technical = MIN_TECHNICAL_SCORE_FOR_BUY.get(style, 65)
                            if score < min_technical:
                                is_buy = False
                                failed_checks = list(failed_checks) + [
                                    f"Technical score {score} below {min_technical} "
                                    "BUY floor — WATCHLIST only"
                                ]

                            fundamental_ok, fundamental_failures = fundamental_buy_gate(
                                fundamentals, quality_score, sector=sector
                            )
                            if not fundamental_ok:
                                is_buy = False
                                failed_checks = list(failed_checks) + fundamental_failures

                            if style == "intraday" and not ALLOW_DAILY_BAR_INTRADAY_BUY:
                                is_buy = False
                                failed_checks = list(failed_checks) + [
                                    "Intraday BUY requires intraday candles; daily data is "
                                    "WATCHLIST-only until an intraday feed is available"
                                ]

                            # Inherit structural failures from stricter styles.
                            inherited = inherit_strict_style_failures(style_failures, style)
                            if inherited:
                                is_buy = False
                                failed_checks = list(failed_checks) + inherited
                            style_failures[style] = list(failed_checks)

                            # Corporate-action data anomaly: the price series is
                            # unreliable (split/bonus), so NO signal may be issued
                            # on it. (HINDCOPPER 2026-08-31 morning run used a
                            # pre-split price of 1037.4 vs the real 525.3.)
                            anomaly = ind.get("data_anomaly", "") or ""
                            if anomaly:
                                is_buy = False
                                failed_checks = failed_checks + [anomaly]

                            # Market-regime filter: suppress BUY in a bearish market and fail
                            # closure on "unknown" (see market_regime_blocks_buy).
                            regime = market_regime.get("regime", "unknown")
                            regime_blocks, regime_reason = market_regime_blocks_buy(regime)
                            regime_tier = "Tier 1 (Full Buy)"
                            position_scale = 1.0
                            pilot_notes = ""
                            watchlist_promotable = False
                            if regime_blocks:
                                # ── Pilot path (optional) ──────────────────────
                                # A candidate may become a reduced-size PILOT BUY
                                # only when the regime filter is its SOLE failure
                                # and it clears stricter stock-level filters
                                # (own 50d/200d EMAs, RS vs NIFTY, high-volume
                                # breakout, EPS growth when reported).
                                # Missing NIFTY data is a risk-control failure, not a
                                # bearish regime eligible for a discretionary pilot.
                                if regime == "bearish" and pilot_gate_eligible(failed_checks, anomaly):
                                    pilot_ok, pilot_fails, p_notes = pilot_conditions_met(
                                        ind, fundamentals, nifty_r21,
                                        close=df["Close"], high=df["High"])
                                    if pilot_ok:
                                        is_buy = True
                                        regime_tier = "Tier 2 (Pilot Buy)"
                                        position_scale = PILOT_POSITION_SCALE
                                        pilot_notes = (
                                            "NIFTY below EMA50 — upgraded to PILOT BUY "
                                            "under stricter filters: "
                                            + ("; ".join(p_notes) or "all stock-level filters met")
                                        )
                                        failed_checks = []
                                    else:
                                        is_buy = False
                                        regime_tier = "Tier 0 (No Buy)"
                                        failed_checks = failed_checks + [
                                            regime_reason + " — pilot filters missed: "
                                            + ("; ".join(pilot_fails) or "insufficient data")
                                        ]
                                else:
                                    is_buy = False
                                    regime_tier = "Tier 0 (No Buy)"
                                    # Fully qualified stock-level, suppressed ONLY by
                                    # the external regime filter -> surface as a
                                    # promotable watchlist (COALINDIA-type name).
                                    watchlist_promotable = bool(
                                        len(failed_checks) == 0 and not anomaly
                                    )
                                    failed_checks = failed_checks + [regime_reason]
                            elif not is_buy:
                                regime_tier = "Tier 0 (No Buy)"

                            # Earnings-event filter: suppress BUY within blackout window
                            earnings_risk = check_earnings_risk(symbol)
                            if earnings_risk.get("risk"):
                                is_buy = False
                                failed_checks = failed_checks + [
                                    f"Earnings event on {earnings_risk.get('earnings_date', '?')} "
                                    f"({earnings_risk.get('days_to_earnings', '?')} days away) — gap risk"
                                ]

                            # Tier represents the final actionable state. A later
                            # earnings blackout must not leave a rejected row
                            # labelled as a Pilot/Full Buy.
                            if not is_buy:
                                regime_tier = "Tier 0 (No Buy)"
                                position_scale = 1.0

                            outobj = {
                                "symbol":    symbol.replace(".NS", ""),
                                "yf_symbol": symbol,
                                "style":     style,
                                "score":     score,
                                "signals":   signals,
                                "buffett_score": buff_score,
                                "buffett_reasons": buff_reasons,
                                "graham_score": graham_score,
                                "graham_reasons": graham_reasons,
                                "lynch_score": lynch_score,
                                "lynch_reasons": lynch_reasons,
                                "templeton_score": templeton_score,
                                "templeton_reasons": templeton_reasons,
                                "greenblatt_score": greenblatt_score,
                                "greenblatt_reasons": greenblatt_reasons,
                                "marks_score": marks_score,
                                "marks_reasons": marks_reasons,
                                "rakesh_score": rakesh_score,
                                "rakesh_reasons": rakesh_reasons,
                                "ensemble_score": ensemble_score,
                                "quality_score": round(quality_score, 1),
                                "recommendation": "BUY" if is_buy else "WATCHLIST",
                                "selection_decision": "BUY" if is_buy else "WATCHLIST",
                                "eligibility_failures": failed_checks,
                                "regime_tier": regime_tier,
                                "position_scale": round(position_scale, 2),
                                "pilot_notes": pilot_notes or None,
                                "watchlist_promotable": bool(watchlist_promotable),
                                "sector": sector,
                                "market_regime": market_regime.get("regime", "unknown"),
                                **ind
                            }

                            if roce_metrics:
                                outobj['roce_score'] = roce_score
                                outobj['roce_reasons'] = roce_reasons
                                outobj.update(roce_metrics)
                            else:
                                outobj['roce_score'] = 0
                                outobj['roce_reasons'] = ['unavailable']

                            all_results[style].append(outobj)

        final = {}
        for style in styles:
            sorted_stocks = sorted(all_results[style],
                                   key=lambda x: x.get("ensemble_score", x["score"]), reverse=True)
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
            decisions = Counter(s.get("selection_decision", "WATCHLIST")
                                for s in stocks)
            reasons = Counter(
                failure
                for stock in stocks
                for failure in stock.get("eligibility_failures", [])
            )
            print(f"  Decision funnel: BUY={decisions.get('BUY', 0)} | "
                  f"WATCHLIST={decisions.get('WATCHLIST', 0)}")
            if reasons:
                print("  Top rejection reasons:")
                for reason, count in reasons.most_common(3):
                    print(f"    {count}x {reason}")
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
        with open(paths.path("screener_results.json"), "w") as f:
            json.dump(output, f, indent=2, default=str)


if __name__ == "__main__":
    screener = StockScreener()
    screener.screen(styles=["intraday","swing","positional"], top_n=10)
