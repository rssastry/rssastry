from datetime import date

from decision_quality import build_decision_summary


def test_summary_aggregates_evidence_and_marks_fresh_data():
    summary = build_decision_summary(
        {
            "symbol": "TEST",
            "recommendation": "BUY",
            "confidence_score": 80,
            "ensemble_score": 70,
            "technical_score": 75,
            "fundamental_score": 65,
            "risk_level": "Medium",
            "indicators": {"data_as_of": "2026-09-11"},
        },
        today=date(2026, 9, 12),
    )

    assert summary["recommendation"] == "BUY"
    assert summary["conviction"] == 73
    assert summary["freshness"] == {
        "as_of": "2026-09-11",
        "age_days": 1,
        "label": "Fresh",
        "stale": False,
    }
    assert summary["blockers"] == ["AI recommendation is missing"]


def test_summary_downgrades_buy_with_gate_failures_and_deduplicates():
    summary = build_decision_summary(
        {
            "symbol": "TEST",
            "recommendation": "BUY",
            "eligibility_failures": ["Market regime unknown", "Market regime unknown"],
            "data_as_of": "2026-09-01",
        },
        today=date(2026, 9, 12),
    )

    assert summary["recommendation"] == "WATCHLIST"
    assert summary["blockers"] == ["Market regime unknown"]
    assert summary["freshness"]["label"] == "Stale"
    assert summary["freshness"]["stale"] is True


def test_summary_handles_missing_or_invalid_data_as_unknown():
    summary = build_decision_summary({"symbol": "TEST", "recommendation": "WATCHLIST", "data_as_of": "bad"})

    assert summary["conviction"] is None
    assert summary["freshness"]["label"] == "Unknown"
    assert summary["freshness"]["stale"] is True