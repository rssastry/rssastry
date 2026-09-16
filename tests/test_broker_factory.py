"""Tests for the broker factory and the live-adapter safety contract."""

import pytest

from brokers import get_broker
from brokers.zerodha import BrokerNotConfigured, ZerodhaKiteBroker
from paper_broker import PaperBroker


def test_factory_defaults_to_paper(monkeypatch):
    monkeypatch.delenv("BROKER", raising=False)
    broker = get_broker()
    assert isinstance(broker, PaperBroker)
    assert broker.name == "paper"


def test_factory_paper_explicit():
    with get_broker("paper", initial_cash=5000) as broker:
        assert isinstance(broker, PaperBroker)
        assert broker.cash == 5000


def test_factory_rejects_unknown_broker():
    with pytest.raises(ValueError):
        get_broker("nonexistent_broker")


def test_zerodha_inert_without_credentials(monkeypatch):
    # Simulate an unconfigured environment: no KITE creds -> adapter must not
    # touch the network and must raise BrokerNotConfigured on use.
    monkeypatch.delenv("KITE_API_KEY", raising=False)
    monkeypatch.delenv("KITE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ZERODHA_KITE_API_KEY", raising=False)
    broker = ZerodhaKiteBroker()
    assert broker.name == "zerodha"
    with pytest.raises(BrokerNotConfigured):
        broker.get_positions()


def test_zerodha_symbol_mapping():
    assert ZerodhaKiteBroker._kite_symbol("RELIANCE.NS") == "RELIANCE"
    assert ZerodhaKiteBroker._kite_symbol("TCS") == "TCS"
