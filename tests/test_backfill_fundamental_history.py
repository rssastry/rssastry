"""Tests for the free historical-fundamentals backfill and its loader wiring.

All tests are network-free: they build synthetic yfinance-style statement
frames and exercise the pure mapping / persistence / loader functions.
"""
import json
from datetime import date

import pandas as pd
import pytest

import backfill_fundamental_history as backfill
import fundamental_snapshots as snapshots
from fundamental_snapshots import apply_price_valuation, load_snapshot_as_of


def make_frames(columns, ni=None, ebit=None, revenue=None, equity=None,
                debt=None, assets=None, liab=None, shares=None, fcf=None,
                capex=None):
    """Synthetic yfinance statement frames (rows x fiscal-year columns).

    ``columns`` are fiscal-year-end labels (e.g. "2024-03-31"); they become
    Timestamp columns exactly like yfinance's statements.
    """
    columns = [pd.Timestamp(c) for c in columns]
    n = len(columns)
    ni = ni or [100.0 + 10.0 * i for i in range(n)]
    ebit = ebit or [50.0 + 2.5 * i for i in range(n)]
    revenue = revenue or [900.0 + 50.0 * i for i in range(n)]
    equity = equity or [350.0 + 25.0 * i for i in range(n)]
    debt = debt or [100.0 - 5.0 * i for i in range(n)]
    assets = assets or [800.0 + 50.0 * i for i in range(n)]
    liab = liab or [140.0 + 5.0 * i for i in range(n)]
    shares = shares or [10.0] * n
    fcf = fcf or [40.0 + 5.0 * i for i in range(n)]
    capex = capex or [-40.0 - 2.0 * i for i in range(n)]

    income = pd.DataFrame(
        index=["Net Income", "EBIT", "Operating Income", "Total Revenue",
               "Pretax Income", "Tax Provision"],
        columns=pd.Index(columns, name="period_end"),
        data=[ni,
              ebit,
              ebit,
              revenue,
              [v + 20.0 for v in ni],
              [20.0] * n],
    )
    balance = pd.DataFrame(
        index=["Stockholders Equity", "Total Debt", "Total Assets",
               "Current Liabilities", "Ordinary Shares Number"],
        columns=pd.Index(columns, name="period_end"),
        data=[equity, debt, assets, liab, shares],
    )
    cashflow = pd.DataFrame(
        index=["Free Cash Flow", "Capital Expenditure", "Operating Cash Flow"],
        columns=pd.Index(columns, name="period_end"),
        data=[fcf, capex, [v * 1.3 for v in fcf]],
    )
    return income, balance, cashflow


def test_build_period_values_reconstructs_scoring_fields():
    income, balance, cashflow = make_frames(
        ["2024-03-31", "2023-03-31"],
        ni=[110.0, 100.0], ebit=[60.0, 50.0], revenue=[1000.0, 900.0],
        equity=[400.0, 350.0], debt=[80.0, 100.0], assets=[900.0, 800.0],
        liab=[150.0, 140.0], shares=[10.0, 10.0], fcf=[55.0, 40.0],
        capex=[-45.0, -40.0],
    )
    values = backfill.build_period_values(
        income, balance, cashflow, pd.Timestamp("2024-03-31"),
        prev_net_income=100.0)

    assert values["returnOnEquity"] == pytest.approx(110.0 / 400.0)
    assert values["returnOnCapitalEmployed"] == pytest.approx(60.0 / 750.0)
    assert values["debtToEquity"] == pytest.approx(0.2)
    assert values["profitMargins"] == pytest.approx(0.11)
    assert values["operatingMargins"] == pytest.approx(0.06)
    assert values["freeCashflow"] == pytest.approx(55.0)
    assert values["earningsGrowth"] == pytest.approx(0.1)
    assert values["payoutRatio"] == pytest.approx(1.0 - 45.0 / 110.0)
    assert values["capitalExpenditures"] == pytest.approx(45.0)
    assert values["netIncome"] == pytest.approx(110.0)
    assert values["eps"] == pytest.approx(11.0)
    assert values["bvps"] == pytest.approx(40.0)


def test_build_records_skip_latest_and_filing_buffer():
    income, balance, cashflow = make_frames(
        ["2023-03-31", "2024-03-31", "2025-03-31", "2026-03-31", "2027-03-31"])
    records = backfill.build_records(
        income, balance, cashflow, "TEST",
        buffer_days=120, skip_latest=True,
        today=date(2026, 9, 8))

    period_ends = [r["period_end"] for r in records]
    # 2027 is excluded by the availability gate; 2026 (newest eligible) is
    # excluded by skip_latest.
    assert period_ends == ["2023-03-31", "2024-03-31", "2025-03-31"]
    assert all(r["source"] == backfill.SOURCE for r in records)
    assert records[0]["as_of"] == "2023-07-29"
    assert records[1]["as_of"] == "2024-07-29"
    assert records[2]["as_of"] == "2025-07-29"
    # growth in FY2024 vs FY2023 is present; FY2023 (no predecessor) is not.
    assert "earningsGrowth" not in records[0]["values"]
    assert records[1]["values"]["earningsGrowth"] == pytest.approx(0.1)


def test_write_snapshots_idempotent_and_force(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setattr(backfill, "SNAPSHOT_DIR", str(tmp_path))
    records = [
        {"as_of": "2024-07-29", "symbol": "TEST", "source": backfill.SOURCE,
         "period_end": "2024-03-31", "values": {"returnOnEquity": 0.27}},
        {"as_of": "2025-07-29", "symbol": "TEST", "source": backfill.SOURCE,
         "period_end": "2025-03-31", "values": {"returnOnEquity": 0.29}},
    ]
    first = backfill.write_snapshots("TEST.NS", list(records))
    assert first["rows_written"] == 2
    assert first["rows_total"] == 2

    # plain re-run: verbatim rows already stored → nothing written
    second = backfill.write_snapshots("TEST.NS", list(records))
    assert second["rows_written"] == 0
    assert second["rows_total"] == 2

    # forced re-run with identical content also writes nothing
    forced = backfill.write_snapshots("TEST.NS", list(records), force=True)
    assert forced["rows_written"] == 0
    assert forced["rows_total"] == 2

    # forced re-run after a mapping change rewrites the changed row only
    renamed = [dict(rec) for rec in records]
    renamed[0]["period_end"] = "2024-09-30"
    forced2 = backfill.write_snapshots("TEST.NS", renamed, force=True)
    assert forced2["rows_written"] == 1
    assert forced2["rows_total"] == 2

    stored = backfill.load_snapshots("TEST")
    assert len(stored) == 2
    assert any(r.get("period_end") == "2024-09-30" for r in stored)


def test_load_snapshot_as_of_surfaces_source_and_period_end(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", str(tmp_path))
    path = tmp_path / "TEST.jsonl"
    path.write_text(json.dumps({
        "as_of": "2024-07-29", "symbol": "TEST",
        "source": backfill.SOURCE, "period_end": "2024-03-31",
        "values": {"eps": 11.0, "bvps": 40.0, "returnOnEquity": 0.27},
    }), encoding="utf-8")

    fund = load_snapshot_as_of("TEST.NS", "2025-01-15")
    assert fund["snapshot_source"] == backfill.SOURCE
    assert fund["period_end"] == "2024-03-31"
    assert fund["eps"] == 11.0


def test_apply_price_valuation_only_for_statement_snapshots():
    # statement-derived snapshot: P/E and P/B derived from the signal close
    fund = {"eps": 11.0, "bvps": 40.0, "snapshot_source": backfill.SOURCE}
    apply_price_valuation(fund, 220)
    assert fund["trailingPE"] == pytest.approx(20.0)
    assert fund["priceToBook"] == pytest.approx(5.5)

    # loss year (eps <= 0) must not produce a bogus negative P/E
    loss = {"eps": -4.0, "bvps": 40.0, "snapshot_source": backfill.SOURCE}
    apply_price_valuation(loss, 220)
    assert "trailingPE" not in loss

    # live info snapshots already carry provider ratios — never overridden
    info = {"trailingPE": 25.0, "priceToBook": 6.0,
            "snapshot_source": "yfinance.info"}
    apply_price_valuation(info, 220)
    assert info["trailingPE"] == 25.0
    assert info["priceToBook"] == 6.0

    # garbage price is ignored
    junk = {"eps": 11.0, "snapshot_source": backfill.SOURCE}
    apply_price_valuation(junk, None)
    assert "trailingPE" not in junk


def test_snapshot_coverage_counts_backfill_source(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", str(tmp_path))
    path = tmp_path / "TEST.jsonl"
    path.write_text("\n".join([
        json.dumps({"as_of": "2024-07-29", "symbol": "TEST",
                    "source": backfill.SOURCE, "period_end": "2024-03-31",
                    "values": {"returnOnEquity": 0.27}}),
        json.dumps({"as_of": "2026-09-06", "symbol": "TEST",
                    "source": "yfinance.info",
                    "values": {"forwardPE": 20.0}}),
    ]), encoding="utf-8")

    coverage = snapshots.snapshot_coverage(["TEST.NS"])
    assert coverage["snapshots_by_source"] == {
        backfill.SOURCE: 1, "yfinance.info": 1}
    assert coverage["backfill_period_end_min"] == "2024-03-31"
    assert coverage["backfill_period_end_max"] == "2024-03-31"
def test_backfill_symbol_skips_index_series():
    summary = backfill.backfill_symbol("^NSEI")
    assert summary["error"] == "index series has no annual fundamentals; skipped"
    assert summary["periods"] == []


def test_backfill_symbol_flags_provider_gap(monkeypatch):
    class EmptyTicker:
        income_stmt = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = pd.DataFrame()

    monkeypatch.setattr(backfill.yf, "Ticker", lambda symbol: EmptyTicker())
    summary = backfill.backfill_symbol("MYSTERY.NS")
    assert summary.get("no_statement_data") is True
    assert summary["periods"] == []
    assert summary["wrote"] == 0


def test_backfill_symbols_classifies_no_data(monkeypatch):
    class EmptyTicker:
        income_stmt = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = pd.DataFrame()

    monkeypatch.setattr(backfill.yf, "Ticker", lambda symbol: EmptyTicker())
    result = backfill.backfill_symbols(["MYSTERY.NS", "OTHER.NS"])
    assert result["symbols_without_statement_data"] == 2
    assert result["symbols_written"] == 0
    assert result["symbols_failed"] == 0