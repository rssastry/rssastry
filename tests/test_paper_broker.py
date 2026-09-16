"""Tests for simulated execution and account state."""

import pytest

from paper_broker import PaperBroker
from trading_db import TradingDatabase


def test_paper_buy_sell_and_weighted_position():
    with TradingDatabase(":memory:") as db:
        with PaperBroker(10000, db=db, transaction_cost=0) as broker:
            broker.set_quote("TCS.NS", 100)
            first = broker.place_order({"symbol": "TCS", "side": "BUY", "quantity": 20}, "buy-1")
            broker.set_quote("TCS", 120)
            second = broker.place_order({"symbol": "TCS.NS", "side": "BUY", "quantity": 10}, "buy-2")

            assert first["status"] == "FILLED"
            assert second["status"] == "FILLED"
            position = broker.get_positions()[0]
            assert position["quantity"] == 30
            assert position["average_price"] == pytest.approx(106.6667, abs=0.001)
            assert broker.get_account()["available_cash"] == 6800

            sold = broker.place_order({"symbol": "TCS", "side": "SELL", "quantity": 30}, "sell-1")
            assert sold["status"] == "FILLED"
            assert broker.get_positions()[0]["quantity"] == 0


def test_paper_broker_rejects_unsafe_orders():
    with TradingDatabase(":memory:") as db:
        with PaperBroker(1000, db=db, transaction_cost=0) as broker:
            broker.set_quote("INFY", 100)
            cash_order = broker.place_order({"symbol": "INFY", "side": "BUY", "quantity": 11}, "cash-1")
            sell_order = broker.place_order({"symbol": "INFY", "side": "SELL", "quantity": 1}, "sell-1")

            assert cash_order["status"] == "REJECTED"
            assert cash_order["rejection_reason"] == "insufficient paper cash"
            assert sell_order["status"] == "REJECTED"
            assert sell_order["rejection_reason"] == "insufficient paper position"


def test_paper_order_retry_is_idempotent():
    with TradingDatabase(":memory:") as db:
        with PaperBroker(1000, db=db, transaction_cost=0) as broker:
            broker.set_quote("RELIANCE", 100)
            first = broker.place_order({"symbol": "RELIANCE", "side": "BUY", "quantity": 2}, "retry-1")
            retry = broker.place_order({"symbol": "RELIANCE", "side": "BUY", "quantity": 2}, "retry-1")

            assert retry["id"] == first["id"]
            assert broker.get_account()["available_cash"] == 800
            assert broker.get_positions()[0]["quantity"] == 2
