"""backfill_fundamental_history.py — free point-in-time fundamentals via yfinance.

yfinance exposes per-fiscal-year *as-reported* annual statements through
``Ticker.income_stmt`` / ``Ticker.balance_sheet`` / ``Ticker.cashflow``. For
NSE symbols these are the audited annual values (e.g. ROE, ROCE, D/E, margins,
FCF, EPS, BVPS) for each completed fiscal year — the same numbers a fund manager
would have known right after each annual report. This is exactly the "provider
that supplies point-in-time historical fundamentals" the README calls for,
without any paid API.

What this script does
---------------------
For each symbol it reconstructs the fundamental fields consumed by
`screener.fundamental_buy_gate` and `strategies.*` and appends one dated record
per fiscal year to ``data_cache/fundamental_snapshots/<SYMBOL>.jsonl`` in the
same JSONL schema as the daily captures::

    {"as_of": "2025-07-29", "symbol": "RELIANCE", "source": "yfinance.statements",
     "period_end": "2025-03-31", "values": {roe, roce, debtToEquity, margins, ...}}

Anti-lookahead contract
------------------------
``as_of`` = fiscal-year end + ``FILING_BUFFER_DAYS`` (120). A signal dated on or
after ``as_of`` may legitimately know the annual results; earlier signals cannot.
The *newest* fiscal-year column is skipped by default (``skip_latest``) because
Yahoo still labels it "estimate" until it has been replaced by the audited
filing, and the daily ``.info`` snapshots already cover the most recent window.
``fundamental_snapshots.load_snapshot_as_of`` picks these rows up unchanged, so
`validate_buy_logic.py` immediately backtests with honest point-in-time
fundamentals instead of today's quality overlaid on 2022 prices.

Run::

    .venv\\Scripts\\python.exe backfill_fundamental_history.py            # all local symbols
    .venv\\Scripts\\python.exe backfill_fundamental_history.py -s RELIANCE.NS,TCS.NS
    .venv\\Scripts\\python.exe backfill_fundamental_history.py --dry-run --symbols 40
    .venv\\Scripts\\python.exe backfill_fundamental_history.py --force     # rebuild statement rows
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

from fundamental_snapshots import (
    SNAPSHOT_DIR,
    _path,
    load_snapshots,
    resolve_provider_ticker,
)

# Conservative filing buffer: an annual report is treated as public knowledge
# only after fiscal-year end + this many days. Indian listed companies file
# within ~6 months of year-end; 120 days keeps us on the safe side.
FILING_BUFFER_DAYS = 120

# Marks rows created by this script so loaders / coverage / --force can tell
# statement-derived snapshots from the live Ticker.info daily captures.
SOURCE = "yfinance.statements"


# ── low-level helpers ────────────────────────────────────────────────────────

def _scalar(frame, row, period, default=None, fallbacks=()):
    """Return one numeric float from ``frame.loc[row / fallback, period]``.

    Tolerates the usual yfinance noise (pd.NA, None, strings, inf).
    """
    if frame is None or getattr(frame, "empty", True):
        return default
    try:
        index = set(frame.index)
    except Exception:
        return default
    for name in (row,) + tuple(fallbacks):
        if name not in index:
            continue
        try:
            value = frame.loc[name, period]
        except (KeyError, TypeError):
            continue
        if value is None or pd.isna(value):
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(numeric):
            return numeric
    return default


def _ratio(num, den, default=None):
    """num / den with the usual guards."""
    if num is None or den is None:
        return default
    if abs(float(den)) < 1e-12:
        return default
    return float(num) / float(den)


def _rounded(value, digits=6, default=None):
    if value is None:
        return default
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return default
# ── statement -> values mapping ──────────────────────────────────────────────

def build_period_values(income, balance, cashflow, period,
                        prev_net_income=None) -> dict:
    """Reconstruct one fiscal year's scoring fields from yfinance statements.

    Uses the same names that `record_snapshot` / `fundamental_buy_gate` /
    `strategies.*` consume so the backfilled rows drop straight into the
    existing scoring pipeline.

    Returns only the fields that could be derived (no None placeholders).
    """
    net_income = _scalar(income, "Net Income", period)
    ebit = _scalar(income, "EBIT", period)
    operating_income = _scalar(income, "Operating Income", period, default=ebit)
    revenue = _scalar(income, "Total Revenue", period,
                      fallbacks=("Operating Revenue",))
    equity = _scalar(balance, "Stockholders Equity", period,
                     fallbacks=("Common Stock Equity",
                                "Total Equity Gross Minority Interest"))
    debt = _scalar(balance, "Total Debt", period, fallbacks=("Net Debt",))
    total_assets = _scalar(balance, "Total Assets", period)
    current_liab = _scalar(balance, "Current Liabilities", period,
                           fallbacks=("Other Current Liabilities",
                                      "Current Debt And Capital Lease Obligation"))
    shares = _scalar(balance, "Ordinary Shares Number", period)
    free_cash_flow = _scalar(cashflow, "Free Cash Flow", period)
    capex = _scalar(cashflow, "Capital Expenditure", period)
    pretax = _scalar(income, "Pretax Income", period)
    tax_provision = _scalar(income, "Tax Provision", period)

    values = {}

    roe = _ratio(net_income, equity)
    if roe is not None:
        values["returnOnEquity"] = _rounded(roe)

    if total_assets is not None and current_liab is not None:
        roce = _ratio(operating_income, total_assets - current_liab)
        if roce is not None:
            values["returnOnCapitalEmployed"] = _rounded(roce)

    debt_eq = _ratio(debt, equity)
    if debt_eq is not None:
        values["debtToEquity"] = _rounded(debt_eq)

    net_margin = _ratio(net_income, revenue)
    if net_margin is not None:
        values["profitMargins"] = _rounded(net_margin)
    op_margin = _ratio(operating_income, revenue)
    if op_margin is not None:
        values["operatingMargins"] = _rounded(op_margin)

    if free_cash_flow is None and pretax is not None and tax_provision is not None:
        # Fall back to cash-earnings proxy: pretax income minus tax provision.
        free_cash_flow = pretax - tax_provision
    if free_cash_flow is not None:
        values["freeCashflow"] = _rounded(free_cash_flow)

    if net_income is not None and prev_net_income is not None \
            and abs(prev_net_income) > 1e-12:
        growth = (net_income - prev_net_income) / abs(prev_net_income)
        values["earningsGrowth"] = _rounded(growth)

    # reinvestment ratio drives strategy.score_roce_reinvest, which reads
    # payoutRatio first, then capitalExpenditures + netIncome.
    if capex is not None and net_income is not None and abs(net_income) > 1e-12:
        reinvest = abs(capex) / abs(net_income)
        values["payoutRatio"] = _rounded(max(1.0 - reinvest, 0.0))
        values["capitalExpenditures"] = _rounded(abs(capex))
    if net_income is not None:
        values["netIncome"] = _rounded(net_income)

    # Per-share building blocks let the loader derive a point-in-time P/E and
    # P/B from the signal-bar close (raw historical market prices are NOT in
    # the statements, so valuation is reconstructed at use time instead).
    if shares is not None and abs(shares) > 1e-12:
        if net_income is not None:
            values["eps"] = _rounded(net_income / shares)
        if equity is not None:
            values["bvps"] = _rounded(equity / shares)

    return values


def fiscal_periods(income) -> list:
    """Sorted ascending list of fiscal-year-end Timestamps from an income stmt."""
    if income is None or getattr(income, "empty", True):
        return []
    periods = []
    for column in income.columns:
        try:
            stamp = pd.Timestamp(column).normalize()
        except Exception:
            continue
        if pd.notna(stamp):
            periods.append(stamp)
    return sorted(set(periods))


def build_records(income, balance, cashflow, symbol_bare: str,
                  buffer_days: int = FILING_BUFFER_DAYS,
                  skip_latest: bool = True,
                  today: date = None) -> list:
    """One dated record per usable fiscal year.

    A fiscal year is usable only when ``period_end + buffer_days`` has already
    passed (the report is plausibly public). ``skip_latest`` additionally drops
    the newest eligible column because Yahoo still labels it an estimate.
    """
    today = today or date.today()
    eligible = [p for p in fiscal_periods(income)
                if p.date() + timedelta(days=buffer_days) <= today]
    if skip_latest and eligible:
        eligible = eligible[:-1]

    records = []
    prev_net_income = None
    for period in eligible:
        current_ni = _scalar(income, "Net Income", period)
        values = build_period_values(income, balance, cashflow, period,
                                     prev_net_income=prev_net_income)
        if values:
            records.append({
                "as_of": (period.date() + timedelta(days=buffer_days)).isoformat(),
                "symbol": symbol_bare,
                "source": SOURCE,
                "period_end": period.date().isoformat(),
                "values": values,
            })
        if current_ni is not None:
            prev_net_income = current_ni
    return records


# ── JSONL persistence (same schema as fundamental_snapshots.py) ──────────────

def merge_records(existing: list, new: list, drop_source=None) -> list:
    """Merge snapshot records deduped by ``as_of``, sorted by ``as_of``.

    ``new`` wins on ``as_of`` collisions so a regenerated row can replace a
    stale one; ``drop_source`` optionally discards existing rows from one
    source first (used by ``--force`` for statement rows).
    """
    base = (existing if drop_source is None
            else [r for r in existing if r.get("source") != drop_source])
    merged = list(base)
    for rec in new:
        merged = [r for r in merged if r.get("as_of") != rec.get("as_of")]
        merged.append(rec)
    merged.sort(key=lambda r: str(r.get("as_of", "")))
    return merged


def write_snapshots(symbol, records: list, force: bool = False) -> dict:
    """Append ``records`` for ``symbol`` to its jsonl, writing only new ones.

    Idempotent: rows already stored verbatim are never re-written. ``force``
    first drops previously backfilled statement rows so a re-run after a
    mapping change regenerates them cleanly, but a forced re-run with identical
    content writes nothing. Daily ``yfinance.info`` captures are never touched.

    Returns ``rows_written`` (lines added or changed by this call) and
    ``rows_total`` (lines in the file afterwards).
    """
    prior = load_snapshots(symbol)
    prior_by_asof = {r.get("as_of"): r for r in prior}
    if force:
        kept = [r for r in prior if r.get("source") != SOURCE]
    else:
        kept = list(prior)
    merged = list(kept)
    changed = 0
    for rec in sorted(records, key=lambda r: str(r.get("as_of", ""))):
        if not force and prior_by_asof.get(rec.get("as_of")) == rec:
            continue  # verbatim row already stored
        merged = [r for r in merged if r.get("as_of") != rec.get("as_of")]
        merged.append(rec)
        old = prior_by_asof.get(rec.get("as_of"))
        if old is None or old != rec:
            changed += 1

    merged.sort(key=lambda r: str(r.get("as_of", "")))
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    with open(_path(symbol), "w", encoding="utf-8") as handle:
        for rec in merged:
            handle.write(json.dumps(rec, default=str, sort_keys=True) + "\n")
    return {"rows_written": changed, "rows_total": len(merged)}


# ── per-symbol / universe entry points ───────────────────────────────────────

def backfill_symbol(symbol, buffer_days: int = FILING_BUFFER_DAYS,
                    skip_latest: bool = True, force: bool = False,
                    dry_run: bool = False) -> dict:
    """Fetch a symbol's statements and append dated annual snapshots."""
    bare = symbol.upper().removesuffix(".NS")
    summary = {"symbol": bare, "periods": [], "wrote": 0,
               "rows_total": 0, "error": None}
    if bare.startswith("^"):
        summary["error"] = "index series has no annual fundamentals; skipped"
        return summary
    # Fetch from the provider's successor ticker for renamed / de-merged
    # companies, but keep records keyed to the local symbol.
    provider_symbol = resolve_provider_ticker(symbol)
    try:
        ticker = yf.Ticker(provider_symbol)
        income = ticker.income_stmt
        balance = ticker.balance_sheet
        cashflow = ticker.cashflow
    except Exception as exc:  # network / provider error — report and continue
        summary["error"] = str(exc)[:160]
        return summary

    records = build_records(income, balance, cashflow, bare,
                            buffer_days=buffer_days, skip_latest=skip_latest)
    summary["periods"] = [r["period_end"] for r in records]

    if not records and not summary.get("error"):
        summary["no_statement_data"] = True

    if dry_run:
        existing = load_snapshots(symbol)
        known = {r.get("as_of") for r in existing}
        summary["wrote"] = sum(1 for r in records if r.get("as_of") not in known)
        summary["rows_total"] = len(existing) + summary["wrote"]
        return summary

    try:
        result = write_snapshots(symbol, records, force=force)
        summary["wrote"] = result["rows_written"]
        summary["rows_total"] = result["rows_total"]
    except Exception as exc:
        summary["error"] = str(exc)[:160]
    return summary


def backfill_symbols(symbols, buffer_days: int = FILING_BUFFER_DAYS,
                     skip_latest: bool = True, force: bool = False,
                     dry_run: bool = False, sleep_secs: float = 0.2,
                     progress=None) -> dict:
    """Backfill a universe of symbols; aggregates a summary dict."""
    results = []
    for position, symbol in enumerate(symbols, 1):
        summary = backfill_symbol(symbol, buffer_days=buffer_days,
                                  skip_latest=skip_latest, force=force,
                                  dry_run=dry_run)
        results.append(summary)
        if progress:
            progress(position, len(symbols), summary)
        if sleep_secs and position < len(symbols):
            time.sleep(sleep_secs)
    with_error = [r["symbol"] for r in results if r.get("error")]
    no_data = [r["symbol"] for r in results
               if not r.get("error") and r.get("no_statement_data")]
    did_write = [r["symbol"] for r in results
                 if not r.get("error") and not r.get("no_statement_data")
                 and r.get("wrote", 0) > 0]
    no_change = [r["symbol"] for r in results
                 if not r.get("error") and not r.get("no_statement_data")
                 and r.get("wrote", 0) == 0]
    return {
        "mode": "dry-run" if dry_run else "backfill",
        "requested": len(symbols),
        "symbols_written": len(did_write),
        "symbols_unchanged": len(no_change),
        "symbols_without_statement_data": len(no_data),
        "symbols_failed": len(with_error),
        "new_rows": sum(r.get("wrote", 0) for r in results),
        "failed_symbols": with_error,
        "no_data_symbols": no_data,
        "unchanged_symbols": no_change[:20],
    }
# ── CLI ──────────────────────────────────────────────────────────────────────

def _default_universe() -> list:
    """Local raw_data/prices universe — stocks only, no index series.

    Index series (``^NSEI``) have no annual fundamentals and are excluded.
    """
    try:
        from price_store import list_symbols
        return [f"{s}.NS" for s in list_symbols() if not s.startswith("^")]
    except Exception:
        from screener import NSE_STOCKS
        return [s for s in NSE_STOCKS if not s.startswith("^")]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill free point-in-time annual fundamentals from "
                    "yfinance statements into data_cache/fundamental_snapshots.")
    parser.add_argument("--symbols", type=int, default=None,
                        help="number of universe symbols to backfill "
                             "(default: all local CSVs)")
    parser.add_argument("-s", "--symbol-list", type=str, default=None,
                        help="comma-separated symbols, e.g. RELIANCE.NS,TCS.NS")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be appended without writing")
    parser.add_argument("--buffer-days", type=int, default=FILING_BUFFER_DAYS,
                        help=f"filing buffer added to fiscal-year end "
                             f"(default {FILING_BUFFER_DAYS})")
    parser.add_argument("--no-skip-latest", action="store_true",
                        help="also keep the newest (possibly estimated) year")
    parser.add_argument("--force", action="store_true",
                        help="regenerate statement rows for the symbols")
    parser.add_argument("--sleep", type=float, default=0.2,
                        help="seconds between symbols (default 0.2)")
    args = parser.parse_args()

    if args.symbol_list:
        universe = [s.strip() for s in args.symbol_list.split(",") if s.strip()]
    else:
        universe = _default_universe()
        if args.symbols:
            universe = universe[:args.symbols]
    if not universe:
        print("No symbols to backfill.")
        return 1

    print("=" * 70)
    print(f"  FUNDAMENTAL HISTORY BACKFILL (yfinance statements)")
    print(f"  universe: {len(universe)} symbols | buffer: {args.buffer_days}d | "
          f"skip_latest: {not args.no_skip_latest} | mode: "
          f"{'dry-run' if args.dry_run else 'live'}")
    print("=" * 70)

    def report(position, total, summary):
        if summary.get("error"):
            print(f"  [{position:>3}/{total}] {summary['symbol']:<22} "
                  f"FAILED: {summary['error'][:80]}")
        elif summary.get("no_statement_data"):
            print(f"  [{position:>3}/{total}] {summary['symbol']:<22} "
                  f"no usable annual statements from provider")
        else:
            periods = ", ".join(summary["periods"]) or "none"
            print(f"  [{position:>3}/{total}] {summary['symbol']:<22} "
                  f"wrote {summary['wrote']:>2} new | "
                  f"periods [{periods}]")

    results = backfill_symbols(
        universe,
        buffer_days=args.buffer_days,
        skip_latest=not args.no_skip_latest,
        force=args.force,
        dry_run=args.dry_run,
        sleep_secs=args.sleep,
        progress=report,
    )

    print("\n  ---- summary ----")
    for key, value in results.items():
        if key in ("failed_symbols", "unchanged_symbols", "no_data_symbols"):
            continue
        print(f"    {key:<20}: {value}")
    if results["failed_symbols"]:
        print(f"    failed_symbols    : {', '.join(results['failed_symbols'])}")
    if results["no_data_symbols"]:
        print(f"    no-data symbols   : {', '.join(results['no_data_symbols'])}")
    if results["unchanged_symbols"]:
        print(f"    unchanged (sample): "
              f"{', '.join(results['unchanged_symbols'])}")
    return 0 if not results["failed_symbols"] else 2


if __name__ == "__main__":
    raise SystemExit(main())