"""Tests for market_breadth.py - market context layer."""

import json

import numpy as np
import pandas as pd
import pytest

import market_breadth as mb


def write_price_csv(dir_path, symbol, close_series, start="2025-01-02"):
    """Write a yfinance-format CSV with a synthetic close path."""
    index = pd.date_range(start, periods=len(close_series), freq="B")
    df = pd.DataFrame({"Date": index.strftime("%Y-%m-%d"),
                       "Adj Close": close_series,
                       "Close": close_series,
                       "High": [v * 1.02 for v in close_series],
                       "Low": [v * 0.98 for v in close_series],
                       "Open": [v * 1.01 for v in close_series],
                       "Volume": [1_000_000] * len(close_series)})
    df.to_csv(dir_path / f"{symbol}.csv", index=False)


@pytest.fixture
def price_dir(monkeypatch, tmp_path):
    # ~130 trading days: >60 bars available, EMA21/50 well-defined
    n = 130
    riser = 100 + np.linspace(0, 50, n)           # ends ~150 > EMA
    faller = 100 - np.linspace(0, 50, n)          # ends ~50 < EMA
    # flat for most of the series, then a firm 5-bar push higher -> last close
    # sits ABOVE its EMA21/50 (a strict '>' comparison needs the pop)
    ramp = list(np.full(n - 5, 100.0)) + [101.5, 102.0, 102.5, 103.0, 103.5]
    write_price_csv(tmp_path, "RISER", list(riser))
    write_price_csv(tmp_path, "FALLER", list(faller))
    write_price_csv(tmp_path, "FLAT", ramp)
    write_price_csv(tmp_path, "^NSEI", list(np.full(n, 120.0)))
    monkeypatch.setattr("price_store.PRICE_DIR", str(tmp_path))
    return tmp_path


class TestBreadth:
    def test_breadth_counts(self, price_dir):
        result = mb.market_breadth(symbols=["RISER", "FALLER", "FLAT"])
        assert result["universe_scanned"] == 3
        # RISER & FLAT above EMA21/50; FALLER below
        assert result["breadth_pct_above_ema21"] == pytest.approx(66.7, abs=0.1)
        assert result["breadth_pct_above_ema50"] == pytest.approx(66.7, abs=0.1)

    def test_advance_decline(self, price_dir):
        result = mb.market_breadth(symbols=["RISER", "FALLER", "FLAT"])
        assert result["advancers_5d"] == 2   # RISER + FLAT
        assert result["decliners_5d"] == 1
        assert result["advance_ratio_5d"] == pytest.approx(2 / 3, abs=0.001)

    def test_distance_from_52w_high(self, price_dir):
        riser_row = mb._one_symbol_stats("RISER")
        faller_row = mb._one_symbol_stats("FALLER")
        # RISER closes just under its own 52w high (High == 1.02 * Close)
        assert riser_row["pct_from_52w_high"] > -3.0
        assert faller_row["pct_from_52w_high"] < -30   # far below


    def test_skips_short_symbol(self, price_dir):
        write_price_csv(price_dir, "SHORT", list(np.linspace(100, 99, 30)))
        assert mb._one_symbol_stats("SHORT") is None


class TestVolatilityRegime:
    def test_low_volatility(self, tmp_path, monkeypatch):
        # wild for the first 230 bars, then quiet. Current 20d vol is far
        # below its own history -> low percentile -> 'low'.
        wild = list(np.full(230, 100.0) + np.sin(np.linspace(0, 140, 230)) * 8.0)
        series = wild + list(np.linspace(100, 101, 30))
        write_price_csv(tmp_path, "NIFTY_LOW", series, start="2024-01-02")
        monkeypatch.setattr("price_store.PRICE_DIR", str(tmp_path))
        result = mb.volatility_regime("NIFTY_LOW")
        assert result["regime"] == "low"

    def test_high_volatility(self, tmp_path, monkeypatch):
        # quiet for the first 230 bars, then wild -> high percentile.
        quiet = list(np.full(230, 100.0))
        wild = list(np.linspace(100, 110, 30) + np.sin(np.linspace(0, 30, 30)) * 8.0)
        write_price_csv(tmp_path, "NIFTY_HIGH", quiet + wild,
                        start="2024-01-02")
        monkeypatch.setattr("price_store.PRICE_DIR", str(tmp_path))
        result = mb.volatility_regime("NIFTY_HIGH")
        assert result["regime"] == "high"

    def test_unknown_short_history(self, tmp_path, monkeypatch):
        write_price_csv(tmp_path, "NIFTY_SHORT", list(np.linspace(100, 101, 10)))
        monkeypatch.setattr("price_store.PRICE_DIR", str(tmp_path))
        result = mb.volatility_regime("NIFTY_SHORT")
        assert result["regime"] == "unknown"


class TestSectorAndSnapshot:
    def test_sector_breadth_uses_latest_snapshot(self, price_dir, monkeypatch,
                                                tmp_path):
        snap_dir = tmp_path / "fundamental_snapshots"
        snap_dir.mkdir()
        for symbol, sector in (("RISER", "Technology"), ("FALLER", "Energy"),
                               ("FLAT", "Technology")):
            (snap_dir / f"{symbol}.jsonl").write_text(
                json.dumps({"as_of": "2026-09-01", "symbol": symbol,
                            "source": "yfinance.info",
                            "values": {"sector": sector}}) + "\n")
        monkeypatch.setattr(mb, "SNAPSHOT_DIR", str(snap_dir))
        result = mb.sector_breadth()
        # RISER & FLAT are both above their EMA50 in this synthetic universe
        assert result["Technology"]["scanned"] == 2
        assert result["Technology"]["breadth_pct_above_ema50"] == pytest.approx(100.0)
        assert result["Energy"]["breadth_pct_above_ema50"] == 0.0

    def test_build_market_snapshot_writes_file(self, price_dir, tmp_path):
        out = tmp_path / "market_snapshot.json"
        snapshot = mb.build_market_snapshot(out=str(out),
                                            symbols=["RISER", "FALLER"])
        assert snapshot["breadth"]["universe_scanned"] == 2
        assert snapshot["volatility_regime"]["regime"] in ("low", "normal",
                                                           "high", "unknown")
        assert "relative_movers" in snapshot
        leaders = sorted(snapshot["relative_movers"]["leaders"],
                         key=lambda r: r["ret_5d_pct"], reverse=True)
        assert leaders[0]["symbol"] == "RISER"
        assert out.exists()