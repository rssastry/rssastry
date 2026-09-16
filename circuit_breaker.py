"""Risk circuit breaker — the automation kill-switch for the trading loop.

Before every automated BUY the system asks the circuit breaker
:meth:`RiskCircuitBreaker.pre_trade_check`. If the portfolio is bleeding
beyond the configured floors (a bad single day, or a deep drawdown from
peak), fresh BUYs are suppressed and the state is persisted so the trip
survives restarts. This is the same fail-closed philosophy already used by
the market-regime filter — an unhealthy tape or an unhealthy account means
no new exposure.

State is kept in a JSON file (``config.CIRCUIT_BREAKER_STATE_PATH``, under
``data_cache/`` so it is gitignored) and is safe to share across the daily
scheduler jobs.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timezone

from config import CIRCUIT_BREAKER_STATE_PATH, MAX_DAILY_LOSS_PCT, MAX_DRAWDOWN_PCT


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


class RiskCircuitBreaker:
    """Tracks daily P&L and drawdown, and blocks new orders when tripped."""

    def __init__(self, state_path: str | None = None,
                 max_daily_loss_pct: float = MAX_DAILY_LOSS_PCT,
                 max_drawdown_pct: float = MAX_DRAWDOWN_PCT):
        self.state_path = state_path or CIRCUIT_BREAKER_STATE_PATH
        self.max_daily_loss_pct = abs(float(max_daily_loss_pct))
        self.max_drawdown_pct = abs(float(max_drawdown_pct))
        self._lock = threading.Lock()
        self._state = self._load()

    # ── persistence ─────────────────────────────────────────────
    def _load(self) -> dict:
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                state = json.load(fh)
            if isinstance(state, dict):
                return state
        except (OSError, ValueError):
            pass
        return self._blank()

    @staticmethod
    def _blank() -> dict:
        return {
            "date": _today(),
            "day_pnl_pct": 0.0,
            "peak_equity": None,
            "latest_equity": None,
            "drawdown_pct": 0.0,
            "tripped": False,
            "tripped_reason": "",
            "updated_at": _iso(),
        }

    def _save(self) -> None:
        self._state["updated_at"] = _iso()
        os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(self._state, fh, indent=2)

    # ── state updates ───────────────────────────────────────────
    def record_day_result(self, day_pnl_pct: float | None = None,
                          equity: float | None = None,
                          date_str: str | None = None) -> dict:
        """Feed the breaker one day's P&L and/or the account equity.

        ``day_pnl_pct`` is the portfolio's P&L for the current trading day
        (e.g. -1.2 for -1.2%). When the date rolls over, the daily counter
        resets. Returns the current status dict.
        """
        with self._lock:
            state = self._state
            today = date_str or _today()
            if state.get("date") != today:
                state["date"] = today
                state["day_pnl_pct"] = 0.0
                state["tripped"] = False
                state["tripped_reason"] = ""

            if day_pnl_pct is not None:
                state["day_pnl_pct"] = float(day_pnl_pct)

            if equity is not None:
                equity = float(equity)
                state["latest_equity"] = equity
                if state.get("peak_equity") is None or equity > state["peak_equity"]:
                    state["peak_equity"] = equity
                if state.get("peak_equity"):
                    state["drawdown_pct"] = (
                        (state["peak_equity"] - equity) / state["peak_equity"] * 100.0
                    )

            self._evaluate()
            self._save()
            return dict(state)

    def reset(self, date_str: str | None = None) -> dict:
        """Clear trip + daily counters (e.g. manual acknowledgment)."""
        with self._lock:
            self._state = self._blank()
            self._state["date"] = date_str or _today()
            self._save()
            return dict(self._state)

    # ── evaluation ──────────────────────────────────────────────
    def _evaluate(self) -> None:
        state = self._state
        reasons = []
        if state["day_pnl_pct"] <= -self.max_daily_loss_pct:
            reasons.append(
                f"daily loss {state['day_pnl_pct']:.2f}% breaches "
                f"-{self.max_daily_loss_pct:.1f}%"
            )
        if state["drawdown_pct"] >= self.max_drawdown_pct:
            reasons.append(
                f"drawdown {state['drawdown_pct']:.2f}% breaches "
                f"-{self.max_drawdown_pct:.1f}%"
            )
        state["tripped"] = bool(reasons)
        state["tripped_reason"] = " | ".join(reasons)

    # ── pre-trade gate ──────────────────────────────────────────
    def pre_trade_check(self) -> tuple[bool, str]:
        """Return ``(allowed, reason)`` for a new automated BUY.

        Re-evaluates from persisted state so a trip that happened in another
        process still blocks orders here.
        """
        with self._lock:
            self._evaluate()
            self._save()
            if self._state["tripped"]:
                return False, self._state["tripped_reason"]
            return True, "circuit breaker open"

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)


__all__ = ["RiskCircuitBreaker"]
