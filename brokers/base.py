"""Broker abstraction for the StockAnalysis execution layer.

A Broker is anything that can take a validated order intent and return a
filled/rejected order record, plus report positions and account equity. The
deterministic :class:`paper_broker.PaperBroker` already satisfies this
interface structurally; live adapters (e.g. ``brokers.zerodha``) implement it
against a real account.

Every backend writes the same broker-neutral order/fill/position records to
:class:`trading_db.TradingDatabase`, so switching execution backends never
changes the ledger schema or the journal/validation layers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Broker(ABC):
    """Common execution interface shared by paper and live brokers.

    The method set intentionally mirrors ``paper_broker.PaperBroker`` so that
    the existing simulator can be used anywhere a ``Broker`` is expected
    (duck typing) without modification.
    """

    name: str = "broker"

    @abstractmethod
    def place_order(self, order: dict[str, Any],
                    client_order_id: str | None = None) -> dict:
        """Submit an order.

        Parameters
        ----------
        order:
            Required keys: ``symbol``, ``side`` (BUY/SELL), ``quantity``.
            Optional: ``order_type``, ``product``, ``price``, ``trigger_price``,
            ``target_price``, ``stop_loss``, ``strategy``, ``signal_id``.
        client_order_id:
            Idempotency key; passing the same key twice never double-fills.

        Returns
        -------
        The stored ``orders`` row (status FILLED / REJECTED / OPEN / PARTIAL).
        """

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """Return the current open positions (ledger rows)."""

    @abstractmethod
    def get_account(self) -> dict[str, float]:
        """Return ``equity`` / ``available_cash`` and persist a snapshot."""

    @abstractmethod
    def set_quote(self, symbol: str, price: float) -> None:
        """Provide an external quote.

        The paper broker consumes it for fills; live brokers ignore it because
        they read the real market.
        """

    def close(self) -> None:
        """Release any resources (e.g. websockets). No-op by default."""
