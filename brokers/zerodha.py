"""Zerodha Kite Connect live execution adapter.

This is the bridge that turns the deterministic paper workflow into a *live*
algo-trading backend. It mirrors the :class:`paper_broker.PaperBroker`
interface and writes the same broker-neutral order/fill/position records to
:class:`trading_db.TradingDatabase`, so switching from paper to live never
changes the ledger, journal, or validation layers.

SAFETY — this adapter is intentionally inert until BOTH conditions hold:

* the optional ``kiteconnect`` package is installed, AND
* the ``KITE_API_KEY`` and ``KITE_ACCESS_TOKEN`` environment variables (or
  ``ZERODHA_KITE_API_KEY``) are set in ``.env``.

Until then every call raises :class:`BrokerNotConfigured` instead of
attempting a network request, so enabling ``BROKER=zerodha`` cannot place
real orders by accident. Always pair live execution with the
:class:`circuit_breaker.RiskCircuitBreaker` kill-switch.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

from brokers.base import Broker
from trading_db import TradingDatabase


class BrokerNotConfigured(RuntimeError):
    """Raised when a live broker is selected but its credentials are absent."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ZerodhaKiteBroker(Broker):
    """Long-only Kite Connect execution adapter (NSE equity, CNC delivery)."""

    name = "zerodha"
    EXCHANGE = "NSE"
    VARIETY = "regular"
    VALIDITY = "DAY"

    def __init__(self, db: TradingDatabase | None = None,
                 api_key: str | None = None,
                 access_token: str | None = None,
                 user_id: str | None = None):
        load_dotenv()
        self.api_key = api_key or os.getenv("KITE_API_KEY") or os.getenv("ZERODHA_KITE_API_KEY")
        self.access_token = access_token or os.getenv("KITE_ACCESS_TOKEN")
        self.user_id = user_id or os.getenv("KITE_USER_ID")
        self.db = db or TradingDatabase()
        self._owns_db = db is None
        self._kite = None
        self._instrument_map: dict[str, int] = {}
        if self.api_key and self.access_token:
            self._connect()

    # ── lifecycle ───────────────────────────────────────────────
    def _connect(self) -> None:
        try:
            from kiteconnect import KiteConnect  # optional dependency
        except ImportError as exc:  # pragma: no cover - env dependent
            raise BrokerNotConfigured(
                "kiteconnect is not installed. Add 'kiteconnect' to "
                "requirements.txt and pip install it before enabling "
                "the Zerodha broker."
            ) from exc
        kite = KiteConnect(api_key=self.api_key)
        kite.set_access_token(self.access_token)
        self._kite = kite

    def _require_kite(self):
        if self._kite is None:
            raise BrokerNotConfigured(
                "Zerodha broker not configured. Set KITE_API_KEY and "
                "KITE_ACCESS_TOKEN (or ZERODHA_KITE_API_KEY) in .env."
            )
        return self._kite

    def close(self) -> None:
        if self._owns_db:
            self.db.close()

    # ── symbol mapping ──────────────────────────────────────────
    @staticmethod
    def _kite_symbol(local_symbol: str) -> str:
        """Map a local 'RELIANCE.NS' symbol to a Kite NSE trading symbol."""
        return str(local_symbol or "").strip().upper().replace(".NS", "")

    def _instrument_token(self, trading_symbol: str) -> int:
        """Resolve a Kite instrument token, caching the instrument list."""
        if trading_symbol in self._instrument_map:
            return self._instrument_map[trading_symbol]
        kite = self._require_kite()
        instruments = kite.instruments(self.EXCHANGE)
        self._instrument_map = {
            row["tradingsymbol"]: int(row["instrument_token"]) for row in instruments
        }
        token = self._instrument_map.get(trading_symbol)
        if token is None:
            raise ValueError(f"symbol {trading_symbol} not found on Kite {self.EXCHANGE}")
        return token

    # ── Broker interface ────────────────────────────────────────
    def set_quote(self, symbol: str, price: float) -> None:
        # Live broker reads real market quotes; nothing to do.
        return None

    def place_order(self, order: dict[str, Any],
                    client_order_id: str | None = None) -> dict:
        kite = self._require_kite()
        symbol = self._kite_symbol(order.get("symbol"))
        if not symbol:
            raise ValueError("order.symbol is required")
        side = str(order.get("side", "")).upper()
        quantity = int(order.get("quantity", 0))
        if side not in ("BUY", "SELL") or quantity <= 0:
            raise ValueError("side (BUY/SELL) and positive quantity are required")

        intent = self.db.create_order_intent({**order, "broker": self.name}, client_order_id)
        existing = self.db.conn.execute(
            "SELECT * FROM orders WHERE intent_id = ? ORDER BY created_at DESC LIMIT 1",
            (intent["id"],),
        ).fetchone()
        if existing and existing["status"] in ("FILLED", "OPEN", "SUBMITTED", "PARTIAL"):
            return dict(existing)

        order_type = str(order.get("order_type", "MARKET")).upper()
        self._instrument_token(symbol)  # validates symbol before placing

        try:
            kite_order_id = kite.place_order(
                variety=self.VARIETY,
                exchange=self.EXCHANGE,
                tradingsymbol=symbol,
                transaction_type=side,
                quantity=quantity,
                product=str(order.get("product", "CNC")).upper(),
                order_type=order_type,
                price=float(order["price"]) if order.get("price") else None,
                trigger_price=float(order["trigger_price"]) if order.get("trigger_price") else None,
                validity=self.VALIDITY,
            )
        except Exception as exc:  # network / broker rejection
            order_row = self.db.record_order(
                intent["id"], "REJECTED",
                broker_order_id=f"zerodha-{intent['client_order_id']}",
                rejection_reason=str(exc)[:200],
            )
            self.db.add_audit_event("ORDER_REJECTED", {"reason": str(exc)[:200]},
                                    "order", order_row["id"])
            return order_row

        order_row = self.db.record_order(
            intent["id"], "SUBMITTED", broker_order_id=str(kite_order_id),
        )
        self.db.add_audit_event("ORDER_SUBMITTED",
                                {"broker_order_id": kite_order_id},
                                "order", order_row["id"])
        return order_row


    def sync_order(self, order_id: str) -> dict | None:
        """Reconcile a submitted order against Kite and record the fill.

        Idempotent: once a fill is recorded for a Kite trade id it is never
        re-applied. Returns the updated order row (or None if not found).
        """
        kite = self._require_kite()
        order_row = self.db.conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if order_row is None or order_row["status"] == "FILLED":
            return dict(order_row) if order_row else None
        broker_order_id = order_row["broker_order_id"]
        if not broker_order_id:
            return dict(order_row)

        orders = {o["order_id"]: o for o in kite.orders()}
        remote = orders.get(broker_order_id)
        if remote is None:
            return dict(order_row)

        status = str(remote.get("status", "")).upper()
        if status in ("COMPLETE", "FILLED") and remote.get("average_price"):
            self.db.record_fill(
                order_id,
                int(remote.get("filled_quantity", order_row["filled_quantity"])),
                float(remote["average_price"]),
                fees=0.0,
                broker_trade_id=f"kite-{broker_order_id}",
                raw={"broker": self.name, "source": "kite.sync"},
            )
        elif status in ("REJECTED", "CANCELLED", "EXPIRED"):
            self.db.conn.execute(
                "UPDATE orders SET status = ?, rejection_reason = ?, updated_at = ? "
                "WHERE id = ?",
                (status, remote.get("status_message", ""), _now(), order_id),
            )
            self.db.conn.commit()
        return dict(self.db.conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ).fetchone())

    def get_positions(self) -> list[dict]:
        kite = self._require_kite()
        rows = []
        for pos in kite.positions().get("net", []) or []:
            qty = int(pos.get("quantity", 0))
            if qty == 0:
                continue
            rows.append({
                "symbol": pos.get("tradingsymbol", ""),
                "product": pos.get("product", "CNC"),
                "quantity": qty,
                "average_price": float(pos.get("average_price", 0) or 0),
                "last_price": float(pos.get("last_price", 0) or 0),
                "unrealized_pnl": float(pos.get("unrealised", 0) or 0),
                "broker": self.name,
                "as_of": _now(),
            })
        return rows

    def get_account(self) -> dict[str, float]:
        kite = self._require_kite()
        margins = kite.margins() or {}
        try:
            equity_val = float(margins["equity"]["net"]) if margins.get("equity") else 0.0
            cash_val = float(margins["equity"]["available"]["cash"]) \
                if margins.get("equity", {}).get("available") else equity_val
        except (KeyError, TypeError, ValueError):
            equity_val = cash_val = 0.0
        account = {"broker": self.name, "equity": round(equity_val, 2),
                   "available_cash": round(cash_val, 2), "used_margin": 0.0}
        self.db.save_account_snapshot(account)
        return account


__all__ = ["ZerodhaKiteBroker", "BrokerNotConfigured"]

