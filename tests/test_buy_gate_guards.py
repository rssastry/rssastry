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
                      inherit_strict_style_failures, fundamental_buy_gate,
                      pilot_conditions_met, pilot_gate_eligible)


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


# ── Pilot-buy path (NIFTY below EMA50) ───────────────────────────────────
# pilot_conditions_met decides whether a candidate whose ONLY buy-gate failure
# is the market-regime filter may be upgraded to a reduced-size PILOT BUY.

def _pilot_ind(**overrides):
    ind = {
        "current_price": 1960.0,
        "ema50": 1900.0,
        "ema200": 1800.0,
        "resistance_1": 1950.0,
        "volume_ratio": 2.0,
        "effective_vol_ratio": 2.0,
        "daily_bar_complete": True,
        "median_traded_value_20d": 10_00_00_000,
    }
    ind.update(overrides)
    return ind


def test_pilot_approves_when_all_strict_filters_pass():
    # Stock +10% in 21 bars vs NIFTY -5% => RS ≈ 1.16x >= 1.10x
    # Prior 10-session high = 105 < 110, so the volume breakout confirms.
    close = [100.0] * 21 + [110.0]
    high = [105.0] * 21 + [111.0]
    ok, fails, notes = pilot_conditions_met(
        _pilot_ind(), {"earningsGrowth": 0.25}, nifty_return=-0.05,
        close=close, high=high)
    assert ok, fails
    assert any("RS vs NIFTY" in n for n in notes)
    assert any("breakout" in n for n in notes)


def test_pilot_blocks_when_relative_strength_too_low():
    # Stock flat while NIFTY rose => RS < 1.10x required.
    close = [100.0] * 21 + [100.0]
    ok, fails, _ = pilot_conditions_met(
        _pilot_ind(), {"earningsGrowth": 0.25}, nifty_return=0.05, close=close)
    assert not ok
    assert any("RS filter" in f for f in fails)


def test_pilot_blocks_when_nifty_benchmark_missing():
    # Stock return is fine; the NIFTY benchmark is what is unavailable.
    ok, fails, _ = pilot_conditions_met(
        _pilot_ind(), {"earningsGrowth": 0.25}, nifty_return=None,
        close=[100.0] * 21 + [110.0])
    assert not ok
    assert any("NIFTY benchmark" in f for f in fails)


def test_pilot_requires_completed_bar_and_liquidity():
    close = [100.0] * 21 + [110.0]
    high = [105.0] * 21 + [111.0]
    ok, fails, _ = pilot_conditions_met(
        _pilot_ind(daily_bar_complete=False, median_traded_value_20d=1_00_00_000),
        {"earningsGrowth": 0.25}, nifty_return=-0.05, close=close, high=high)
    assert not ok
    assert any("completed daily breakout bar" in f for f in fails)
    assert any("liquidity filter" in f for f in fails)


def test_pilot_requires_resistance_history():
    ok, fails, _ = pilot_conditions_met(
        _pilot_ind(), {"earningsGrowth": 0.25}, nifty_return=-0.05,
        close=[100.0] * 21 + [110.0])
    assert not ok
    assert any("breakout-volume" in f for f in fails)


def test_pilot_blocks_when_breakout_volume_too_low():
    ok, fails, _ = pilot_conditions_met(
        _pilot_ind(volume_ratio=1.2, effective_vol_ratio=1.2),
        {"earningsGrowth": 0.25}, nifty_return=-0.05,
        close=[100.0] * 21 + [110.0], high=[105.0] * 21 + [111.0])
    assert not ok
    assert any("breakout-volume" in f for f in fails)


def test_pilot_blocks_when_close_not_above_prior_resistance():
    # Volume is huge but the close (108) is still BELOW yesterday's 10-day
    # high (111) -- not a breakout, must not qualify. Synthetic prices must be
    # internally consistent with ind['current_price'] (108) so only the
    # breakout leg fails.
    close = [100.0] * 21 + [108.0]
    high = [111.0] * 21 + [112.0]
    ok, fails, _ = pilot_conditions_met(
        _pilot_ind(current_price=108.0, ema50=100.0, ema200=90.0),
        {"earningsGrowth": 0.25}, nifty_return=-0.05,
        close=close, high=high)
    assert not ok
    assert any("breakout" in f for f in fails)


def test_pilot_requires_stock_above_own_200day_ema():
    ok, fails, _ = pilot_conditions_met(
        _pilot_ind(ema200=1970.0), {"earningsGrowth": 0.25}, nifty_return=-0.05,
        close=[100.0] * 21 + [110.0])
    assert not ok
    assert any("200-day EMA" in f for f in fails)


def test_pilot_eps_growth_floor_blocks_when_reported_low():
    ok, fails, _ = pilot_conditions_met(
        _pilot_ind(), {"earningsGrowth": 0.05}, nifty_return=-0.05,
        close=[100.0] * 21 + [110.0])
    assert not ok
    assert any("EPS growth" in f for f in fails)


def test_pilot_eps_growth_missing_is_advisory_not_blocking():
    ok, fails, notes = pilot_conditions_met(
        _pilot_ind(), {"returnOnEquity": 0.2}, nifty_return=-0.05,
        close=[100.0] * 21 + [110.0], high=[105.0] * 21 + [111.0])
    assert ok, fails
    assert any("advisory" in n for n in notes)


def test_pilot_gate_eligible_regime_must_be_sole_failure():
    """Regression: a fully-qualified candidate has FAILED_CHECKS == [] at the
    regime point; the pilot path may only rescue THAT case, never one that
    carries another (non-regime) failure."""
    assert pilot_gate_eligible([], anomaly=False, enabled=True) is True
    assert pilot_gate_eligible([], anomaly=False) is False         # disabled by default
    assert pilot_gate_eligible(["some other failure"], anomaly=False) is False
    assert pilot_gate_eligible([], anomaly=True) is False
    assert pilot_gate_eligible([], anomaly=False, enabled=False) is False
def test_passes_filter_tolerates_change_pct_only_shape():
    """Analyze-page payloads come from IndicatorEngine.compute_all() which
    emits 'change_pct' (no 'price_change_pct'). passes_filter must not raise
    KeyError and must still enforce the daily-move cap via the alias."""
    screener = StockScreener()
    ind = {
        "current_price": 1000.0,
        "avg_volume_20d": 3_000_000,
        "rsi": 55.0,
        "change_pct": 1.5,          # IndicatorEngine shape: no price_change_pct
        "atr_pct": 1.1,
        "pct_from_52w_high": -20.0,
    }
    assert screener.passes_filter(ind, "swing") is True
    ind["change_pct"] = -9.0        # beyond swing's 8% move cap => reject
    assert screener.passes_filter(ind, "swing") is False


def test_indicator_engine_emits_price_change_pct_alias():
    """IndicatorEngine.compute_all must expose the canonical key that the
    deterministic gate / passes_filter expect (regression for the Analyze
    page KeyError)."""
    import numpy as np
    import pandas as pd

    from indicators import IndicatorEngine

    idx = pd.bdate_range("2024-01-01", periods=260)
    close = np.linspace(100.0, 140.0, 260)
    engine = IndicatorEngine("TEST.NS")
    engine.df = pd.DataFrame(
        {"Open": close, "High": close + 1.0, "Low": close - 1.0,
         "Close": close, "Volume": np.full(260, 1_000_000.0)},
        index=idx,
    )
    out = engine.compute_all()
    assert out.get("price_change_pct") is not None
    assert out["price_change_pct"] == out["change_pct"]

def test_breakout_trigger_off_by_default_blocks():
    """High-volume new-high breakout is a valid candidate signal, but the
    config-gated trigger is OFF by default -> swing still needs a canonical
    fresh trigger."""
    s = StockScreener()
    ok, fails = s.evaluate_buy_eligibility(
        _passing_stock(fresh_bullish_trigger=False, volume_breakout=True), "swing")
    assert not ok
    assert any("No fresh bullish trigger" in f for f in fails)


def test_breakout_trigger_ignites_swing_when_enabled(monkeypatch):
    import screener as scr
    monkeypatch.setattr(scr, "ALLOW_BREAKOUT_TRIGGER", True)
    s = StockScreener()
    ok, fails = s.evaluate_buy_eligibility(
        _passing_stock(fresh_bullish_trigger=False, volume_breakout=True), "swing")
    assert ok, fails
    # intraday must NOT inherit the breakout trigger (needs real intraday candles)
    ok2, fails2 = s.evaluate_buy_eligibility(
        _passing_stock(fresh_bullish_trigger=False, volume_breakout=True), "intraday")
    assert not ok2
    assert any("No fresh bullish trigger" in f for f in fails2)


def test_breakout_trigger_requires_volume_confirmation(monkeypatch):
    import screener as scr
    monkeypatch.setattr(scr, "ALLOW_BREAKOUT_TRIGGER", True)
    s = StockScreener()
    ok, fails = s.evaluate_buy_eligibility(
        _passing_stock(fresh_bullish_trigger=False, volume_breakout=False), "swing")
    assert not ok
    assert any("No fresh bullish trigger" in f for f in fails)