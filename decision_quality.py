"""Decision-quality summaries for scanner and AI candidates.

This module contains no UI or network code. It turns a candidate record into
an auditable snapshot that can be rendered by the dashboard or exported later.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional


def _number(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _freshness(as_of: Any, today: date) -> Dict[str, Any]:
    if not as_of:
        return {"as_of": None, "age_days": None, "label": "Unknown", "stale": True}
    try:
        parsed = datetime.fromisoformat(str(as_of)[:10]).date()
    except (TypeError, ValueError):
        return {"as_of": str(as_of), "age_days": None, "label": "Unknown", "stale": True}
    age_days = max(0, (today - parsed).days)
    if age_days <= 1:
        label = "Fresh"
    elif age_days <= 5:
        label = "Recent"
    else:
        label = "Stale"
    return {
        "as_of": parsed.isoformat(),
        "age_days": age_days,
        "label": label,
        "stale": age_days > 5,
    }


def build_decision_summary(candidate: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    """Build a compact, explainable view of one scanner/AI candidate."""
    today = today or date.today()
    indicators = candidate.get("indicators") or {}
    recommendation = str(candidate.get("recommendation") or candidate.get("selection_decision") or "UNKNOWN").upper()
    blockers: List[str] = list(candidate.get("eligibility_failures") or [])

    if recommendation == "BUY" and blockers:
        recommendation = "WATCHLIST"
    if not candidate.get("ai_recommendation") and recommendation == "BUY":
        blockers.append("AI recommendation is missing")

    confidence = _number(candidate.get("confidence_score") or candidate.get("confidence"))
    ensemble = _number(candidate.get("ensemble_score"))
    technical = _number(candidate.get("technical_score"))
    fundamental = _number(candidate.get("fundamental_score"))
    risk = str(candidate.get("risk_level") or "Unknown").title()
    as_of = candidate.get("data_as_of") or indicators.get("data_as_of")

    evidence = {
        "technical": technical,
        "fundamental": fundamental,
        "ensemble": ensemble,
        "confidence": confidence,
        "risk": risk,
    }
    available_scores = [value for value in (technical, fundamental, ensemble, confidence) if value is not None]
    conviction = int(sum(available_scores) / len(available_scores) + 0.5) if available_scores else None

    return {
        "symbol": candidate.get("symbol", ""),
        "recommendation": recommendation,
        "style": candidate.get("trading_style", ""),
        "conviction": conviction,
        "evidence": evidence,
        "risk": risk,
        "blockers": list(dict.fromkeys(blockers)),
        "freshness": _freshness(as_of, today),
        "market_regime": candidate.get("market_regime") or "Unknown",
        "earnings_risk": bool(candidate.get("earnings_risk") or candidate.get("earnings_event")),
    }