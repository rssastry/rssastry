"""Broker factory — resolve an execution backend from config / environment.

Usage::

    from brokers import get_broker
    broker = get_broker()                      # paper by default
    broker = get_broker("zerodha")             # live Kite Connect (opt-in)

The backend name comes from (in priority order) the explicit argument, the
``BROKER`` environment variable, or the ``config.BROKER`` default.
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from brokers.base import Broker
from config import BROKER, PAPER_INITIAL_CASH


def get_broker(name: str | None = None,
               initial_cash: float | None = None,
               **kwargs: Any) -> Broker:
    """Return a configured Broker instance.

    ``kwargs`` are forwarded to the backend constructor (e.g. ``db=`` for a
    shared TradingDatabase).
    """
    load_dotenv()
    resolved = (name or os.getenv("BROKER") or BROKER).strip().lower()

    if resolved in ("paper", "paperbroker", "paper_broker"):
        from paper_broker import PaperBroker
        cash = (initial_cash if initial_cash is not None
                else float(os.getenv("PAPER_INITIAL_CASH", PAPER_INITIAL_CASH)))
        return PaperBroker(cash, **kwargs)

    if resolved in ("zerodha", "kite", "kiteconnect"):
        from brokers.zerodha import ZerodhaKiteBroker
        return ZerodhaKiteBroker(**kwargs)

    raise ValueError(
        f"unknown broker '{resolved}'. Choose from: paper, zerodha."
    )


__all__ = ["get_broker", "Broker"]
