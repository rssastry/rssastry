from screener import StockScreener
from portfolio import (
    validate_holding_fields,
    add_holding,
    load_portfolio,
    save_portfolio,
    last_add_failures,
    check_portfolio_risk,
    rank_buy_candidates,
    allocate_portfolio_buy_candidates,
    get_sector_leader,
    compute_relative_strength,
)
import json
import os
import numpy as np
import pandas as pd

import portfolio as portfolio_module
import pytest


@pytest.fixture(autouse=True)
def _isolate_portfolio_file(tmp_path, monkeypatch):
    """Never read/write the real portfolio.json during tests.

    Several tests in this file temporarily mutate the live portfolio; run them
    against a throwaway file so the repo's portfolio.json is always safe.
    """
    monkeypatch.setattr(portfolio_module, "PORTFOLIO_FILE",
                        str(tmp_path / "portfolio.json"))
    # Seed the isolated file with the same shape the module expects.
    portfolio_module.save_portfolio(
        {"holdings": [], "closed_trades": [], "last_updated": ""})


def test_weak_momentum_stock_is_penalized():
    stock = {
        "ema9": 174.0,
        "ema21": 173.0,
        "ema50": 172.0,
        "macd_hist": -0.05,
        "current_price": 174.0,
        "buy_rule_passed": False,
        "sell_rule_passed": False,
        "rsi": 50.0,
        "price_change_pct": -0.6,
        "volume_ratio": 1.2,
        "bb_pct": 0.5,
        "atr_pct": 2.0,
        "pct_from_52w_high": -15,
        "adx": 15.0,
        "macd_crossover": "bearish",
    }

    score, signals = StockScreener().score_stock(stock, "intraday")

    assert score < 50, f"Expected weak momentum stock to be penalized, got score {score}. Signals: {signals}"
    assert any("Recent weakness" in s or "Weak trend" in s or "bearish" in s.lower() for s in signals)


def _base_stock(**overrides):
    stock = {
        "ema9": 394.43,
        "ema21": 392.22,
        "ema50": 390.19,
        "macd_hist": 0.64,
        "current_price": 402.8,
        "buy_rule_passed": False,
        "sell_rule_passed": False,
        "rsi": 62.0,
        "price_change_pct": 1.37,
        "volume_ratio": 1.67,
        "effective_vol_ratio": 1.67,
        "bb_pct": 0.5,
        "atr_pct": 1.72,
        "pct_from_52w_high": -10.97,
        "adx": 27.17,
        "macd_crossover": "none",
    }
    stock.update(overrides)
    return stock


def _bounce_stock(**overrides):
    """A dead-cat bounce profile: up-day after a high-volume breakdown day,
    with the price still below the broken swing high (HINDCOPPER 26-Aug 2026
    shape: crash -7.2% on 4.2x vol, bounce +4.4%, still below 586.75 peak)."""
    stock = _base_stock(
        current_price=556.05,
        ema9=553.24,
        ema21=539.06,
        ema50=525.19,
        rsi=56.46,
        price_change_pct=4.39,
        volume_ratio=4.72,
        adx=26.02,
        recent_breakdown_day=True,
        breakdown_date="2026-08-25",
        breakdown_change_pct=-7.23,
        breakdown_volume_ratio=4.21,
        breakdown_reclaim_level=586.75,
        reclaims_breakdown_level=False,
        bounce_after_breakdown=True,
        fresh_bullish_trigger=False,
    )
    stock.update(overrides)
    if "bounce_win_pct" not in stock:
        stock["bounce_win_pct"] = None
    stock["bounce_samples"] = stock.get("bounce_samples", 12)
    return stock


def test_dead_cat_bounce_is_blocked_for_all_styles():
    """A bounce after a high-volume breakdown that has not reclaimed the broken
    swing high (and has no fresh MACD/EMA cross) must never pass the BUY gate."""
    bounce = _bounce_stock()
    for style in ("intraday", "swing", "positional"):
        ok, failures = StockScreener().evaluate_buy_eligibility(bounce, style)
        assert not ok, f"{style}: dead-cat bounce must be WATCHLIST, got BUY"
        assert any("breakdown" in f for f in failures), failures


def test_dead_cat_bounce_is_penalized_in_score():
    bounce = _bounce_stock()
    score, signals = StockScreener().score_stock(bounce, "swing")
    assert score < 85, f"Dead-cat bounce should be penalized, got {score}"
    assert any("Dead-cat" in s for s in signals), signals


def test_reclaimed_bounce_with_fresh_trigger_passes():
    """Same recovery structure but price closed back above the broken swing high
    AND a fresh MACD bullish cross exists -> a legitimate re-entry BUY."""
    ok_bounce = _bounce_stock(
        current_price=590.2,          # above 586.75 reclaim level
        reclaims_breakdown_level=True,
        macd_crossover="bullish",
        fresh_bullish_trigger=True,
        macd_hist=1.2,
        price_change_pct=2.1,
        close_location=0.85,
    )
    ok, failures = StockScreener().evaluate_buy_eligibility(ok_bounce, "swing")
    assert ok, failures


def test_bounce_without_fresh_trigger_stays_watchlist_even_if_reclaimed():
    """Price reclaimed the swing high but no fresh MACD/EMA cross yet — still
    a WATCHLIST because a lone reclaimed candle is not a confirmed reversal."""
    mid = _bounce_stock(
        current_price=590.2,
        reclaims_breakdown_level=True,
        macd_crossover="none",
        fresh_bullish_trigger=False,
        macd_hist=0.4,
    )
    ok, failures = StockScreener().evaluate_buy_eligibility(mid, "swing")
    assert not ok
    assert any("fresh MACD/EMA" in f for f in failures), failures


def test_stretched_above_band_is_penalized():
    """Close above the upper Bollinger (BB% > 1) is a fade, not a buy signal."""
    stretched = _base_stock(bb_pct=1.06)
    score, signals = StockScreener().score_stock(stretched, "intraday")

    assert any("Stretched above upper Bollinger" in s or "fade" in s.lower() for s in signals)


def test_stretched_above_band_fails_eligibility():
    """KOTAK-style stretched breakout without EMA crossover = WATCHLIST, not BUY."""
    stretched = _base_stock(bb_pct=1.06)
    ok, failures = StockScreener().evaluate_buy_eligibility(stretched, "intraday")
    assert not ok
    assert any("upper Bollinger" in f for f in failures)


def test_rsi_overbought_penalized():
    rsi_high = _base_stock(rsi=72, bb_pct=0.4)
    score, signals = StockScreener().score_stock(rsi_high, "intraday")
    assert any("RSI overbought" in s for s in signals)


def test_sweetspot_entry_not_penalized():
    sweet = _base_stock(rsi=56, bb_pct=0.45)
    score, signals = StockScreener().score_stock(sweet, "intraday")
    assert not any("Stretched" in s or "overbought" in s.lower() for s in signals)


def test_target_and_stoploss_are_hard_risk_controls():
    """An actionable holding must carry a valid stop, target and reward/risk."""

    # Bad reward/risk (1.33) must be rejected.
    ok, failures = validate_holding_fields("TEST", 100, 10, 104, 97, "swing")
    assert not ok
    assert any("reward/risk" in f for f in failures)

    # Stop above entry is invalid.
    ok, failures = validate_holding_fields("TEST", 100, 10, 97, 104, "swing")
    assert not ok
    assert any("stop_loss" in f for f in failures)

    ok, failures = validate_holding_fields("TEST", 100, 10, 110, 95, "swing")
    assert ok, failures


def test_quantity_buy_price_and_style_still_validated():
    """Core safety fields are still enforced by holding validation."""
    ok, failures = validate_holding_fields("TEST", 0, 0, 104, 97, "swing")
    assert not ok
    assert any("buy_price" in f for f in failures)
    assert any("quantity" in f for f in failures)

    ok, failures = validate_holding_fields("TEST", 100, 10, 104, 97, "momentum")
    assert not ok
    assert any("style" in f for f in failures)


def test_validate_holding_fields_never_raises_on_bad_input():
    """Zero, None and non-numeric fields must NEVER raise (validate-only).

    Regression guard for the ZeroDivisionError that buy_price=0 used to
    trigger inside the percentage / reward-risk math.
    """
    invalid_inputs = [
        {"buy_price": 0},
        {"buy_price": None},
        {"buy_price": "abc"},
        {"stop_loss": "abc"},
        {"target": "abc"},
        {"quantity": "abc"},
        {"quantity": None},
        {"stop_loss": None},
        {"target": None},
    ]
    for overrides in invalid_inputs:
        kwargs = {"symbol": "TEST", "buy_price": 100, "quantity": 10,
                  "target": 110, "stop_loss": 95, "style": "swing"}
        kwargs.update(overrides)
        ok, failures = validate_holding_fields(**kwargs)
        assert not ok, f"Expected rejection for {overrides}, got ok"
        assert failures, f"Expected failure reasons for {overrides}"


def test_duplicate_position_prevented_and_restores():
    orig = json.dumps(load_portfolio())
    try:
        add_holding("ZZTESTX", 50, 1, "2026-08-24", 55, 48, "swing", cash=100000)
        assert "ZZTESTX" in [h["symbol"] for h in load_portfolio()["holdings"]]
        # second add of same symbol must be rejected
        ok = add_holding("ZZTESTX", 50, 1, "2026-08-24", 55, 48, "swing", cash=100000)
        assert not ok
        assert last_add_failures and "already in your portfolio" in last_add_failures[0]
    finally:
        save_portfolio(json.loads(orig))


def test_screener_exposes_weekly_trend_confirmation():
    dates = pd.date_range('2024-01-01', periods=260, freq='B')
    close = pd.Series(np.linspace(100, 190, len(dates)), index=dates)
    high = close * 1.02
    low = close * 0.98
    volume = pd.Series(1_500_000, index=dates)
    df = pd.DataFrame({'Close': close, 'High': high, 'Low': low, 'Volume': volume, 'Open': close})

    out = StockScreener().compute_indicators(df)

    assert 'weekly_trend' in out
    assert 'multi_tf_confirm' in out
    assert out['multi_tf_confirm'] is True


def test_sector_exposure_limit_blocks_overweight_buy():
    orig = json.dumps(load_portfolio())
    try:
        save_portfolio({
            'holdings': [
                {"symbol": "RELIANCE", "investment": 60000.0, "sector": "Energy"},
            ],
            'closed_trades': [],
            'last_updated': "2026-01-01"
        })

        ok, failures = check_portfolio_risk('TCS', sector='Energy', cash=100000, notional=50000.0)
        assert not ok
        assert any('sector' in f.lower() for f in failures)
    finally:
        save_portfolio(json.loads(orig))


def test_account_risk_uses_stop_distance_not_position_notional():
    orig = json.dumps(load_portfolio())
    try:
        save_portfolio({'holdings': [], 'closed_trades': [], 'last_updated': ''})

        # A 20% notional position with only 1% stop risk should be allowed.
        ok, failures = check_portfolio_risk(
            'TEST', cash=100000, notional=20000, risk_amount=1000
        )
        assert ok, failures

        # A position risking more than 2% of account cash must be blocked.
        ok, failures = check_portfolio_risk(
            'TEST', cash=100000, notional=20000, risk_amount=2500
        )
        assert not ok
        assert any('Single position risk' in failure for failure in failures)
    finally:
        save_portfolio(json.loads(orig))


def test_suggest_buys_passes_stop_risk_to_portfolio_check(monkeypatch):
    captured = []

    def fake_check(symbol, sector=None, cash=None, notional=None, risk_amount=None):
        captured.append(risk_amount)
        return True, []

    class FakeScreener:
        def screen(self, **kwargs):
            return {"swing": [{
                "symbol": "TEST",
                "yf_symbol": "TEST.NS",
                "current_price": 100.0,
                "atr": 10.0,
                "ensemble_score": 80,
                "recommendation": "BUY",
                "style": "swing",
            }], "positional": []}

    monkeypatch.setattr("screener.StockScreener", FakeScreener)
    monkeypatch.setattr("portfolio.check_portfolio_risk", fake_check)
    monkeypatch.setattr("portfolio.compute_position_and_stop", lambda *args, **kwargs: {
        "qty": 10, "stop_price": 90.0, "risk_amount": 1000.0
    })
    monkeypatch.setattr("portfolio.load_portfolio", lambda: {"holdings": []})
    monkeypatch.setattr("portfolio.get_correlation", lambda *_: 0.0)

    suggestions = allocate_portfolio_buy_candidates([], cash=100000)
    assert suggestions == []

    from portfolio import suggest_buys
    suggest_buys(100000)
    assert captured == [100.0]


def test_rank_buy_candidates_prefers_risk_adjusted_edge():
    candidates = [
        {
            "symbol": "A",
            "ensemble_score": 78,
            "quality_score": 67,
            "sig_win_pct": 58,
            "sig_samples": 36,
            "multi_tf_confirm": True,
            "adx": 30,
            "sector": "Banking",
        },
        {
            "symbol": "B",
            "ensemble_score": 82,
            "quality_score": 60,
            "sig_win_pct": 22,
            "sig_samples": 45,
            "multi_tf_confirm": True,
            "adx": 18,
            "sector": "Auto",
        },
    ]

    ranked = rank_buy_candidates(candidates)
    assert ranked[0]["symbol"] == "A"
    assert ranked[0]["portfolio_rank_score"] >= ranked[1]["portfolio_rank_score"]


def test_allocate_portfolio_buy_candidates_respects_sector_cap():
    candidates = [
        {"symbol": "A", "sector": "Energy", "current_price": 100, "atr": 3.0, "ensemble_score": 85, "quality_score": 70, "sig_win_pct": 60, "sig_samples": 30, "multi_tf_confirm": True, "adx": 30},
        {"symbol": "B", "sector": "Energy", "current_price": 100, "atr": 3.0, "ensemble_score": 83, "quality_score": 68, "sig_win_pct": 58, "sig_samples": 30, "multi_tf_confirm": True, "adx": 28},
        {"symbol": "C", "sector": "IT", "current_price": 100, "atr": 2.5, "ensemble_score": 76, "quality_score": 72, "sig_win_pct": 55, "sig_samples": 30, "multi_tf_confirm": True, "adx": 27},
    ]

    allocations = allocate_portfolio_buy_candidates(candidates, cash=100000, max_positions=3)
    assert len(allocations) <= 2
    assert all(item["sector"] != "Energy" or item["notional"] <= 30000 for item in allocations)


def test_rank_buy_candidates_includes_relative_strength_bonus():
    """Sector leaders should rank higher due to RS bonus."""
    candidates = [
        {
            "symbol": "LEADER",
            "sector": "Energy",
            "ensemble_score": 85,
            "quality_score": 75,
            "sig_win_pct": 60,
            "sig_samples": 40,
            "multi_tf_confirm": True,
            "adx": 32,
        },
        {
            "symbol": "LAGGARD",
            "sector": "Energy",
            "ensemble_score": 65,
            "quality_score": 60,
            "sig_win_pct": 52,
            "sig_samples": 30,
            "multi_tf_confirm": True,
            "adx": 22,
        },
    ]

    ranked = rank_buy_candidates(candidates)
    # Leader should have higher rank score due to RS bonus
    assert ranked[0]["symbol"] == "LEADER"
    assert ranked[0]["relative_strength_score"] == 10.0
    # Laggard far from leader, should get 0 RS bonus
    assert ranked[1]["relative_strength_score"] == 0.0


def test_compute_relative_strength_sector_leader():
    """Sector leader should get 10.0 RS bonus."""
    leader = {"symbol": "A", "ensemble_score": 85}
    rs = compute_relative_strength(leader, leader)
    assert rs == 10.0


def test_compute_relative_strength_close_to_leader():
    """Candidate within 3 points of leader should get 10.0 RS bonus."""
    leader = {"ensemble_score": 80}
    close = {"ensemble_score": 79}
    rs = compute_relative_strength(close, leader)
    assert rs == 10.0

    close2 = {"ensemble_score": 77}
    rs = compute_relative_strength(close2, leader)
    assert rs == 10.0


def test_compute_relative_strength_moderately_below():
    """Candidate 5 points below leader should get 5.0 RS bonus."""
    leader = {"ensemble_score": 80}
    moderate = {"ensemble_score": 75}
    rs = compute_relative_strength(moderate, leader)
    assert rs == 5.0


def test_compute_relative_strength_far_below():
    """Candidate >8 points below leader should get 0 RS bonus."""
    leader = {"ensemble_score": 80}
    lagging = {"ensemble_score": 70}
    rs = compute_relative_strength(lagging, leader)
    assert rs == 0.0


def test_get_sector_leader():
    """Should identify highest-scoring candidate in a sector."""
    candidates = [
        {"symbol": "A", "sector": "Banking", "ensemble_score": 75},
        {"symbol": "B", "sector": "Banking", "ensemble_score": 85},
        {"symbol": "C", "sector": "IT", "ensemble_score": 90},
    ]

    leader = get_sector_leader(candidates, "Banking")
    assert leader["symbol"] == "B"
    assert leader["ensemble_score"] == 85


def test_get_sector_leader_returns_none_for_missing_sector():
    """Should return None if sector has no candidates."""
    candidates = [
        {"symbol": "A", "sector": "Banking", "ensemble_score": 75},
    ]

    leader = get_sector_leader(candidates, "IT")
    assert leader is None

