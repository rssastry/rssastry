"""
Tests for the local price-file layer (raw_data/prices):

  * price_store reads the yfinance-raw CSV format and normalizes it to the
    adjusted frame the app consumes downstream (same math as data_cache);
  * fetch_or_fallback quietly falls back to live yfinance when no CSV exists;
  * update_price_files merges only genuinely-new dates, preserves every
    existing line byte-for-byte, stays idempotent, and back-fills symbols
    that have no CSV yet.

No network is required: the fetch path is monkeypatched.
"""
import os

import pandas as pd
import pytest

import price_store
import update_price_files as updater

HEADER = "Date,Adj Close,Close,High,Low,Open,Volume"
SAMPLE = [
    HEADER,
    "2026-09-01,100.0,100.0,101.0,99.0,99.5,1000",
    "2026-09-02,101.0,101.0,102.0,100.0,100.5,1100",
    "2026-09-04,103.0,103.0,104.0,102.0,102.5,1300",
]


def _write_csv(path: str, rows=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as fh:
        fh.write("\r\n".join(rows or SAMPLE) + "\r\n")
    return path


@pytest.fixture
def raw_path(tmp_path):
    return _write_csv(str(tmp_path / "TEST.csv"))


@pytest.fixture
def store_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(price_store, "csv_path_for",
                        lambda sym: str(tmp_path / (sym + ".csv")))
    monkeypatch.setattr(updater, "csv_path_for",
                        lambda sym: str(tmp_path / (sym + ".csv")))
    return tmp_path


# ── price_store ────────────────────────────────────────────────

def test_read_raw_parses_yfinance_format(raw_path, monkeypatch):
    monkeypatch.setattr(price_store, "csv_path_for", lambda s: raw_path)
    df = price_store.read_raw("TEST")
    assert df.index.name == "Date"
    assert df.columns.tolist() == price_store.CSV_COLUMNS
    assert len(df) == 3
    assert float(df.loc["2026-09-04"].Open) == 102.5
    assert int(df.loc["2026-09-04"].Volume) == 1300


def test_load_adjusted_uses_adj_close(raw_path, monkeypatch):
    monkeypatch.setattr(price_store, "csv_path_for", lambda s: raw_path)
    df = price_store.load_adjusted("TEST")
    assert df.columns.tolist()[:5] == ["Open", "High", "Low", "Close", "Volume"]
    assert float(df["Close"].iloc[-1]) == 103.0


def test_load_adjusted_scales_ohlc_by_ratio(tmp_path, monkeypatch):
    rows = [
        HEADER,
        "2026-09-01,50.0,100.0,101.0,99.0,99.5,1000",
        "2026-09-02,51.0,102.0,103.0,101.0,101.5,1100",
    ]
    path = _write_csv(str(tmp_path / "TEST.csv"), rows)
    monkeypatch.setattr(price_store, "csv_path_for", lambda s: path)
    df = price_store.load_adjusted("TEST")
    assert float(df["Close"].iloc[0]) == 50.0
    assert float(df["Open"].iloc[0]) == pytest.approx(49.75)


def test_load_adjusted_window_filter(tmp_path, monkeypatch):
    path = _write_csv(str(tmp_path / "TEST.csv"))
    monkeypatch.setattr(price_store, "csv_path_for", lambda s: path)
    # end is exclusive (yfinance semantics): 09-02 only
    df = price_store.load_adjusted("TEST", start="2026-09-02",
                                   end="2026-09-04")
    assert len(df) == 1
    assert df.index[0].strftime("%Y-%m-%d") == "2026-09-02"
    # explicit period '1mo' keeps the whole sample (all dates within a month)
    df2 = price_store.load_adjusted("TEST", period="1mo")
    assert len(df2) == 3


def test_load_adjusted_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(price_store, "csv_path_for",
                        lambda s: str(tmp_path / "NOPE.csv"))
    assert price_store.load_adjusted("NOPE").empty


def test_fetch_or_fallback_empty_path(tmp_path, monkeypatch):
    monkeypatch.setattr(price_store, "csv_path_for",
                        lambda s: str(tmp_path / "NOPE.csv"))
    monkeypatch.setattr("data_cache.fetch_history",
                        lambda *a, **k: pd.DataFrame({"Close": [1.0]}))
    assert not price_store.fetch_or_fallback("NOPE").empty


# ── update_price_files ─────────────────────────────────────────

def test_update_merge_preserves_lines_and_orders(tmp_path, monkeypatch):
    path = _write_csv(str(tmp_path / "TEST.csv"))
    fake = pd.DataFrame({
        "Adj Close": [102.0, 104.0, 105.0],
        "Close": [102.0, 104.0, 105.0],
        "High": [103.0, 105.0, 106.0],
        "Low": [101.0, 103.0, 104.0],
        "Open": [101.5, 103.5, 104.5],
        "Volume": [1200, 1400, 1500],
    }, index=pd.DatetimeIndex(["2026-09-03", "2026-09-04", "2026-09-08"]))
    monkeypatch.setattr(updater, "fetch_bars", lambda *a, **k: fake)
    monkeypatch.setattr(updater, "csv_path_for", lambda s: path)

    status = updater.update_one("TEST")
    assert status.startswith("merge:2")

    lines = open(path).read().splitlines()
    for line in SAMPLE[1:]:
        assert line in lines, f"original line changed: {line}"
    assert lines.index("2026-09-04,103.0,103.0,104.0,102.0,102.5,1300") == 4
    assert lines[-1].startswith("2026-09-08,105.0")
    assert lines.count("2026-09-04,103.0,103.0,104.0,102.0,102.5,1300") == 1
    assert lines[0] == HEADER


def test_update_idempotent(tmp_path, monkeypatch):
    path = _write_csv(str(tmp_path / "TEST.csv"))
    fake = pd.DataFrame({
        "Adj Close": [102.0], "Close": [102.0], "High": [103.0],
        "Low": [101.0], "Open": [101.5], "Volume": [1200],
    }, index=pd.DatetimeIndex(["2026-09-03"]))
    monkeypatch.setattr(updater, "fetch_bars", lambda *a, **k: fake)
    monkeypatch.setattr(updater, "csv_path_for", lambda s: path)

    first = updater.update_one("TEST")
    before = open(path).read()
    second = updater.update_one("TEST")
    assert first.startswith("merge:")
    assert second == "unchanged"
    assert open(path).read() == before


def test_update_backfill_creates_missing_file(tmp_path, monkeypatch):
    path = str(tmp_path / "NEWCO.csv")
    fake = pd.DataFrame({
        "Adj Close": [10.0, 11.0], "Close": [10.0, 11.0],
        "High": [11.0, 12.0], "Low": [9.0, 10.0],
        "Open": [9.5, 10.5], "Volume": [500, 600],
    }, index=pd.DatetimeIndex(["2026-09-01", "2026-09-02"]))
    monkeypatch.setattr(updater, "fetch_bars", lambda *a, **k: fake)
    monkeypatch.setattr(updater, "csv_path_for", lambda s: path)

    status = updater.update_one("NEWCO")
    assert status == "backfill:2"
    lines = open(path).read().splitlines()
    assert lines[0] == HEADER
    assert len(lines) == 3


def test_update_appends_after_last_date(tmp_path, monkeypatch):
    path = _write_csv(str(tmp_path / "TEST.csv"))
    fake = pd.DataFrame({
        "Adj Close": [104.0], "Close": [104.0], "High": [105.0],
        "Low": [103.0], "Open": [103.5], "Volume": [1400],
    }, index=pd.DatetimeIndex(["2026-09-08"]))
    monkeypatch.setattr(updater, "fetch_bars", lambda *a, **k: fake)
    monkeypatch.setattr(updater, "csv_path_for", lambda s: path)

    assert updater.update_one("TEST") == "append:1"
    lines = open(path).read().splitlines()
    assert lines[-1].startswith("2026-09-08,104.0")