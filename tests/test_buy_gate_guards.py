"""
Regression tests for the buy-gate safety guards added after the SUNPHARMA
2026-09-03 review:

  * volume confirmation must strictly exceed (no boundary pass) and carry a
    VOLUME_CONFIRMATION_MARGIN surplus;
  * a recent high-volume reversal that has not been reclaimed blocks BUY;
  * a genuine fresh bullish trigger is required (intraday/swing always,
    positional unless trend is strongly confirmed);
  * market regime "unknown" fails closed;
  * structural failures in stricter styles propagate to looser styles.
"""
from config import (VOLUME_CONFIRMATION_MARGIN, MARKET_REGIME_FAIL_CLOSED,
                    MAX_STOP_DISTANCE_PCT_BY_STYLE, ATR_MULT)
from screener import (StockScreener, market_regime_blocks_buy,
                      inherit_strict_style_failures, fundamental_buy_gate)


def _passing_stock(**overrides):
    """An indicator dict that passes EVERY eligibility check for every style.

    Fine-tune one facet per test via overrides.
    """
    stock = {
        "ema9": 1950.0,
        "ema21": 1930.0,
        "ema50": 1900.0,
        "current_price": 1960.0,
        "atr": 18.0,
        "atr_pct": 0.92,
        "rsi": 55.0,
        "macd_hist": 1.5,
        "macd_crossover": "none",
        "adx": 26.0,
        "volume": 2_000_000,
        "avg_volume_20d": 1_500_000,
        "volume_ratio": 1.40,
        "effective_vol_ratio": 1.40,
        "price_change_pct": 0.5,
        "bb_pct": 0.5,
        "pct_from_52w_high": -12.0,
        "buy_rule_passed": False,
        "sell_rule_passed": False,
        "buy_rule_details": {},
        "sell_rule_details": {},
        "fresh_bullish_trigger": True,
        "multi_tf_confirm": True,
        "obv_trend": "rising",
        "unresolved_breakdown": False,
        "recent_breakdown_day": False,
        "recent_reversal_day": False,
        "reclaims_reversal_level": None,
        "sig_win_pct": None,
        "sig_samples": 0,
        "bounce_win_pct": None,
        "bounce_samples": 0,
        "data_anomaly": "",
        "gap_pct": 0.0,
    }
    stock.update(overrides)
    return stock


def test_all_styles_pass_on_clean_setup():
    """Sanity check: the base fixture actually passes every style."""
    s = StockScreener()
    for style in ("intraday", "swing", "positional"):
        ok, fails = s.evaluate_buy_eligibility(_passing_stock(), style)
        assert ok, (style, fails)


# ── Volume confirmation ─────────────────────────────────────────
def test_volume_at_exact_floor_is_blocked():
    """A volume ratio exactly at the (raised) positional floor must fail."""
    s = StockScreener()
    ok, fails = s.evaluate_buy_eligibility(
        _passing_stock(effective_vol_ratio=1.0, volume_ratio=1.0), "positional"
    )
    assert not ok
    assert any("Volume confirmation" in f for f in fails)


def test_marginal_volume_is_blocked_by_margin_buffer():
    """A ratio barely above the floor is not real confirmation."""
    s = StockScreener()
    stock = _passing_stock(effective_vol_ratio=1.05, volume_ratio=1.05)
    ok, fails = s.evaluate_buy_eligibility(stock, "positional")
    assert not ok
    assert any("marginal" in f for f in fails)
    # intraday requires 1.2x * margin -> a 1.3x intraday read is also marginal
    ok2, fails2 = s.evaluate_buy_eligibility(
        _passing_stock(effective_vol_ratio=1.30, volume_ratio=1.30), "intraday"
    )
    assert not ok2
    assert any("marginal" in f for f in fails2)
def test_volume_surplus_above_margin_passes_volume():
    """1.4x comfortably exceeds every style's minimum * margin."""
    s = StockScreener()
    for style in ("intraday", "swing", "positional"):
        fails = s.evaluate_buy_eligibility(_passing_stock(), style)[1]
        assert not any("Volume confirmation" in f for f in fails), (style, fails)


def test_positional_volume_minimum_is_one_x():
    """The old 0.8x positional floor must be gone (SUNPHARMA regression)."""
    from screener import SCREEN_CRITERIA
    assert SCREEN_CRITERIA["positional"]["min_volume_ratio"] >= 1.0


# ── Recent high-volume reversal guard ───────────────────────────
def _reversal_stock(**overrides):
    stock = _passing_stock(
        recent_reversal_day=True,
        reversal_date="2026-09-01",
        reversal_change_pct=-2.81,
        reversal_volume_ratio=2.3,
        reversal_reclaim_level=1984.8,
        reclaims_reversal_level=False,
    )
    stock.update(overrides)
    return stock


def test_recent_reversal_not_reclaimed_blocks_all_styles():
    """SUNPHARMA 2026-09-01 shape: high-volume reversal under the swing high."""
    s = StockScreener()
    for style in ("intraday", "swing", "positional"):
        ok, fails = s.evaluate_buy_eligibility(_reversal_stock(), style)
        assert not ok, style
        assert any("reversal" in f for f in fails), (style, fails)


def test_recent_reversal_reclaimed_does_not_block():
    """Once the broken swing high is reclaimed the reversal guard lifts."""
    s = StockScreener()
    stock = _reversal_stock(reclaims_reversal_level=True)
    ok, fails = s.evaluate_buy_eligibility(stock, "positional")
    assert ok, fails


def test_reversal_detected_in_compute_indicators_sunpharma():
    """End-to-end reversal detection uses a stable synthetic price series."""
    import numpy as np
    import pandas as pd

    dates = pd.date_range("2025-01-01", periods=120, freq="D")
    close = np.linspace(90.0, 100.0, len(dates))
    close[-2:] = [96.5, 97.0]
    df = pd.DataFrame({
        "Open": close,
        "High": close + 0.5,
        "Low": close - 0.5,
        "Close": close,
        "Volume": np.full(len(dates), 100_000.0),
    }, index=dates)
    df.iloc[-2, df.columns.get_loc("Volume")] = 250_000.0

    ind = StockScreener().compute_indicators(df)
    assert ind.get("recent_reversal_day") is True
    assert ind.get("reclaims_reversal_level") is False


# ── Fresh-trigger requirement ───────────────────────────────────
def test_no_fresh_trigger_blocks_intraday_and_swing():
    s = StockScreener()
    stock = _passing_stock(fresh_bullish_trigger=False)
    for style in ("intraday", "swing"):
        ok, fails = s.evaluate_buy_eligibility(stock, style)
        assert not ok, style
        assert any("fresh bullish trigger" in f for f in fails), (style, fails)


def test_positional_no_trigger_needs_strong_trend():
    s = StockScreener()
    # weak trend + no trigger -> blocked
    ok, fails = s.evaluate_buy_eligibility(
        _passing_stock(fresh_bullish_trigger=False, adx=22), "positional"
    )
    assert not ok
    assert any("trigger" in f for f in fails)
    # strong trend (ADX>=25), volume and weekly confirmation -> allowed
    ok2, fails2 = s.evaluate_buy_eligibility(
        _passing_stock(fresh_bullish_trigger=False, adx=28), "positional"
    )
    assert ok2, fails2


# ── Market regime fail-closed ───────────────────────────────────
def test_market_regime_fail_closed_default():
    assert MARKET_REGIME_FAIL_CLOSED is True
    block, reason = market_regime_blocks_buy("unknown")
    assert block
    assert "fail-closed" in reason
    assert market_regime_blocks_buy("bearish")[0]
    assert not market_regime_blocks_buy("bullish")[0]


def test_missing_fundamentals_cannot_approve_buy():
    ok, failures = fundamental_buy_gate({}, 100)
    assert not ok
    assert any("Fundamental data unavailable" in failure for failure in failures)


def test_incomplete_fundamentals_cannot_approve_buy():
    fundamentals = {
        "returnOnEquity": 0.2,
        "debtToEquity": 0.5,
        "freeCashflow": 1,
    }
    ok, failures = fundamental_buy_gate(fundamentals, 80)
    assert not ok
    assert any("data points" in failure for failure in failures)


def test_complete_fundamentals_can_approve_quality_gate():
    fundamentals = {
        "returnOnEquity": 0.2,
        "debtToEquity": 0.5,
        "freeCashflow": 1,
        "profitMargins": 0.1,
    }
    ok, failures = fundamental_buy_gate(fundamentals, 40)
    assert ok, failures


def test_fundamental_gate_rejects_high_debt():
    fundamentals = {
        "returnOnEquity": 0.2,
        "debtToEquity": 3.0,
        "freeCashflow": 1,
        "profitMargins": 0.1,
    }
    ok, failures = fundamental_buy_gate(fundamentals, 40)
    assert not ok
    assert any("Debt-to-equity" in failure for failure in failures)


def test_fundamental_gate_uses_sector_debt_norms():
    fundamentals = {
        "returnOnEquity": 0.2,
        "debtToEquity": 5.0,
        "freeCashflow": 1,
        "profitMargins": 0.1,
    }
    ok, failures = fundamental_buy_gate(fundamentals, 40, sector="Financial Services")
    assert ok, failures

    ok, failures = fundamental_buy_gate(fundamentals, 40, sector="Technology")
    assert not ok
    assert any("Debt-to-equity" in failure for failure in failures)


def test_fundamental_gate_rejects_excessive_valuation():
    fundamentals = {
        "returnOnEquity": 0.2,
        "debtToEquity": 0.5,
        "freeCashflow": 1,
        "profitMargins": 0.1,
        "forwardPE": 65,
    }
    ok, failures = fundamental_buy_gate(fundamentals, 40)
    assert not ok
    assert any("P/E" in failure for failure in failures)


def test_fundamental_gate_rejects_no_return_engine():
    fundamentals = {
        "debtToEquity": 0.5,
        "trailingPE": 20,
        "priceToBook": 2,
        "earningsGrowth": 0,
    }
    ok, failures = fundamental_buy_gate(fundamentals, 40)
    assert not ok
    assert any("profitability or cash-flow" in failure for failure in failures)


def test_market_regime_unknown_optional_pass():
    """Fail-closed can be disabled explicitly, but must then not block."""
    block, reason = market_regime_blocks_buy("unknown", fail_closed=False)
    assert not block
    assert reason == ""


# ── Cross-style consistency ─────────────────────────────────────
def test_structural_failures_propagate_to_looser_styles():
    style_failures = {
        "intraday": [
            "MACD momentum is not bullish",
            "Volume confirmation below 1.2x average",  # style-specific
            "ATR stop distance too wide (5.0% > 4.0% cap)",  # style-specific
        ]
    }
    inherited = inherit_strict_style_failures(style_failures, "positional")
    assert "MACD momentum is not bullish" in inherited
    assert not any("Volume confirmation" in f for f in inherited)
    assert not any("ATR stop" in f for f in inherited)


def test_loser_style_inherits_reversal_from_stricter():
    style_failures = {
        "intraday": [
            "Recent high-volume reversal 2026-09-01: -2.81% on 2.3x volume "
            "(reclaim Rs.1984.8) NOT reclaimed - low-volume bounce into "
            "overhead supply"
        ]
    }
    inherited = inherit_strict_style_failures(style_failures, "swing")
    assert inherited and "reversal" in inherited[0]


def test_intraday_data_requirement_does_not_propagate():
    """Daily data blocks intraday BUYs, but remains valid for daily styles."""
    style_failures = {
        "intraday": [
            "Intraday BUY requires intraday candles; daily data is WATCHLIST-only "
            "until an intraday feed is available"
        ]
    }
    assert inherit_strict_style_failures(style_failures, "swing") == []
    assert inherit_strict_style_failures(style_failures, "positional") == []


# ── Stop-distance caps (triggered by the ATR_STYLE change) ──────
def test_stop_caps_tightened():
    assert MAX_STOP_DISTANCE_PCT_BY_STYLE["swing"] <= 5.0
    assert MAX_STOP_DISTANCE_PCT_BY_STYLE["positional"] <= 6.0


def test_wide_atr_stop_blocked_at_new_cap():
    """A 6.1% ATR stop must be blocked for positional under the new 6% cap,
    and a 5.1% stop for swing under the new 5% cap."""
    s = StockScreener()
    # positional: 3 * ATR / price. With ATR 40 and price 1960 -> 6.12% > 6%
    ok, fails = s.evaluate_buy_eligibility(
        _passing_stock(atr=40.0, atr_pct=2.04), "positional"
    )
    assert not ok
    assert any("ATR stop distance too wide" in f for f in fails)
    # swing cap is 5%; 2.5*40/1960 = 5.10% > 5%
    ok2, fails2 = s.evaluate_buy_eligibility(
        _passing_stock(atr=40.0, atr_pct=2.04), "swing"
    )
    assert not ok2
    assert any("ATR stop distance too wide" in f for f in fails2)