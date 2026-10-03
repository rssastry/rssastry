"""Deterministic paper broker backed by TradingDatabase."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from trading_db import TradingDatabase, _symbol


class PaperBroker:
    """Long-only simulated broker with immediate market fills.

    Optional realistic-cost mode: ``slippage`` pushes the fill away from the
    quote (buy higher / sell lower) and ``stt_rate`` adds the India STT line
    to every fill's fee. Both default to 0.0 so pure price-level tests stay
    exact; the broker factory enables them via config for honest paper P&L.
    """

    name = "paper"

    def __init__(self, initial_cash: float, db: TradingDatabase | None = None,
                 transaction_cost: float = 0.001, fixed_fee: float = 0.0,
                 slippage: float = 0.0, stt_rate: float = 0.0):
        if float(initial_cash) <= 0:
            raise ValueError("initial_cash must be positive")
        if float(transaction_cost) < 0 or float(fixed_fee) < 0:
            raise ValueError("fees cannot be negative")
        if float(slippage) < 0 or float(slippage) >= 0.5:
            raise ValueError("slippage must be in [0, 0.5)")
        if float(stt_rate) < 0:
            raise ValueError("stt_rate cannot be negative")
        self.db = db or TradingDatabase()
        self._owns_db = db is None
        self.transaction_cost = float(transaction_cost)
        self.fixed_fee = float(fixed_fee)
        self.slippage = float(slippage)
        self.stt_rate = float(stt_rate)
        latest = self.db.conn.execute(
            "SELECT available_cash FROM account_snapshots WHERE broker = ? "
            "ORDER BY as_of DESC LIMIT 1", (self.name,)
        ).fetchone()
        self.cash = float(latest[0]) if latest and latest[0] is not None else float(initial_cash)
        self.quotes: dict[str, float] = {}

    def close(self) -> None:
        if self._owns_db:
            self.db.close()

    def __enter__(self) -> "PaperBroker":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def set_quote(self, symbol: str, price: float) -> None:
        if float(price) <= 0:
            raise ValueError("quote price must be positive")
        self.quotes[_symbol(symbol)] = float(price)

    def get_account(self) -> dict[str, float]:
        equity = self.cash
        for position in self.db.positions(self.name):
            price = position["last_price"] or position["average_price"]
            equity += int(position["quantity"]) * float(price)
        account = {
            "broker": self.name,
            "equity": round(equity, 2),
            "available_cash": round(self.cash, 2),
            "used_margin": 0.0,
        }
        self.db.save_account_snapshot(account)
        return account

    def get_positions(self) -> list[dict]:
        return self.db.positions(self.name)

    def place_order(self, order: dict[str, Any], client_order_id: str | None = None) -> dict:
        intent = self.db.create_order_intent({**order, "broker": self.name}, client_order_id)
        existing_order = self.db.conn.execute(
            "SELECT * FROM orders WHERE intent_id = ? ORDER BY created_at DESC LIMIT 1",
            (intent["id"],),
        ).fetchone()
        if existing_order and existing_order["status"] == "FILLED":
            return dict(existing_order)

        symbol = intent["symbol"]
        price = float(order.get("price") or self.quotes.get(symbol, 0))
        if price <= 0:
            return self._reject(intent, "no paper quote available")

        side = intent["side"]
        quantity = int(intent["quantity"])
        position = self._position(symbol, intent["product"])
        # Realistic fill: buys slip UP, sells slip DOWN from the quoted price.
        fill_price = price * (1 + self.slippage) if side == "BUY" else price * (1 - self.slippage)
        fee = fill_price * quantity * (self.transaction_cost + self.stt_rate) + self.fixed_fee
        gross = fill_price * quantity
        if side == "BUY" and gross + fee > self.cash + 1e-9:
            return self._reject(intent, "insufficient paper cash")
        if side == "SELL" and quantity > int(position["quantity"] if position else 0):
            return self._reject(intent, "insufficient paper position")

        broker_order_id = f"paper-{intent['client_order_id']}"
        stored_order = self.db.record_order(intent["id"], "OPEN", broker_order_id=broker_order_id)
        self.db.record_fill(
            stored_order["id"], quantity, fill_price, fees=fee,
            broker_trade_id=f"trade-{intent['client_order_id']}",
            raw={"broker": self.name, "fill_type": "immediate",
                 "quoted_price": round(price, 4),
                 "slippage": self.slippage, "stt_rate": self.stt_rate},
        )
        self.cash += (-gross - fee) if side == "BUY" else (gross - fee)
        self._update_position(intent, quantity, fill_price)
        self.get_account()
        return dict(self.db.conn.execute(
            "SELECT * FROM orders WHERE id = ?", (stored_order["id"],)
        ).fetchone())

    def _reject(self, intent: dict, reason: str) -> dict:
        order = self.db.record_order(
            intent["id"], "REJECTED", broker_order_id=f"paper-{intent['client_order_id']}",
            rejection_reason=reason,
        )
        self.db.add_audit_event("ORDER_REJECTED", {"reason": reason}, "order", order["id"])
        return order

    def _position(self, symbol: str, product: str) -> dict | None:
        return self.db.conn.execute(
            "SELECT * FROM positions WHERE symbol = ? AND product = ? AND broker = ?",
            (_symbol(symbol), product, self.name),
        ).fetchone()

    def _update_position(self, intent: dict, quantity: int, price: float) -> None:
        symbol = intent["symbol"]
        product = intent["product"]
        old = self._position(symbol, product)
        old_quantity = int(old["quantity"]) if old else 0
        old_average = float(old["average_price"]) if old else 0.0
        if intent["side"] == "BUY":
            new_quantity = old_quantity + quantity
            average = ((old_quantity * old_average) + (quantity * price)) / new_quantity
        else:
            new_quantity = old_quantity - quantity
            average = old_average if new_quantity else 0.0
        self.db.upsert_position({
            "symbol": symbol,
            "product": product,
            "quantity": new_quantity,
            "average_price": round(average, 4),
            "last_price": price,
            "unrealized_pnl": round((price - average) * new_quantity, 2),
            "broker": self.name,
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "raw": {"source": "paper_fill"},
        })
