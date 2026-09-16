"""Focused tests for the broker-neutral trading database."""

import pytest

from trading_db import TradingDatabase


def order(**overrides):
    value = {
        "symbol": "RELIANCE.NS",
        "side": "BUY",
        "quantity": 10,
        "strategy": "swing",
        "stop_loss": 1400.0,
        "metadata": {"signal_score": 72},
    }
    value.update(overrides)
    return value


def test_order_intent_is_idempotent():
    with TradingDatabase(":memory:") as db:
        first = db.create_order_intent(order(), client_order_id="signal-123")
        retry = db.create_order_intent(order(quantity=99), client_order_id="signal-123")

        assert retry["id"] == first["id"]
        assert retry["quantity"] == 10
        assert db.conn.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0] == 1


def test_order_fill_and_audit_are_recorded():
    with TradingDatabase(":memory:") as db:
        intent = db.create_order_intent(order(), client_order_id="signal-124")
        broker_order = db.record_order(intent["id"], "OPEN", broker_order_id="paper-1")
        fill = db.record_fill(broker_order["id"], 10, 1500.0, fees=2.5,
                              broker_trade_id="trade-1")
        retry = db.record_fill(broker_order["id"], 10, 1500.0,
                       broker_trade_id="trade-1")

        assert fill["quantity"] == 10
        assert retry["id"] == fill["id"]
        assert db.open_orders() == []
        assert db.conn.execute("SELECT status FROM orders").fetchone()[0] == "FILLED"
        count = db.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        assert count == 3


def test_position_upsert_and_account_snapshot():
    with TradingDatabase(":memory:") as db:
        db.upsert_position({"symbol": "TCS.NS", "quantity": 5,
                            "average_price": 3500, "last_price": 3520})
        db.upsert_position({"symbol": "TCS", "quantity": 7,
                            "average_price": 3510, "last_price": 3530})
        db.save_account_snapshot({"equity": 100000, "available_cash": 80000})

        positions = db.positions()
        assert len(positions) == 1
        assert positions[0]["quantity"] == 7
        assert db.conn.execute("SELECT COUNT(*) FROM account_snapshots").fetchone()[0] == 1


def test_invalid_order_is_rejected():
    with TradingDatabase(":memory:") as db:
        with pytest.raises(ValueError):
            db.create_order_intent(order(side="HOLD"))
        with pytest.raises(ValueError):
            db.create_order_intent(order(quantity=0))
