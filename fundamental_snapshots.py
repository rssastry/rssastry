"""Persist point-in-time fundamental observations for future validation."""
import json
import math
import os
from datetime import date, timedelta

import yfinance as yf


SNAPSHOT_DIR = os.path.join("data_cache", "fundamental_snapshots")

# Yahoo Finance ticker aliases for local NSE symbols whose company was renamed
# or de-merged on the provider after the symbol joined the universe. Records
# and files keep the LOCAL symbol so coverage / daily captures / validation
# stay keyed to the universe name; only the upstream fetch uses the alias:
#   TATAMOTORS  -> TMPV.NS       Tata Motors de-merged into TMCV.NS (CV /
#                                 legal successor "Tata Motors Limited") and
#                                 TMPV.NS (passenger vehicles). Yahoo assigned
#                                 the LEGACY composite symbol's 5y price chart
#                                 and annual statements to TMPV.NS, so it is
#                                 the only splice that keeps the long history
#                                 MIN_DAILY_HISTORY (260 bars) requires.
#   ADANITRANS  -> ADANIENSOL.NS  renamed Adani Energy Solutions Limited.
#   ZOMATO      -> ETERNAL.NS     renamed Eternal Limited.
# LTIM is intentionally absent: LTIMindtree has been delisted from the
# provider, which serves no info/statements/price for it or its predecessors
# (LTI / Mindtree), so no honest snapshot can be produced.
PROVIDER_TICKER_MAP = {
    "TATAMOTORS": "TMPV.NS",
    "ADANITRANS": "ADANIENSOL.NS",
    "ZOMATO": "ETERNAL.NS",
}


def resolve_provider_ticker(symbol: str) -> str:
    """Return the live provider ticker for a local universe symbol.

    Renamed / de-merged companies keep their local identity (files, records)
    but are fetched from the successor ticker the provider actually serves.
    Unmapped symbols are returned unchanged.
    """
    clean = symbol.upper().removesuffix(".NS")
    return PROVIDER_TICKER_MAP.get(clean, symbol)


def _path(symbol: str) -> str:
    clean = symbol.replace(".NS", "").replace("/", "_").replace(":", "_")
    return os.path.join(SNAPSHOT_DIR, f"{clean}.jsonl")


def record_snapshot(symbol: str, fundamentals: dict, as_of=None) -> bool:
    """Append one dated, normalized snapshot per symbol and calendar day."""
    if not fundamentals:
        return False
    capture_date = str(as_of or date.today())[:10]
    fields = (
        "sector", "industry", "marketCap", "enterpriseValue",
        "trailingPE", "forwardPE", "priceToBook", "returnOnEquity",
        "returnOnCapitalEmployed", "debtToEquity", "profitMargins",
        "operatingMargins", "freeCashflow", "earningsGrowth",
        "earningsQuarterlyGrowth", "heldPercentInsiders",
    )
    values = {key: fundamentals.get(key) for key in fields
              if fundamentals.get(key) is not None}
    if not values:
        return False
    record = {
        "as_of": capture_date,
        "symbol": symbol.replace(".NS", ""),
        "source": "yfinance.info",
        "values": values,
    }

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    path = _path(symbol)
    existing = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                existing = [json.loads(line) for line in handle if line.strip()]
        except (OSError, json.JSONDecodeError):
            existing = []
    existing = [item for item in existing if item.get("as_of") != capture_date]
    existing.append(record)
    existing.sort(key=lambda item: item.get("as_of", ""))
    with open(path, "w", encoding="utf-8") as handle:
        for item in existing:
            handle.write(json.dumps(item, default=str, sort_keys=True) + "\n")
    return True


def capture_symbol_snapshot(symbol: str) -> tuple[bool, str]:
    """Fetch current provider fundamentals and persist one daily snapshot."""
    provider_symbol = resolve_provider_ticker(symbol)
    try:
        fundamentals = yf.Ticker(provider_symbol).info or {}
        if record_snapshot(symbol, fundamentals):
            return True, "captured"
        return False, "provider returned no scored fundamentals"
    except Exception as exc:
        return False, str(exc)[:160]


def capture_snapshots(symbols: list[str]) -> dict:
    """Capture one current point-in-time snapshot per symbol."""
    captured = 0
    failed = 0
    for symbol in symbols:
        ok, _ = capture_symbol_snapshot(symbol)
        if ok:
            captured += 1
        else:
            failed += 1
    return {"requested": len(symbols), "captured": captured, "failed": failed}


def load_snapshots(symbol: str) -> list[dict]:
    """Load dated snapshots in ascending capture-date order."""
    path = _path(symbol)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def load_snapshot_as_of(symbol: str, as_of) -> dict | None:
    """Return the latest snapshot available on or before ``as_of``.

    A later snapshot is never allowed to answer an earlier historical signal;
    this is the key anti-lookahead contract for fundamental validation.
    Live-info debtToEquity readings are unit-normalized (see
    ``normalize_debt_equity``) so a provider unit artifact never makes the
    deterministic gate falsely reject a low-debt issuer.
    """
    cutoff = str(as_of)[:10]
    eligible = [item for item in load_snapshots(symbol)
                if str(item.get("as_of", ""))[:10] <= cutoff]
    if not eligible:
        return None
    selected = max(eligible, key=lambda item: str(item.get("as_of", "")))
    values = dict(selected.get("values") or {})
    # yfinance.info debtToEquity for NSE tickers is a broken unit (~70-800x);
    # statements-derived snapshots are already correct and never rescaled.
    if str(selected.get("source", "")) == "yfinance.info" and "debtToEquity" in values:
        values["debtToEquity"] = normalize_debt_equity(values["debtToEquity"])
    values["symbol"] = selected.get("symbol", symbol.replace(".NS", ""))
    values["snapshot_as_of"] = str(selected.get("as_of", ""))[:10]
    values["snapshot_source"] = str(selected.get("source", "yfinance.info"))
    if selected.get("period_end"):
        values["period_end"] = str(selected.get("period_end", ""))[:10]
    return values


# ── NSE debtToEquity unit artifact ──────────────────────────────────
# yfinance.Ticker.info returns `debtToEquity` for most NSE tickers in a
# unit that is roughly 70-800x the true ratio (checked 2026-09: TCS 10.21
# vs 0.099, ITC 3.29 vs 0.004, DABUR 10.91 vs 0.088, HINDUNILVR 3.02 vs
# 0.033, LT 97.6 vs 1.36, NYKAA 82.8 vs 1.01). The annual-statement
# snapshots carry the correct value and are therefore preferred wherever
# they exist. When ONLY a live-info reading is available, any value above
# NSE_DEBT_UNIT_ARTIFACT_THRESHOLD is treated as the documented unit
# artifact and scaled by NSE_DEBT_UNIT_SCALE (a genuine D/E above 5.0 for a
# non-financial NSE issuer is very rare, and sector thresholds already
# admit Financial Services up to 8.0).
NSE_DEBT_UNIT_ARTIFACT_THRESHOLD = 5.0
NSE_DEBT_UNIT_SCALE = 100.0


def normalize_debt_equity(value) -> float | None:
    """Return a trustworthy D/E for the fundamental gate.

    Values at or below the artifact threshold are returned unchanged. Larger
    raw readings are scaled by NSE_DEBT_UNIT_SCALE only when the scaled
    result is itself plausible (<= threshold); otherwise the raw value is
    kept, so a genuinely over-levered balance sheet is never hidden.
    """
    if value is None:
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(raw) or raw <= 0:
        return None
    if raw > NSE_DEBT_UNIT_ARTIFACT_THRESHOLD:
        scaled = raw / NSE_DEBT_UNIT_SCALE
        if scaled <= NSE_DEBT_UNIT_ARTIFACT_THRESHOLD:
            return round(scaled, 6)
    return raw


# Quality/balance-sheet fields the statements snapshots report in the
# correct unit (D/E, ROE, ROCE, FCF) or that live info often drops entirely.
_STATEMENT_RELIABLE_KEYS = (
    "returnOnEquity", "returnOnCapitalEmployed", "debtToEquity",
    "freeCashflow", "earningsGrowth", "earningsQuarterlyGrowth",
)


def merge_fundamental_snapshots(symbol: str, live: dict | None = None,
                                as_of=None) -> dict:
    """Best-available fundamentals: statements quality + live valuation.

    The live scan feeds ``yfinance.Ticker.info`` straight into the
    fundamental gate and the quality scorers, but for NSE tickers that dict
    carries an inflated ``debtToEquity`` (unit bug) and often omits
    ROE/ROCE/FCF. This merges the freshly captured ``live`` record with the
    richer, unit-correct annual-statement snapshot already stored per
    symbol, so the deterministic gate reads trustworthy leverage and
    profitability evidence while still using the live quote for
    price-sensitive multiples (P/E, P/B, market cap, sector).

    Field policy:
      * ``debtToEquity`` — statements value always wins (live info is broken
        for NSE); a live-only reading is unit-normalized.
      * other quality fields (ROE/ROCE/FCF/growth) — live wins when present,
        statements fill gaps.
      * valuation / price-sensitive keys (P/E, P/B, marketCap, sector,
        industry, margins) — always the live quote when available.

    ``as_of`` caps which stored snapshots may be consulted (anti-lookahead),
    making this helper safe for historical validation runs too.
    """
    merged = dict(live or {})
    records = load_snapshots(symbol)
    if as_of is not None:
        cutoff = str(as_of)[:10]
        records = [rec for rec in records
                   if str(rec.get("as_of", ""))[:10] <= cutoff]

    def _latest(source: str):
        picked = [rec for rec in records
                  if str(rec.get("source", "")) == source]
        if not picked:
            return None
        return max(picked, key=lambda rec: str(rec.get("as_of", "")))

    stmt = _latest("yfinance.statements")
    info = _latest("yfinance.info")

    # A historical call without a live dict still enjoys the stored snapshot.
    if not merged and info is not None:
        merged = dict(info.get("values") or {})

    if stmt is not None:
        stmt_values = stmt.get("values") or {}
        for key in _STATEMENT_RELIABLE_KEYS:
            value = stmt_values.get(key)
            if value is None:
                continue
            if key == "debtToEquity":
                merged[key] = value  # provider unit bug: statements wins
            elif merged.get(key) is None:
                merged[key] = value

    if info is not None:
        info_values = info.get("values") or {}
        for key in _STATEMENT_RELIABLE_KEYS:
            if merged.get(key) is None and info_values.get(key) is not None:
                merged[key] = info_values[key]

    # price-sensitive / profile fields come from the live quote when present
    if info is not None:
        info_values = info.get("values") or {}
        for key in ("trailingPE", "forwardPE", "priceToBook", "marketCap",
                    "enterpriseValue", "sector", "industry",
                    "heldPercentInsiders", "profitMargins",
                    "operatingMargins"):
            value = info_values.get(key)
            if value is not None:
                merged[key] = value

    # statements-derived D/E is already correct; normalizing it is a no-op.
    if "debtToEquity" in merged:
        merged["debtToEquity"] = normalize_debt_equity(merged["debtToEquity"])

    merged["symbol"] = symbol.replace(".NS", "")
    merged["data_quality"] = ("statements+live" if (stmt and info)
                              else ("statements" if stmt else "live_info"))
    as_of_dates = [str(rec.get("as_of", ""))[:10] for rec in records
                   if rec.get("as_of")]
    if as_of_dates:
        merged["snapshot_as_of"] = max(as_of_dates)
    return merged


def apply_price_valuation(fundamentals: dict, close_price) -> dict:
    """Fill point-in-time P/E and P/B proxies for statement-derived snapshots.

    Annual statements contain EPS / BVPS but no market prices (and the price
    the buy logic sees is the price on the signal bar, not today's). When the
    snapshot came from `yfinance.statements`, derive trailing P/E and P/B from
    the signal-bar close times the fiscal-year per-share numbers. Live
    `yfinance.info` snapshots already carry provider-computed ratios and are
    never overridden. ``fundamentals`` is mutated and returned.
    """
    if not fundamentals:
        return fundamentals
    if fundamentals.get("snapshot_source") != "yfinance.statements":
        return fundamentals
    try:
        price = float(close_price)
    except (TypeError, ValueError):
        return fundamentals
    if not math.isfinite(price) or price <= 0:
        return fundamentals
    eps = fundamentals.get("eps")
    if eps is not None and fundamentals.get("trailingPE") is None \
            and float(eps) > 0:
        try:
            fundamentals["trailingPE"] = round(float(price) / float(eps), 4)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    bvps = fundamentals.get("bvps")
    if bvps is not None and fundamentals.get("priceToBook") is None \
            and float(bvps) > 0:
        try:
            fundamentals["priceToBook"] = round(float(price) / float(bvps), 4)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return fundamentals


def snapshot_coverage(symbols: list[str]) -> dict:
    """Summarize stored snapshot coverage for a validation universe."""
    today = date.today()
    covered = []
    missing = []
    stale = []
    first_dates = []
    latest_dates = []
    sources = {}
    backfill_ends = []
    for symbol in symbols:
        records = load_snapshots(symbol)
        for record in records:
            source = str(record.get("source", "yfinance.info"))
            sources[source] = sources.get(source, 0) + 1
            if source == "yfinance.statements" and record.get("period_end"):
                backfill_ends.append(str(record.get("period_end"))[:10])
        if not records:
            missing.append(symbol)
            continue
        covered.append(symbol)
        dates = sorted(str(item.get("as_of", ""))[:10]
                       for item in records if item.get("as_of"))
        if not dates:
            missing.append(symbol)
            continue
        first_dates.append(dates[0])
        latest_dates.append(dates[-1])
        try:
            if today - date.fromisoformat(dates[-1]) > timedelta(days=2):
                stale.append(symbol)
        except ValueError:
            stale.append(symbol)
    return {
        "symbols_requested": len(symbols),
        "symbols_with_snapshots": len(covered),
        "coverage_pct": round(100 * len(covered) / len(symbols), 1)
        if symbols else 0.0,
        "missing_symbols": missing,
        "stale_symbols": stale,
        "oldest_snapshot": min(first_dates) if first_dates else None,
        "newest_snapshot": max(latest_dates) if latest_dates else None,
        "snapshots_by_source": sources,
        "backfill_period_end_min": min(backfill_ends) if backfill_ends else None,
        "backfill_period_end_max": max(backfill_ends) if backfill_ends else None,
    }