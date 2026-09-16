"""Broker package — execution backends for the StockAnalysis trading loop.

Exposes :func:`get_broker` (factory) and the :class:`Broker` interface.

    from brokers import get_broker
    broker = get_broker()            # paper simulator (default)
    broker = get_broker("zerodha")   # live Kite Connect (opt-in)
"""
from brokers.base import Broker
from brokers.factory import get_broker

__all__ = ["get_broker", "Broker"]
