import json

import fundamental_snapshots as snapshots
from screener import NSE_STOCKS


def test_provider_aliases_preserve_local_symbol_identity():
    assert snapshots.resolve_provider_ticker("TATAMOTORS.NS") == "TMPV.NS"
    assert snapshots.resolve_provider_ticker("ADANITRANS") == "ADANIENSOL.NS"
    assert snapshots.resolve_provider_ticker("ZOMATO.NS") == "ETERNAL.NS"
    assert snapshots.resolve_provider_ticker("RELIANCE.NS") == "RELIANCE.NS"


def test_ltim_remains_explicitly_unmapped():
    """Do not silently substitute a different company for unavailable LTIM data."""
    assert snapshots.resolve_provider_ticker("LTIM.NS") == "LTIM.NS"


def test_unavailable_ltim_is_excluded_from_active_universe():
    assert "LTIM.NS" not in NSE_STOCKS


def test_load_snapshot_as_of_never_looks_ahead(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", str(tmp_path))
    path = tmp_path / "TEST.jsonl"
    records = [
        {"as_of": "2024-01-01", "symbol": "TEST", "values": {"forwardPE": 20}},
        {"as_of": "2024-02-01", "symbol": "TEST", "values": {"forwardPE": 30}},
    ]
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    before_first = snapshots.load_snapshot_as_of("TEST.NS", "2023-12-31")
    first = snapshots.load_snapshot_as_of("TEST.NS", "2024-01-15")
    second = snapshots.load_snapshot_as_of("TEST.NS", "2024-02-15")

    assert before_first is None
    assert first["forwardPE"] == 20
    assert first["snapshot_as_of"] == "2024-01-01"
    assert second["forwardPE"] == 30
    assert second["snapshot_as_of"] == "2024-02-01"


def test_snapshot_coverage_reports_missing_and_dates(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", str(tmp_path))
    path = tmp_path / "TEST.jsonl"
    path.write_text(
        json.dumps({
            "as_of": "2026-09-06",
            "symbol": "TEST",
            "values": {"forwardPE": 20},
        }),
        encoding="utf-8",
    )

    coverage = snapshots.snapshot_coverage(["TEST.NS", "MISSING.NS"])

    assert coverage["symbols_requested"] == 2
    assert coverage["symbols_with_snapshots"] == 1
    assert coverage["coverage_pct"] == 50.0
    assert coverage["missing_symbols"] == ["MISSING.NS"]
    assert coverage["oldest_snapshot"] == "2026-09-06"
    assert coverage["newest_snapshot"] == "2026-09-06"


# ── NSE debtToEquity unit artifact + best-available merge ──────────
def _write_records(tmp_path, monkeypatch, symbol, records):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", str(tmp_path))
    path = tmp_path / f"{symbol.replace('.NS', '')}.jsonl"
    path.write_text("\n".join(json.dumps(rec) for rec in records), encoding="utf-8")
    return path


def test_normalize_debt_equity_unit_artifact():
    """yfinance.info inflated NSE D/E (~70-800x) is scaled to a plausible ratio."""
    assert snapshots.normalize_debt_equity(None) is None
    assert snapshots.normalize_debt_equity("oops") is None
    assert snapshots.normalize_debt_equity(0.5) == 0.5      # plausible, unchanged
    assert snapshots.normalize_debt_equity(3.293) == 3.293  # below threshold, unchanged
    assert snapshots.normalize_debt_equity(10.907) == 0.10907
    assert snapshots.normalize_debt_equity(82.829) == 0.82829
    assert snapshots.normalize_debt_equity(97.64) == 0.9764
    # an artifact that would still read implausibly after scaling is NOT hidden
    assert snapshots.normalize_debt_equity(900.0) == 900.0


def test_load_snapshot_as_of_normalizes_info_debt(tmp_path, monkeypatch):
    _write_records(tmp_path, monkeypatch, "DABUR.NS", [{
        "as_of": "2026-09-16", "symbol": "DABUR",
        "source": "yfinance.info",
        "values": {"debtToEquity": 10.907, "trailingPE": 34.4},
    }])
    values = snapshots.load_snapshot_as_of("DABUR.NS", "2026-09-16")
    assert values["debtToEquity"] == 0.10907
    assert values["trailingPE"] == 34.4


def test_merge_prefers_statements_debt_and_keeps_live_valuation(tmp_path, monkeypatch):
    _write_records(tmp_path, monkeypatch, "DABUR.NS", [
        {"as_of": "2025-07-29", "symbol": "DABUR",
         "source": "yfinance.statements",
         "values": {"returnOnEquity": 0.163659, "returnOnCapitalEmployed": 0.158128,
                    "debtToEquity": 0.087965, "freeCashflow": 14172100000.0,
                    "profitMargins": 0.142551}},
        {"as_of": "2026-09-16", "symbol": "DABUR",
         "source": "yfinance.info",
         "values": {"returnOnEquity": None, "returnOnCapitalEmployed": None,
                    "debtToEquity": 10.907, "freeCashflow": None,
                    "trailingPE": 34.4, "forwardPE": 28.9,
                    "priceToBook": 5.93, "sector": "Consumer Defensive",
                    "profitMargins": 0.14551}},
    ])

    merged = snapshots.merge_fundamental_snapshots(
        "DABUR.NS", {"debtToEquity": 10.907, "trailingPE": 34.4,
                     "sector": "Consumer Defensive"})

    # unit-correct statements D/E always wins over the broken live-info value
    assert merged["debtToEquity"] == 0.087965
    # fill-in of quality metrics live info drops
    assert merged["returnOnEquity"] == 0.163659
    assert merged["returnOnCapitalEmployed"] == 0.158128
    assert merged["freeCashflow"] == 14172100000.0
    # fresh live valuation / profile is preserved
    assert merged["trailingPE"] == 34.4
    assert merged["forwardPE"] == 28.9
    assert merged["sector"] == "Consumer Defensive"
    assert merged["data_quality"] == "statements+live"


def test_merge_live_only_normalizes_info_debt(tmp_path, monkeypatch):
    _write_records(tmp_path, monkeypatch, "TEST.NS", [{
        "as_of": "2026-09-16", "symbol": "TEST", "source": "yfinance.info",
        "values": {"debtToEquity": 82.829, "trailingPE": 357.8},
    }])
    merged = snapshots.merge_fundamental_snapshots("TEST.NS")
    assert merged["debtToEquity"] == 0.82829
    assert merged["trailingPE"] == 357.8
    assert merged["data_quality"] == "live_info"


def test_merge_uses_statements_when_no_live_dict(tmp_path, monkeypatch):
    _write_records(tmp_path, monkeypatch, "TEST.NS", [
        {"as_of": "2025-07-29", "symbol": "TEST", "source": "yfinance.statements",
         "values": {"returnOnEquity": 0.51, "debtToEquity": 0.099,
                    "freeCashflow": 32000000000.0}},
    ])
    merged = snapshots.merge_fundamental_snapshots("TEST.NS")
    assert merged["returnOnEquity"] == 0.51
    assert merged["debtToEquity"] == 0.099
    assert merged["freeCashflow"] == 32000000000.0
    assert merged["data_quality"] == "statements"




def test_capture_snapshots_counts_and_throttles(monkeypatch):
    """Every symbol gets one capture call plus one inter-request pause."""
    monkeypatch.setattr(
        snapshots, "capture_symbol_snapshot",
        lambda sym: (True, "captured") if sym != "BAD.NS" else (False, "nope"),
    )
    pauses = {"n": 0}
    monkeypatch.setattr(snapshots.time, "sleep", lambda _sec: pauses.__setitem__("n", pauses["n"] + 1))
    res = snapshots.capture_snapshots(["A.NS", "B.NS", "BAD.NS"])
    assert res == {"requested": 3, "captured": 2, "failed": 1}
    assert pauses["n"] == 3


def test_merge_as_of_respects_antilookahead(tmp_path, monkeypatch):
    _write_records(tmp_path, monkeypatch, "TEST.NS", [
        {"as_of": "2024-01-01", "symbol": "TEST", "source": "yfinance.statements",
         "values": {"debtToEquity": 0.5}},
        {"as_of": "2024-06-01", "symbol": "TEST", "source": "yfinance.info",
         "values": {"debtToEquity": 87.0, "trailingPE": 12.0}},
    ])
    merged = snapshots.merge_fundamental_snapshots("TEST.NS", as_of="2024-03-01")
    assert merged["debtToEquity"] == 0.5          # statements only, no look-ahead
    assert merged.get("trailingPE") is None       # later info record excluded
    assert merged["data_quality"] == "statements"
