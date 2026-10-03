"""Tests for legacy-holding reconciliation (portfolio.validate_portfolio).

Network-free: portfolio._local_atr is monkeypatched so recommended_levels uses
a deterministic ATR and never touches local CSVs or the network.
"""
import pytest

from portfolio import validate_portfolio, recommended_levels, _local_atr


def _portfolio(target=540.0, stop=520.5, style="swing"):
    return {"holdings": [
        {"symbol": "HINDCOPPER", "buy_price": 545.64, "quantity": 43,
         "buy_date": "2026-08-27", "target": target, "stop_loss": stop,
         "style": style, "investment": 23462.52},
    ], "closed_trades": [], "last_updated": ""}


def test_validate_portfolio_flags_target_below_entry(monkeypatch):
    monkeypatch.setattr("portfolio._local_atr", lambda symbol, period=14: 15.53)
    report = validate_portfolio(_portfolio(target=540.0, stop=520.5), fix=False)
    assert report["checked"] == 1
    assert report["valid"] == 0
    assert len(report["issues"]) == 1
    assert report["issues"][0]["symbol"] == "HINDCOPPER"
    assert any("target" in f.lower() or "reward" in f.lower()
               for f in report["issues"][0]["failures"])


def test_validate_portfolio_fix_rebuilds_compliant_plan(monkeypatch, tmp_path):
    # NEVER write to the real portfolio.json: point the module at a temp file.
    monkeypatch.setattr("portfolio.PORTFOLIO_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr("portfolio._local_atr", lambda symbol, period=14: 15.53)
    report = validate_portfolio(_portfolio(target=540.0, stop=520.5), fix=True)
    assert len(report["fixed"]) == 1
    assert report["issues"] == []
    corrected = report["fixed"][0]
    assert corrected["new_target"] > corrected["buy_price"]
    assert corrected["new_stop"] < corrected["buy_price"]
    # The stored holding itself was updated.
    assert corrected["symbol"] == "HINDCOPPER"


def test_recommended_levels_valid_plan(monkeypatch):
    monkeypatch.setattr("portfolio._local_atr", lambda symbol, period=14: 15.53)
    plan = recommended_levels("HINDCOPPER", 545.64, "swing")
    assert plan["target"] > 545.64 * 1.02          # min target delta covered
    assert 0 < plan["stop_loss"] < 545.64
    rr = (plan["target"] - 545.64) / (545.64 - plan["stop_loss"])
    assert rr >= 2.0


def test_recommended_levels_fallback_without_atr(monkeypatch):
    monkeypatch.setattr("portfolio._local_atr", lambda symbol, period=14: None)
    plan = recommended_levels("NOSUCHSTOCK", 100.0, "swing")
    assert plan["target"] == 110.0          # +10% deterministic fallback
    assert plan["stop_loss"] == pytest.approx(95.0, abs=0.01)
    assert plan["atr"] is None