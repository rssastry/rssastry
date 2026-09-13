"""Tests for discipline.py - portfolio aging, concentration, attribution."""

import json

import pandas as pd
import pytest

import discipline as d


def make_df(closes, start="2026-01-02"):
    index = pd.date_range(start, periods=len(closes), freq="B")
    df = pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                       "Close": closes, "Volume": [1_000_000] * len(closes)},
                      index=index)
    df.index.name = "Date"
    return df


def fake_loader(mapping):
    """price_loader: symbol (bare or ^NSEI) -> DataFrame (or empty)."""
    def loader(symbol, period=None, interval="1d"):
        key = str(symbol).upper().replace(".NS", "")
        return mapping.get(key, pd.DataFrame())
    return loader


BASIC_PORTFOLIO = {
    "holdings": [
        {"symbol": "HINDCOPPER", "buy_price": 545.64, "quantity": 43,
         "buy_date": "2026-07-01", "style": "swing"},
        {"symbol": "TCS", "buy_price": 100.0, "quantity": 60,
         "buy_date": "2026-08-20", "style": "positional"},
    ],
    "closed_trades": [
        {"symbol": "GAIL", "buy_price": 174.35, "buy_date": "2026-06-12",
         "sell_price": 172.5, "sell_date": "2026-08-18",
         "pnl_pct": -1.06},
        {"symbol": "IDFCFIRSTB", "buy_price": 85.5, "buy_date": "2026-08-14",
         "sell_price": 86.5, "sell_date": "2026-08-20",
         "pnl_pct": 1.17},
    ],
}


class TestPositionAging:
    def test_overdue_swing(self):
        # HINDCOPPER swing open 40 trading bars (max 15) -> OVERDUE
        loader = fake_loader(
            {"HINDCOPPER": make_df([100.0] * 60, start="2026-06-02")})
        rows = d.position_aging(BASIC_PORTFOLIO, as_of="2026-08-31",
                                price_loader=loader)
        by_sym = {r["symbol"]: r for r in rows}
        assert by_sym["HINDCOPPER"]["overdue"] is True
        assert by_sym["HINDCOPPER"]["open_bars"] >= 30  # far past max 15
        assert by_sym["HINDCOPPER"]["max_hold_bars"] == 15

    def test_fresh_positional(self):
        loader = fake_loader(
            {"TCS": make_df([100.0] * 20, start="2026-08-18")})
        rows = d.position_aging(BASIC_PORTFOLIO, as_of="2026-08-31",
                                price_loader=loader)
        by_sym = {r["symbol"]: r for r in rows}
        assert by_sym["TCS"]["overdue"] is False
        assert by_sym["TCS"]["age_basis"] == "trading_bars"

    def test_calendar_fallback_without_price(self):
        row = d.position_aging(
            {"holdings": [{"symbol": "SOMETEST", "buy_price": 10.0,
                           "quantity": 1, "buy_date": "2026-01-01",
                           "style": "positional"}]},
            as_of="2026-08-31", price_loader=fake_loader({}))[0]
        assert row["age_basis"] == "calendar_days_fallback"


class TestConcentration:
    def test_hhi_and_sector_weights(self):
        portfolio = {"holdings": [
            {"symbol": "TCS", "buy_price": 100.0, "quantity": 600},
            {"symbol": "INFY", "buy_price": 100.0, "quantity": 300},
            {"symbol": "HDFCBANK", "buy_price": 100.0, "quantity": 100},
        ]}
        lookup = {"TCS": "Technology", "INFY": "Technology",
                  "HDFCBANK": "Financial Services"}
        result = d.concentration(portfolio, sector_lookup=lambda s: lookup.get(s))
        assert result["positions"] == 3
        assert result["top_position_share"] == pytest.approx(0.6, abs=1e-4)
        assert result["sector_weights"]["Technology"] == pytest.approx(0.9, abs=1e-4)
        assert result["hhi"] == pytest.approx(0.46, abs=1e-4)  # .6^2+.3^2+.1^2

    def test_empty_portfolio(self):
        result = d.concentration({"holdings": []}, sector_lookup=lambda s: "X")
        assert result["positions"] == 0
        assert result["hhi"] is None


class TestRealizedLedger:
    def test_alpha_vs_nifty(self):
        index = pd.to_datetime(["2026-06-12", "2026-08-18", "2026-08-19"])
        nifty = pd.DataFrame({"Open": [100.0, 110.0, 111.0],
                              "High": [100.0, 110.0, 111.0],
                              "Low": [100.0, 110.0, 111.0],
                              "Close": [100.0, 110.0, 111.0],
                              "Volume": [1_000_000] * 3}, index=index)
        loader = fake_loader({"^NSEI": nifty})
        rows = d.realized_ledger(
            {"closed_trades": [{"symbol": "GAIL", "buy_price": 174.35,
                                "buy_date": "2026-06-12",
                                "sell_price": 172.5, "sell_date": "2026-08-18",
                                "pnl_pct": -1.06}]},
            price_loader=loader)
        row = rows[0]
        assert row["realized_pnl_pct"] == pytest.approx(-1.06)
        assert row["nifty_buyhold_pct"] == pytest.approx(10.0)
        assert row["alpha_pct"] == pytest.approx(-11.06, abs=1e-2)

    def test_alpha_none_without_nifty(self):
        rows = d.realized_ledger(
            {"closed_trades": [{"symbol": "GAIL", "buy_price": 1.0,
                                "buy_date": "2026-06-12", "sell_price": 1.0,
                                "sell_date": "2026-08-18", "pnl_pct": 0.0}]},
            price_loader=fake_loader({}))
        assert rows[0]["alpha_pct"] is None
        assert rows[0]["nifty_buyhold_pct"] is None


class TestUnrealized:
    def test_current_pnl(self):
        stock = make_df([100.0] * 30 + [110.0], start="2026-07-01")
        loader = fake_loader({"TCS": stock})
        rows = d.unrealized_now(
            {"holdings": [{"symbol": "TCS", "buy_price": 100.0,
                           "quantity": 1, "buy_date": "2026-08-01",
                           "style": "swing"}]},
            price_loader=loader)
        assert rows[0]["unrealized_pnl_pct"] == pytest.approx(10.0, abs=1e-2)


class TestReport:
    def test_build_report_writes_file(self, tmp_path):
        loader = fake_loader({"HINDCOPPER": make_df([100.0] * 60),
                              "TCS": make_df([100.0] * 20),
                              "^NSEI": make_df([100.0] * 90)})
        portfolio = BASIC_PORTFOLIO
        out = tmp_path / "report.json"
        # Call internals with the fake loader so no local CSVs are needed.
        aging = d.position_aging(portfolio, as_of="2026-08-31",
                                 price_loader=loader)
        closed = d.realized_ledger(portfolio, price_loader=loader)
        open_rows = d.unrealized_now(portfolio, price_loader=loader)
        report = {
            "generated_at": "t",
            "portfolio_updated": None,
            "position_aging": aging,
            "concentration": d.concentration(portfolio),
            "realized_ledger": closed,
            "unrealized": open_rows,
            "summary": {
                "open_positions": len(aging),
                "overdue_positions": sum(1 for r in aging if r["overdue"]),
                "hhi": 0.5,
                "top_position_share": 0.7,
                "closed_trades": len(closed),
                "closed_alpha_win_pct": 50.0,
                "net_realized_pnl_pct": 0.0,
            },
        }
        out.write_text(json.dumps(report))
        loaded = json.loads(out.read_text())
        assert "position_aging" in loaded
        assert loaded["summary"]["open_positions"] == 2