"""SQLite storage for paper and broker-connected trading workflows.

This module stores execution state separately from the decision journal. The
database is broker-neutral: a paper broker and the future Zerodha adapter can
write the same order, fill, position, account, and audit records.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from config import TRADING_DB_PATH


_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS order_intents (
    id TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    order_type TEXT NOT NULL DEFAULT 'MARKET',
    product TEXT NOT NULL DEFAULT 'CNC',
    price REAL,
    trigger_price REAL,
    target_price REAL,
    stop_loss REAL,
    strategy TEXT,
    signal_id TEXT,
    status TEXT NOT NULL DEFAULT 'CREATED',
    broker TEXT NOT NULL DEFAULT 'paper',
    broker_order_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intents_status ON order_intents(status);
CREATE INDEX IF NOT EXISTS idx_intents_symbol ON order_intents(symbol);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES order_intents(id),
    broker_order_id TEXT,
    status TEXT NOT NULL,
    filled_quantity INTEGER NOT NULL DEFAULT 0 CHECK (filled_quantity >= 0),
    average_price REAL,
    rejection_reason TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (intent_id, broker_order_id)
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_broker_id
    ON orders(broker_order_id) WHERE broker_order_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS fills (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    broker_trade_id TEXT UNIQUE,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    price REAL NOT NULL CHECK (price > 0),
    fees REAL NOT NULL DEFAULT 0,
    filled_at TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT NOT NULL,
    product TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    average_price REAL NOT NULL DEFAULT 0,
    last_price REAL,
    unrealized_pnl REAL,
    broker TEXT NOT NULL DEFAULT 'paper',
    as_of TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (symbol, product, broker)
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id TEXT PRIMARY KEY,
    broker TEXT NOT NULL,
    as_of TEXT NOT NULL,
    equity REAL,
    available_cash REAL,
    used_margin REAL,
    raw_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_account_as_of ON account_snapshots(broker, as_of);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    event_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_type, entity_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, default=str, sort_keys=True)


def _symbol(value: str) -> str:
    return str(value or "").strip().upper().replace(".NS", "")


class TradingDatabase:
    """Small transactional store for order lifecycle and reconciliation data."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or TRADING_DB_PATH
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "TradingDatabase":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def create_order_intent(self, order: dict[str, Any], client_order_id: str | None = None) -> dict:
        """Create an idempotent order intent and return the stored row."""
        symbol = _symbol(order.get("symbol"))
        side = str(order.get("side", "")).upper()
        quantity = int(order.get("quantity", 0))
        if not symbol or side not in {"BUY", "SELL"} or quantity <= 0:
            raise ValueError("symbol, side (BUY/SELL), and positive quantity are required")
        client_id = client_order_id or str(order.get("client_order_id") or uuid.uuid4().hex)
        existing = self.conn.execute(
            "SELECT * FROM order_intents WHERE client_order_id = ?", (client_id,)
        ).fetchone()
        if existing:
            return dict(existing)

        now = _now()
        intent_id = uuid.uuid4().hex
        values = {
            "id": intent_id,
            "client_order_id": client_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": str(order.get("order_type", "MARKET")).upper(),
            "product": str(order.get("product", "CNC")).upper(),
            "price": order.get("price"),
            "trigger_price": order.get("trigger_price"),
            "target_price": order.get("target_price"),
            "stop_loss": order.get("stop_loss"),
            "strategy": order.get("strategy"),
            "signal_id": order.get("signal_id"),
            "broker": str(order.get("broker", "paper")).lower(),
            "metadata_json": _json(order.get("metadata")),
            "created_at": now,
            "updated_at": now,
        }
        self.conn.execute(
            """INSERT INTO order_intents
               (id, client_order_id, symbol, side, quantity, order_type, product,
                price, trigger_price, target_price, stop_loss, strategy, signal_id,
                broker, metadata_json, created_at, updated_at)
               VALUES (:id, :client_order_id, :symbol, :side, :quantity, :order_type,
                :product, :price, :trigger_price, :target_price, :stop_loss,
                :strategy, :signal_id, :broker, :metadata_json, :created_at, :updated_at)""",
            values,
        )
        self._audit("ORDER_INTENT_CREATED", "order_intent", intent_id, values)
        self.conn.commit()
        return dict(self.conn.execute(
            "SELECT * FROM order_intents WHERE id = ?", (intent_id,)
        ).fetchone())

    def record_order(self, intent_id: str, status: str, broker_order_id: str | None = None,
                     filled_quantity: int = 0, average_price: float | None = None,
                     rejection_reason: str | None = None, raw: dict | None = None) -> dict:
        now = _now()
        order_id = uuid.uuid4().hex
        self.conn.execute(
            """INSERT INTO orders
               (id, intent_id, broker_order_id, status, filled_quantity, average_price,
                rejection_reason, raw_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (order_id, intent_id, broker_order_id, str(status).upper(), int(filled_quantity),
             average_price, rejection_reason, _json(raw), now, now),
        )
        self.conn.execute(
            "UPDATE order_intents SET status = ?, broker_order_id = ?, updated_at = ? WHERE id = ?",
            (str(status).upper(), broker_order_id, now, intent_id),
        )
        self._audit("ORDER_RECORDED", "order", order_id, {
            "intent_id": intent_id, "status": status, "broker_order_id": broker_order_id,
        })
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone())

    def record_fill(self, order_id: str, quantity: int, price: float,
                    fees: float = 0, broker_trade_id: str | None = None,
                    filled_at: str | None = None, raw: dict | None = None) -> dict:
        if int(quantity) <= 0 or float(price) <= 0:
            raise ValueError("fill quantity and price must be positive")
        if broker_trade_id:
            existing = self.conn.execute(
                "SELECT * FROM fills WHERE broker_trade_id = ?", (broker_trade_id,)
            ).fetchone()
            if existing:
                return dict(existing)
        fill_id = uuid.uuid4().hex
        self.conn.execute(
            """INSERT INTO fills
               (id, order_id, broker_trade_id, quantity, price, fees, filled_at, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (fill_id, order_id, broker_trade_id, int(quantity), float(price), float(fees),
             filled_at or _now(), _json(raw)),
        )
        self._audit("FILL_RECORDED", "order", order_id, {
            "quantity": quantity, "price": price, "broker_trade_id": broker_trade_id,
        })
        order_row = self.conn.execute(
            """SELECT o.intent_id, o.filled_quantity, i.quantity AS requested_quantity
               FROM orders o JOIN order_intents i ON i.id = o.intent_id
               WHERE o.id = ?""",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise ValueError(f"unknown order_id: {order_id}")
        filled_quantity = int(order_row["filled_quantity"]) + int(quantity)
        status = "FILLED" if filled_quantity >= int(order_row["requested_quantity"]) else "PARTIAL"
        now = _now()
        self.conn.execute(
            "UPDATE orders SET filled_quantity = ?, status = ?, updated_at = ? WHERE id = ?",
            (filled_quantity, status, now, order_id),
        )
        self.conn.execute(
            "UPDATE order_intents SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, order_row["intent_id"]),
        )
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM fills WHERE id = ?", (fill_id,)).fetchone())

    def upsert_position(self, position: dict[str, Any]) -> None:
        symbol = _symbol(position.get("symbol"))
        if not symbol:
            raise ValueError("position symbol is required")
        broker = str(position.get("broker", "paper")).lower()
        product = str(position.get("product", "CNC")).upper()
        as_of = position.get("as_of") or _now()
        self.conn.execute(
            """INSERT INTO positions
               (symbol, product, quantity, average_price, last_price, unrealized_pnl,
                broker, as_of, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol, product, broker) DO UPDATE SET
                 quantity=excluded.quantity, average_price=excluded.average_price,
                 last_price=excluded.last_price, unrealized_pnl=excluded.unrealized_pnl,
                 as_of=excluded.as_of, raw_json=excluded.raw_json""",
            (symbol, product, int(position.get("quantity", 0)),
             float(position.get("average_price", 0)), position.get("last_price"),
             position.get("unrealized_pnl"), broker, as_of, _json(position.get("raw"))),
        )
        self._audit("POSITION_RECONCILED", "position", f"{broker}:{product}:{symbol}", position)
        self.conn.commit()

    def save_account_snapshot(self, account: dict[str, Any]) -> str:
        snapshot_id = uuid.uuid4().hex
        self.conn.execute(
            """INSERT INTO account_snapshots
               (id, broker, as_of, equity, available_cash, used_margin, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (snapshot_id, str(account.get("broker", "paper")).lower(),
             account.get("as_of") or _now(), account.get("equity"),
             account.get("available_cash"), account.get("used_margin"),
             _json(account.get("raw"))),
        )
        self.conn.commit()
        return snapshot_id

    def add_audit_event(self, event_type: str, event: dict | None = None,
                        entity_type: str | None = None, entity_id: str | None = None) -> None:
        self._audit(event_type, entity_type, entity_id, event or {})
        self.conn.commit()

    def open_orders(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM orders WHERE status IN ('CREATED', 'SUBMITTED', 'OPEN', 'PARTIAL') "
            "ORDER BY created_at"
        ).fetchall()
        return [dict(row) for row in rows]

    def positions(self, broker: str = "paper") -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM positions WHERE broker = ? ORDER BY symbol", (broker.lower(),)
        ).fetchall()
        return [dict(row) for row in rows]

    def _audit(self, event_type: str, entity_type: str | None,
               entity_id: str | None, event: dict) -> None:
        self.conn.execute(
            """INSERT INTO audit_events
               (event_type, entity_type, entity_id, event_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (event_type, entity_type, entity_id, _json(event), _now()),
        )
