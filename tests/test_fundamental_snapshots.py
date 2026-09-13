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
