"""The intraday style can never BUY on daily bars, so the AI second opinion
should be skipped for it (pure token spend) whenever the policy flag is on.

Network-free: _init_engine and analyze_stock are stubbed, so no API key is
needed and no LLM call is ever made. paths.path is redirected to a temp dir so
the real ai_analysis.json / ai_analysis_progress.json are never overwritten.
"""
import os

import paths
from ai_analyst import AIAnalyst

_INTRADAY_PICKS = [{
    "symbol": "TEST", "yf_symbol": "TEST.NS", "selection_decision": "WATCHLIST",
    "eligibility_failures": ["Intraday BUY requires intraday candles"],
}]

_SWING_PICKS = [{
    "symbol": "TEST", "yf_symbol": "TEST.NS", "selection_decision": "BUY",
    "eligibility_failures": [],
}]


def test_analyze_top_picks_skips_intraday_when_policy_disabled(monkeypatch,
                                                                tmp_path):
    from config import AI_SKIP_POLICY_DISABLED_STYLES, ALLOW_DAILY_BAR_INTRADAY_BUY
    if not (AI_SKIP_POLICY_DISABLED_STYLES and not ALLOW_DAILY_BAR_INTRADAY_BUY):
        raise AssertionError("test precondition: policy must disable intraday AI")

    calls = []

    def _fake_engine(self):
        self.client = object()
        self.engine_name = "stub"
        self.analysis_date = "2026-10-02"

    def _fake_analyze(self, symbol, style, **kwargs):
        calls.append(style)
        return {
            "symbol": "TEST", "trading_style": style, "recommendation": "BUY",
            "confidence_score": 80, "analysis_summary": "",
            "entry_price": {"ideal": 100, "range_low": 99, "range_high": 101},
            "target_prices": {"T1": 105, "T2": 108, "T3": 112},
            "stop_loss": 97.0, "risk_reward_ratio": "1:2",
            "hold_duration": "2-3 days", "risk_level": "Medium",
            "key_signals": [], "exit_trigger": "", "alert_on_price": {},
            "data_anomaly": None,
        }

    monkeypatch.setattr(AIAnalyst, "_init_engine", _fake_engine)
    monkeypatch.setattr(AIAnalyst, "analyze_stock", _fake_analyze)
    # Never touch the real ai_analysis*.json files on disk.
    monkeypatch.setattr(paths, "path",
                        lambda rel: str(tmp_path / os.path.basename(rel)))
    analyst = AIAnalyst()
    out = analyst.analyze_top_picks(
        {"intraday": _INTRADAY_PICKS, "swing": _SWING_PICKS},
        delay_seconds=0)
    # analyze_stock was called ONLY for swing, never for intraday.
    assert calls == ["swing"]
    assert out["intraday"] == []
    assert len(out["swing"]) == 1