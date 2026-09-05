"""Persist point-in-time fundamental observations for future validation."""
import json
import os
from datetime import date

import yfinance as yf


SNAPSHOT_DIR = os.path.join("data_cache", "fundamental_snapshots")


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
    try:
        fundamentals = yf.Ticker(symbol).info or {}
        if record_snapshot(symbol, fundamentals):
            return True, "captured"
        return False, "provider returned no scored fundamentals"
    except Exception as exc:
        return False, str(exc)[:160]


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