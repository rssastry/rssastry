"""Tests for journal.py - the personal decision journal."""

import json

import pandas as pd

import journal  # noqa: F401  (module must import cleanly)
from journal import DecisionJournal, STOPPED, EXPIRED, OPEN, NO_PLAN


def make_df(bars, start="2026-09-01"):
    """bars: list of (close, high, low) daily tuples."""
    index = pd.date_range(start, periods=len(bars), freq="B")
    df = pd.DataFrame(
        {"Open": [b[0] for b in bars],
         "High": [b[1] for b in bars],
         "Low": [b[2] for b in bars],
         "Close": [b[0] for b in bars],
         "Volume": [1_000_000] * len(bars)},
        index=index,
    )
    df.index.name = "Date"
    return df


def record(symbol="RELIANCE", style="swing", recommendation="BUY",
           entry=100.0, stop=95.0, targets=(108.0, 116.0, 124.0),
           capture_date="2026-08-31", atr=3.0, **extra):
    rec = {
        "symbol": symbol,
        "style": style,
        "recommendation": recommendation,
        "entry_price": {"ideal": entry},
        "stop_loss": stop,
        "target_prices": {"T1": targets[0], "T2": targets[1], "T3": targets[2]},
        "capture_date": capture_date,
        "atr": atr,
        "sector": "Technology",
        "market_regime": "bullish",
        "confidence_score": 70,
        "ensemble_score": 65,
    }
    rec.update(extra)
    return rec


# ── Logging ──────────────────────────────────────────────────────────
class TestLogging:
    def test_insert_and_dedupe(self):
        j = DecisionJournal(":memory:")
        assert j.log_decision(record()) == "inserted"
        # .NS and bare symbol, different case = same logical decision
        assert j.log_decision(record(symbol="RELIANCE.NS")) == "duplicate"
        # different recommendation is a distinct decision
        assert j.log_decision(record(recommendation="WATCHLIST",
                                     stop=None)) == "inserted"
        assert j.status()[OPEN] == 2

    def test_skipped_without_symbol(self):
        j = DecisionJournal(":memory:")
        assert j.log_decision({"recommendation": "BUY"}) == "skipped"

    def test_accepts_ai_analysis_shape(self):
        j = DecisionJournal(":memory:")
        ai = {
            "symbol": "SBICARD",
            "trading_style": "intraday",
            "recommendation": "WATCHLIST",
            "confidence_score": 68,
            "entry_price": {"ideal": 668.4, "range_low": 661.72},
            "target_prices": {"T1": 696.6, "T2": 724.8, "T3": 753.0},
            "stop_loss": 640.2,
            "sector": "Financial Services",
            "market_regime": "bullish",
            "atr": 12.3,
            "capture_date": "2026-09-12",
        }
        assert j.log_decision(ai) == "inserted"
        row = j.conn.execute("SELECT * FROM decisions").fetchone()
        assert row["style"] == "intraday"
        assert row["entry_price"] == 668.4
        assert row["target_1"] == 696.6


# ── Import ───────────────────────────────────────────────────────────
class TestImport:
    def test_import_screener_results(self, tmp_path):
        j = DecisionJournal(":memory:")
        path = tmp_path / "screener_results.json"
        path.write_text(json.dumps({
            "scan_time": "2026-09-12T15:45:00",
            "results": {"swing": [record(symbol="TCS")],
                        "positional": [record(symbol="INFY", style="positional")]},
        }))
        res = j.import_from_file(str(path))
        assert res["inserted"] == 2
        n = j.conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"]
        assert n == 2
        # re-import is idempotent
        res2 = j.import_from_file(str(path))
        assert res2["inserted"] == 0
        assert res2["duplicates"] == 2

    def test_import_ai_analysis(self, tmp_path):
        j = DecisionJournal(":memory:")
        path = tmp_path / "ai_analysis.json"
        path.write_text(json.dumps({
            "date": "2026-09-12",
            "analysis": {"swing": [record(recommendation="WATCHLIST")]},
        }))
        res = j.import_from_file(str(path), source="ai")
        assert res["inserted"] == 1
        assert res["duplicates"] == 0

    def test_import_missing_file(self, tmp_path):
        j = DecisionJournal(":memory:")
        res = j.import_from_file(str(tmp_path / "nope.json"))
        assert res["found"] is False


# ── Resolution ───────────────────────────────────────────────────────
def _set_prices(monkeypatch, bars):
    monkeypatch.setattr("price_store.load_adjusted",
                        lambda *a, **k: make_df(bars))


class TestResolution:
    def test_stopped(self, monkeypatch):
        j = DecisionJournal(":memory:")
        _set_prices(monkeypatch, [(101, 102, 99), (94, 95, 92), (96, 97, 95)])
        j.log_decision(record(stop=95.0))
        stats = j.resolve_open()
        assert stats[STOPPED] == 1
        row = j.conn.execute("SELECT * FROM decisions").fetchone()
        assert row["status"] == STOPPED
        assert row["outcome_price"] == 95.0
        # first completed bar AFTER the signal bar
        assert row["outcome_date"] == "2026-09-02"

    def test_target1_when_target_only(self, monkeypatch):
        j = DecisionJournal(":memory:")
        _set_prices(monkeypatch, [(105, 109, 104), (106, 107, 105),
                                  (104, 105, 103)])
        j.log_decision(record(targets=(108.0, 116.0, 124.0)))
        stats = j.resolve_open()
        assert stats["TARGET1"] == 1

    def test_target3_preferred_on_high_closure(self, monkeypatch):
        j = DecisionJournal(":memory:")
        _set_prices(monkeypatch, [(120, 130, 118), (100, 101, 99),
                                  (100, 101, 99)])
        j.log_decision(record(targets=(108.0, 116.0, 124.0)))
        stats = j.resolve_open()
        assert stats["TARGET3"] == 1

    def test_stop_first_within_same_bar(self, monkeypatch):
        """Low <= stop AND High >= T1 in the same bar: conservative wins."""
        j = DecisionJournal(":memory:")
        _set_prices(monkeypatch, [(100, 115, 90), (110, 111, 109),
                                  (110, 111, 109)])
        j.log_decision(record(stop=95.0, targets=(110.0, 116.0, 124.0)))
        stats = j.resolve_open()
        assert stats[STOPPED] == 1

    def test_expired_after_max_hold_sideways(self, monkeypatch):
        j = DecisionJournal(":memory:")
        # swing max_hold = 15 -> 15 flat bars, no touches
        _set_prices(monkeypatch, [(101, 102, 100)] * 15)
        j.log_decision(record(stop=95.0, targets=(108.0, 116.0, 124.0)))
        stats = j.resolve_open()
        assert stats[EXPIRED] == 1
        row = j.conn.execute("SELECT * FROM decisions").fetchone()
        assert row["outcome_price"] == 101.0  # last close of the window

    def test_stays_open_when_history_runs_out(self, monkeypatch):
        j = DecisionJournal(":memory:")
        _set_prices(monkeypatch, [(101, 102, 100)] * 5)  # < swing max-hold 15
        j.log_decision(record())
        stats = j.resolve_open()
        assert stats[OPEN] == 1
        assert j.status()[OPEN] == 1

    def test_hypothetical_for_planless_watchlist(self, monkeypatch):
        j = DecisionJournal(":memory:")
        _set_prices(monkeypatch, [(98, 99, 96), (95, 97, 93), (96, 97, 95)])
        j.log_decision(record(recommendation="WATCHLIST", stop=None,
                              targets=(None, None, None), atr=2.0))
        # swing: ATR_MULT 2.5 -> stop 95.0 ; TARGET_ATR_MULT 5.0 -> T1 110.0
        stats = j.resolve_open(hypothetical=False)
        assert stats[NO_PLAN] == 1
        stats = j.resolve_open(hypothetical=True)
        assert stats[STOPPED] == 1  # implied stop 95.0 hit on bar 2
        row = j.conn.execute("SELECT * FROM decisions").fetchone()
        assert row["outcome_price"] == 95.0

    def test_resolve_symbol_filter(self, monkeypatch):
        j = DecisionJournal(":memory:")
        _set_prices(monkeypatch, [(94, 95, 92)] * 5)
        j.log_decision(record(symbol="TCS"))
        j.log_decision(record(symbol="INFY"))
        stats = j.resolve_open(symbols=["TCS"])
        assert stats[STOPPED] == 1
        assert j.status()[OPEN] == 1  # INFY untouched


# ── Report / calibration ─────────────────────────────────────────────
class TestReport:
    def _seed(self, monkeypatch):
        j = DecisionJournal(":memory:")
        _set_prices(monkeypatch, [(94, 95, 92)] * 5)
        j.log_decision(record(symbol="TCS", confidence_score=80,
                              ensemble_score=70, sector="Technology"))
        j.log_decision(record(symbol="INFY", confidence_score=80,
                              ensemble_score=70, sector="Technology"))
        j.log_decision(record(symbol="HDFCBANK", confidence_score=50,
                              ensemble_score=40,
                              sector="Financial Services"))
        j.resolve_open()
        return j

    def test_grouped_by_style(self, monkeypatch):
        j = self._seed(monkeypatch)
        report = j.report(by="style")
        bucket = report["grouped"]["swing"]
        assert bucket["decisions"] == 3
        assert bucket["win_rate"] == 0.0
        assert bucket["stop_rate"] == 1.0
        assert bucket["median_return_pct"] == -5.0  # (95/100 - 1)

    def test_calibration_bands(self, monkeypatch):
        j = self._seed(monkeypatch)
        report = j.report(by="band")
        hi = report["grouped"]["conf-75+"]
        lo = report["grouped"]["conf-<55"]
        assert hi["decisions"] == 2
        assert lo["decisions"] == 1

    def test_report_overall_aggregate(self, monkeypatch):
        j = self._seed(monkeypatch)
        report = j.report(by="all")
        overall = report["overall"]
        assert overall["decisions"] == 3
        assert report["resolved"] == 3
        assert report["open"] == 0