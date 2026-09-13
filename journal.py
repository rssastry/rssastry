"""
journal.py - Personal Decision Journal: close the loop on every trading
decision so the system calibrates against reality instead of only backtests.

A "bible" for a stock-market journey must record three things:
  1) what the system believed (screener / AI / manual context),
  2) what was decided (BUY / WATCHLIST / HOLD / SELL per style),
  3) what actually happened afterwards (stop hit / T1..T3 reached / faded).

Every decision is stored in a local SQLite store (data_cache/decision_journal.sqlite).
`resolve_open()` folds the *frozen* raw_data/prices CSVs forward from the signal
bar - no network, no look-ahead - using the same conventions as
validate_buy_logic.py (entry at the next bar, style max-hold in completed bars).
Decisions with a full trade plan (stop + targets, e.g. AI analysis records) are
resolved directly. Decisions without a plan (plain screener candidates) can be
resolved *hypothetically* (--hypothetical): a deterministic plan is implied from
config (ATR_MULT / TARGET_ATR_MULT by style), which answers the question
"did rejecting this to WATCHLIST save us, or cost us?"

Resolution rule per completed bar (conservative, stop-first intrabar):
  - if bar.Low  <= stop_loss : STOPPED  (filled at stop_loss)
  - elif bar.High >= T3      : TARGET3
  - elif bar.High >= T2      : TARGET2
  - elif bar.High >= T1      : TARGET1
  - window of STYLE_MAX_HOLD_BARS[style] exhausted without a touch:
        EXPIRED at the window's last close  (time-based exit, the model's
        convention for a position that ran out of thesis)
If the local CSV ends before the window is complete, the decision stays OPEN.

CLI:
    python journal.py import            # seed from screener_results.json + ai_analysis.json
    python journal.py resolve           # resolve OPEN decisions against local CSVs
    python journal.py resolve --hypothetical
    python journal.py report [--by style]
    python journal.py status
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import date, datetime, timezone

import pandas as pd

import config
from config import STYLE_MAX_HOLD_BARS, JOURNAL_DB_PATH

# Status vocabulary
OPEN = "OPEN"
STOPPED = "STOPPED"
EXPIRED = "EXPIRED"
TARGETS = ("TARGET1", "TARGET2", "TARGET3")
WIN_STATUSES = set(TARGETS)
RESOLVED_STATUSES = WIN_STATUSES | {STOPPED, EXPIRED}
NO_PLAN = "NO_PLAN"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    capture_date    TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    style           TEXT,
    source          TEXT DEFAULT 'screener',
    recommendation  TEXT,
    entry_price     REAL,
    stop_loss       REAL,
    target_1        REAL,
    target_2        REAL,
    target_3        REAL,
    confidence_score REAL,
    ensemble_score  REAL,
    technical_score REAL,
    fundamental_score REAL,
    sector          TEXT,
    market_regime   TEXT,
    atr             REAL,
    current_price   REAL,
    decision_json   TEXT,
    status          TEXT DEFAULT 'OPEN',
    outcome_date    TEXT,
    outcome_price   REAL,
    resolved_at     TEXT,
    UNIQUE(capture_date, symbol, style, source, recommendation)
);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON decisions(symbol);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fnum(value):
    try:
        f = float(value)
        return f if f == f else None  # NaN guard
    except (TypeError, ValueError):
        return None


def _istr(value) -> str:
    return str(value or "").strip()


def _bare(symbol: str) -> str:
    return _istr(symbol).upper().replace(".NS", "")


def _median(values: list) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 2)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 2)
class DecisionJournal:
    """SQLite-backed journal of trading decisions with forward resolution."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or JOURNAL_DB_PATH
        if self.db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(self.db_path))
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ---- writing -----------------------------------------------------
    def log_decision(self, record: dict, ts: str = None) -> str | None:
        """Insert one decision; returns 'inserted' | 'duplicate' | 'skipped'.

        Accepts both screening candidates (no trade plan) and AI analysis
        records (full plan). Missing plan fields are stored NULL and the
        record remains resolvable later with --hypothetical.
        """
        symbol = _istr(record.get("symbol") or record.get("ticker"))
        if not symbol:
            return "skipped"
        style = _istr(record.get("style")
                      or record.get("trading_style")
                      or record.get("strategy")).lower()
        recommendation = _istr(record.get("recommendation")
                               or record.get("selection_decision")).upper()
        if recommendation in ("", "UNKNOWN"):
            recommendation = "WATCHLIST"
        capture_date = _istr(record.get("capture_date")
                             or record.get("data_as_of")
                             or date.today().isoformat())[:10]
        source = _istr(record.get("source") or "screener")

        # Explicit idempotency check (INSERT OR IGNORE rowcount is unreliable
        # across sqlite3 builds for ignored rows).
        identity = (capture_date, _bare(symbol), style, source, recommendation)
        if self.conn.execute(
            "SELECT 1 FROM decisions WHERE capture_date=? AND symbol=? "
            "AND style=? AND source=? AND recommendation=? LIMIT 1",
            identity).fetchone():
            return "duplicate"

        entry = record.get("entry_price") or {}
        targets = record.get("target_prices") or {}
        if isinstance(entry, dict):
            ideal_entry = _fnum(entry.get("ideal") or entry.get("current_price"))
        else:
            ideal_entry = _fnum(entry) or _fnum(record.get("current_price"))
        stop = _fnum(record.get("stop_loss")) or _fnum(record.get("stop"))
        t1 = _fnum(targets.get("T1")) or _fnum(record.get("target_1"))
        t2 = _fnum(targets.get("T2")) or _fnum(record.get("target_2"))
        t3 = _fnum(targets.get("T3")) or _fnum(record.get("target_3"))

        row = {
            "ts": ts or _utc_now(),
            "capture_date": _istr(record.get("capture_date")
                                  or record.get("data_as_of")
                                  or date.today().isoformat())[:10],
            "symbol": _bare(symbol),
            "style": style or None,
            "source": _istr(record.get("source") or "screener"),
            "recommendation": recommendation,
            "entry_price": ideal_entry,
            "stop_loss": stop,
            "target_1": t1,
            "target_2": t2,
            "target_3": t3,
            "confidence_score": _fnum(record.get("confidence_score")
                                      or record.get("confidence")),
            "ensemble_score": _fnum(record.get("ensemble_score")),
            "technical_score": _fnum(record.get("technical_score")
                                     or record.get("score")),
            "fundamental_score": _fnum(record.get("fundamental_score")
                                       or record.get("quality_score")),
            "sector": _istr(record.get("sector")) or None,
            "market_regime": _istr(record.get("market_regime")) or None,
            "atr": _fnum(record.get("atr")),
            "current_price": _fnum(record.get("current_price")),
            "decision_json": json.dumps(record, default=str),
        }
        try:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO decisions
                   (ts, capture_date, symbol, style, source, recommendation,
                    entry_price, stop_loss, target_1, target_2, target_3,
                    confidence_score, ensemble_score, technical_score,
                    fundamental_score, sector, market_regime, atr,
                    current_price, decision_json)
                   VALUES (:ts, :capture_date, :symbol, :style, :source,
                    :recommendation, :entry_price, :stop_loss, :target_1,
                    :target_2, :target_3, :confidence_score,
                    :ensemble_score, :technical_score, :fundamental_score,
                    :sector, :market_regime, :atr, :current_price,
                    :decision_json)""",
                row,
            )
            self.conn.commit()
        except sqlite3.Error:
            return "error"
        if cur.rowcount:
            return "inserted"
        return "duplicate"

    def import_from_file(self, path: str, source: str = "screener",
                         date_str: str = None) -> dict:
        """Bulk-import candidates from screener_results.json / ai_analysis.json.

        screener_results.json : {"scan_time": ..., "results": {style: [..]}}
        ai_analysis.json      : {"date": ..., "analysis": {style: [..]}}
        """
        if not os.path.exists(path):
            return {"path": path, "found": False, "inserted": 0,
                    "duplicates": 0, "skipped": 0}
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        styles = {}
        capture_date = date_str
        if isinstance(data, dict):
            if "results" in data and isinstance(data["results"], dict):
                styles = data["results"]
                capture_date = capture_date or str(data.get("scan_time"))[:10]
            elif "analysis" in data and isinstance(data["analysis"], dict):
                styles = data["analysis"]
                capture_date = capture_date or str(data.get("date"))[:10]
            elif any(k in data for k in ("intraday", "swing", "positional")):
                styles = data
        counts = {"path": path, "found": True, "inserted": 0,
                  "duplicates": 0, "skipped": 0}
        for style, items in styles.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item = dict(item)
                item.setdefault("style", style)
                item.setdefault("source", source)
                item.setdefault("capture_date", capture_date)
                action = self.log_decision(item)
                counts[action] = counts.get(action, 0) + 1
        counts["duplicates"] = counts.pop("duplicate", 0)
        counts.pop("error", None)
        return counts

    # ---- resolution ---------------------------------------------------
    def open_rows(self, include_no_plan: bool = False):
        rows = self.conn.execute(
            "SELECT * FROM decisions WHERE status = ?", (OPEN,)).fetchall()
        for row in rows:
            if include_no_plan or row["stop_loss"] is not None:
                yield row

    def _implied_plan(self, row) -> dict | None:
        """Deterministic trade plan from config when the record has none
        (hypothetical resolution of WATCHLIST candidates)."""
        style = row["style"] or "swing"
        atr = row["atr"]
        price = row["entry_price"] or row["current_price"]
        if not price or price <= 0 or not atr or atr <= 0:
            return None
        atr_mult = config.ATR_MULT.get(style, 1.5)
        target_mult = config.TARGET_ATR_MULT.get(style, 3.0)
        stop = price - atr_mult * atr
        return {
            "stop_loss": round(stop, 2),
            "target_1": round(price + target_mult * atr, 2),
            "target_2": round(price + target_mult * atr * 1.6, 2),
            "target_3": round(price + target_mult * atr * 2.2, 2),
            "implied": True,
        }

    def resolve_row(self, row, as_of: str = None) -> dict | None:
        """Resolve ONE decision forward against local price data.

        Returns an outcome dict, or None when local history has no further
        bars yet (decision stays OPEN). Conservative stop-first intrabar
        resolution within each completed bar.
        """
        stop = row["stop_loss"]
        t1, t2, t3 = row["target_1"], row["target_2"], row["target_3"]
        if stop is None or t1 is None:
            return None
        try:
            from price_store import load_adjusted
        except Exception:
            return None
        df = load_adjusted(row["symbol"], period=None, interval="1d")
        if df is None or df.empty or "Close" not in df.columns:
            return None
        signal = pd.Timestamp(row["capture_date"])
        after = df[df.index > signal]
        if after.empty:
            return None
        max_hold = int(STYLE_MAX_HOLD_BARS.get(row["style"], 15))
        window = after.iloc[:max_hold]
        for bar_date, bar in window.iterrows():
            if float(bar["Low"]) <= stop:
                return {"status": STOPPED,
                        "outcome_date": str(bar_date.date()),
                        "outcome_price": stop}
            for label, level in (("TARGET3", t3), ("TARGET2", t2),
                                 ("TARGET1", t1)):
                if level is not None and float(bar["High"]) >= level:
                    return {"status": label,
                            "outcome_date": str(bar_date.date()),
                            "outcome_price": level}
        # No touch within the forward bars we have so far.
        if len(after) < max_hold:
            # Not enough completed bars yet to declare a time-based exit.
            return None
        last_close = float(window["Close"].iloc[-1])
        return {"status": EXPIRED,
                "outcome_date": str(window.index[-1].date()),
                "outcome_price": last_close}

    def resolve_open(self, hypothetical: bool = False, symbols=None) -> dict:
        """Resolve every OPEN decision; optionally materialise hypothetical
        plans for plan-less rows first. Returns per-status counts."""
        stats = {OPEN: 0, STOPPED: 0, EXPIRED: 0,
                 "TARGET1": 0, "TARGET2": 0, "TARGET3": 0, NO_PLAN: 0}
        resolved_at = _utc_now()
        wanted = {_bare(s) for s in symbols} if symbols else None
        cursor = self.conn.execute(
            "SELECT * FROM decisions WHERE status = ? ORDER BY capture_date",
            (OPEN,),
        )
        for row in cursor.fetchall():
            if wanted and row["symbol"] not in wanted:
                continue
            stop = row["stop_loss"]
            t1 = row["target_1"]
            if stop is not None and t1 is not None:
                plan = None  # row has a real plan; resolve directly
            elif hypothetical:
                plan = self._implied_plan(row)
            else:
                stats[NO_PLAN] += 1
                continue
            outcome = self.resolve_row(_RecordProxy(row, plan or {}))
            if outcome is None:
                stats[OPEN] += 1
                continue
            with self.conn:
                self.conn.execute(
                    """UPDATE decisions SET status=?, outcome_date=?,
                       outcome_price=?, resolved_at=? WHERE id=?""",
                    (outcome["status"], outcome["outcome_date"],
                     outcome["outcome_price"], resolved_at, row["id"]),
                )
            stats[outcome["status"]] = stats.get(outcome["status"], 0) + 1
        return stats

    # ---- reporting -----------------------------------------------------
    def _resolved_rows(self):
        placeholder = ",".join("?" * len(RESOLVED_STATUSES))
        return self.conn.execute(
            f"SELECT * FROM decisions WHERE status IN ({placeholder})",
            tuple(RESOLVED_STATUSES)).fetchall()

    def report(self, by: str = None) -> dict:
        rows = self._resolved_rows()
        total = self.conn.execute(
            "SELECT COUNT(*) AS n FROM decisions").fetchone()["n"]
        open_n = self.conn.execute(
            "SELECT COUNT(*) AS n FROM decisions WHERE status=?",
            (OPEN,)).fetchone()["n"]
        resolved = []
        for r in rows:
            entry = r["entry_price"] or r["current_price"]
            if not entry or entry <= 0 or r["outcome_price"] is None:
                continue
            resolved.append({
                "symbol": r["symbol"],
                "style": r["style"] or "unknown",
                "sector": r["sector"] or "Unknown",
                "regime": r["market_regime"] or "unknown",
                "status": r["status"],
                "entry": entry,
                "outcome": r["outcome_price"],
                "return_pct": round((r["outcome_price"] / entry - 1) * 100, 2),
                "confidence": r["confidence_score"],
                "ensemble": r["ensemble_score"],
                "capture_date": r["capture_date"],
            })
        groups = _grouped(resolved, by)
        overall = _grouped(resolved, None)
        return {
            "generated_at": _utc_now(),
            "store": os.path.basename(self.db_path),
            "total_decisions": total,
            "open": open_n,
            "resolved": len(resolved),
            "overall": overall.get("ALL"),
            "grouped": groups,
            "dedupe_key": "capture_date+symbol+style+source+recommendation",
        }

    def status(self) -> dict:
        counts = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM decisions GROUP BY status")
        return {r["status"] or OPEN: r["n"] for r in counts}

    def close(self):
        self.conn.close()


class _RecordProxy:
    """Shim so resolve_row() can read a hypothetical plan transparently."""

    def __init__(self, row, plan: dict):
        self._row = row
        self._plan = plan

    def __getitem__(self, key):
        if key in self._plan:
            return self._plan[key]
        return self._row[key]

    # ---- aggregation helpers ---------------------------------------------
def _key_for(record: dict, by: str | None) -> str:
    if by in (None, "all"):
        return "ALL"
    if by == "band":
        c = record.get("confidence")
        if c is None:
            return "no-conf"
        if c < 55:
            return "conf-<55"
        if c < 65:
            return "conf-55-64"
        if c < 75:
            return "conf-65-74"
        return "conf-75+"
    if by == "ensemble":
        e = record.get("ensemble")
        if e is None:
            return "no-ens"
        if e < 50:
            return "ens-<50"
        if e < 65:
            return "ens-50-64"
        return "ens-65+"
    return _istr(record.get(by) or "unknown")


def _grouped(records: list, by: str | None) -> dict:
    out = {}
    for rec in records:
        key = _key_for(rec, by)
        bucket = out.setdefault(key, {"decisions": 0, "wins": 0, "losses": 0,
                                      "faded": 0, "returns": [],
                                      "symbols": set()})
        bucket["decisions"] += 1
        bucket["symbols"].add(rec["symbol"])
        bucket["returns"].append(rec["return_pct"])
        if rec["status"] in WIN_STATUSES:
            bucket["wins"] += 1
        elif rec["status"] == STOPPED:
            bucket["losses"] += 1
        else:
            bucket["faded"] += 1
    for bucket in out.values():
        n = bucket["decisions"]
        bucket["win_rate"] = round(bucket["wins"] / n, 4) if n else None
        bucket["stop_rate"] = round(bucket["losses"] / n, 4) if n else None
        bucket["fade_rate"] = round(bucket["faded"] / n, 4) if n else None
        bucket["avg_return_pct"] = (round(sum(bucket["returns"]) / n, 2)
                                    if n else None)
        bucket["median_return_pct"] = _median(bucket["returns"])
        bucket["symbols"] = sorted(bucket["symbols"])
        del bucket["returns"]
    return out


# ---- CLI ---------------------------------------------------------------
def _print_report(report: dict):
    title = (f"Decision Journal - resolved {report['resolved']} / "
             f"open {report['open']} / total {report['total_decisions']}")
    print("=" * len(title))
    print(title)
    print("=" * len(title))
    for key in sorted(report.get("grouped", {})):
        bucket = report["grouped"][key]
        print(f"\n[{key}]  n={bucket['decisions']}  "
              f"win={bucket['win_rate']:.1%}  "
              f"stop={bucket['stop_rate']:.1%}  fade={bucket['fade_rate']:.1%}  "
              f"avgRet={bucket['avg_return_pct']}%  "
              f"medRet={bucket['median_return_pct']}%")
        print(f"    symbols: {', '.join(bucket['symbols'][:12])}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    p_import = sub.add_parser("import", help="seed from screener/AI JSONs")
    p_import.add_argument("--paths",
                          default="screener_results.json,ai_analysis.json")
    p_import.add_argument("--source", default="auto")
    p_import.add_argument("--date", default=None)
    p_resolve = sub.add_parser("resolve", help="resolve OPEN decisions")
    p_resolve.add_argument("--hypothetical", action="store_true")
    p_resolve.add_argument("--symbols", default=None)
    p_report = sub.add_parser("report", help="win-rate report")
    p_report.add_argument("--by", choices=["all", "style", "sector", "band",
                                           "ensemble", "regime"],
                          default="style")
    p_report.add_argument("--json", default="journal_report.json")
    sub.add_parser("status", help="status counts")
    args = ap.parse_args()

    journal = DecisionJournal()
    try:
        if args.cmd == "import":
            totals = {"inserted": 0, "duplicates": 0, "skipped": 0}
            for path in [p.strip() for p in args.paths.split(",") if p.strip()]:
                inferred = ("ai" if "ai_" in os.path.basename(path)
                            else "screener")
                source = (inferred if args.source in (None, "auto")
                          else args.source)
                res = journal.import_from_file(path, source=source,
                                               date_str=args.date)
                if res.get("found"):
                    print(f"{path}: inserted={res['inserted']} "
                          f"duplicates={res['duplicates']} "
                          f"skipped={res['skipped']}")
                    for key in totals:
                        totals[key] += res.get(key, 0)
            print(f"Total: {totals}")
        elif args.cmd == "resolve":
            symbols = ([s.strip() for s in args.symbols.split(",") if s.strip()]
                       if args.symbols else None)
            stats = journal.resolve_open(hypothetical=args.hypothetical,
                                         symbols=symbols)
            resolved = sum(v for k, v in stats.items()
                           if k not in (OPEN, NO_PLAN))
            print(f"Resolved {resolved} decision(s) -> ", end="")
            print(", ".join(f"{k}={v}" for k, v in stats.items() if v))
        elif args.cmd == "report":
            report = journal.report(by=args.by or None)
            with open(args.json, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, default=str)
            _print_report(report)
            print(f"\nSaved: {args.json}")
        elif args.cmd == "status":
            print(json.dumps(journal.status(), indent=2))
        else:
            ap.print_help()
        return 0
    finally:
        journal.close()


if __name__ == "__main__":
    raise SystemExit(main())