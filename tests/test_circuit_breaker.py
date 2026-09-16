"""Tests for the risk circuit breaker (automation kill-switch)."""

import pytest

from circuit_breaker import RiskCircuitBreaker


def test_allows_normal_day(tmp_path):
    cb = RiskCircuitBreaker(state_path=str(tmp_path / "cb.json"))
    cb.record_day_result(-1.0, equity=100000)
    allowed, reason = cb.pre_trade_check()
    assert allowed is True
    assert "open" in reason


def test_trips_on_daily_loss_breach(tmp_path):
    cb = RiskCircuitBreaker(state_path=str(tmp_path / "cb.json"),
                            max_daily_loss_pct=2.0)
    status = cb.record_day_result(-2.5, equity=100000)
    assert status["tripped"] is True
    allowed, reason = cb.pre_trade_check()
    assert allowed is False
    assert "daily loss" in reason


def test_trips_on_drawdown_breach(tmp_path):
    cb = RiskCircuitBreaker(state_path=str(tmp_path / "cb.json"),
                            max_drawdown_pct=15.0)
    cb.record_day_result(0.0, equity=100000)
    status = cb.record_day_result(0.0, equity=80000)  # -20% from peak
    assert status["tripped"] is True
    allowed, _ = cb.pre_trade_check()
    assert allowed is False
    assert status["drawdown_pct"] == pytest.approx(20.0, abs=0.001)


def test_daily_counter_resets_on_date_rollover(tmp_path):
    cb = RiskCircuitBreaker(state_path=str(tmp_path / "cb.json"),
                            max_daily_loss_pct=2.0)
    cb.record_day_result(-1.5, date_str="2026-01-05")
    cb.record_day_result(-1.5, date_str="2026-01-06")
    allowed, _ = cb.pre_trade_check()
    assert allowed is True


def test_reset_clears_trip(tmp_path):
    cb = RiskCircuitBreaker(state_path=str(tmp_path / "cb.json"))
    cb.record_day_result(-5.0, equity=100000)
    assert cb.pre_trade_check()[0] is False
    cb.reset()
    assert cb.pre_trade_check()[0] is True


def test_state_survives_reload(tmp_path):
    path = str(tmp_path / "cb.json")
    cb = RiskCircuitBreaker(state_path=path)
    cb.record_day_result(-3.0, equity=100000)
    cb2 = RiskCircuitBreaker(state_path=path)
    allowed, reason = cb2.pre_trade_check()
    assert allowed is False
    assert "daily loss" in reason
