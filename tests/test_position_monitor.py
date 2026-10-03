"""Tests for the open-position stop/target monitor (alerts.py).

These tests never touch the network or Telegram — quote_fn is injected and
send_telegram is monkeypatched.
"""
import json

import pytest

from alerts import position_monitor_status, check_position_alerts


def _holding(overrides=None):
    base = {
        "symbol": "HINDCOPPER", "buy_price": 545.64, "quantity": 43,
        "target": 623.29, "stop_loss": 518.36, "style": "swing",
    }
    base.update(overrides or {})
    return base


def test_status_ok_between_stop_and_target():
    rows = position_monitor_status(
        portfolio={"holdings": [_holding()]},
        quote_fn=lambda s: 590.0)
    assert len(rows) == 1
    r = rows[0]
    assert r["status"] == "OK"
    assert r["symbol"] == "HINDCOPPER"
    assert r["pnl_pct"] == pytest.approx(8.13, abs=0.02)  # 590 / 545.64 - 1


def test_status_stop_hit():
    rows = position_monitor_status(
        portfolio={"holdings": [_holding()]},
        quote_fn=lambda s: 510.0)
    assert rows[0]["status"] == "STOP_HIT"
    assert rows[0]["trigger_level"] == 518.36


def test_status_target_hit():
    rows = position_monitor_status(
        portfolio={"holdings": [_holding()]},
        quote_fn=lambda s: 630.0)
    assert rows[0]["status"] == "TARGET_HIT"
    assert rows[0]["trigger_level"] == 623.29


def test_status_no_quote():
    rows = position_monitor_status(
        portfolio={"holdings": [_holding()]},
        quote_fn=lambda s: 0.0)
    assert rows[0]["status"] == "NO_QUOTE"


def test_check_position_alerts_fires_once_per_level(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr("alerts.send_telegram", lambda msg: sent.append(msg))
    monkeypatch.setattr(
        "alerts._position_monitor_state_file",
        lambda: str(tmp_path / "position_alerts_fired.json"))

    portfolio = {"holdings": [_holding()]}
    first = check_position_alerts(portfolio=portfolio, quote_fn=lambda s: 510.0)
    assert first["fired"] == ["HINDCOPPER:STOP_HIT"]
    assert first["checked"] == 1
    assert len(sent) == 1

    # Second call at the same level must NOT re-fire (deduplicated).
    second = check_position_alerts(portfolio=portfolio, quote_fn=lambda s: 500.0)
    assert second["fired"] == []
    assert len(sent) == 1

    # A new level (target) still fires.
    third = check_position_alerts(portfolio=portfolio, quote_fn=lambda s: 640.0)
    assert third["fired"] == ["HINDCOPPER:TARGET_HIT"]
    assert len(sent) == 2

    # State file persisted on disk.
    state = json.loads((tmp_path / "position_alerts_fired.json").read_text())
    assert "HINDCOPPER:stop_hit:518.36" in state
    assert "HINDCOPPER:target_hit:623.29" in state