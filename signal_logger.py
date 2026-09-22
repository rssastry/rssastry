import csv
import os
from datetime import datetime, timezone

import paths

LOG_FILE = paths.path("signals_log.csv")

FIELDNAMES = [
    "ts", "symbol", "source", "price", "atr", "qty", "stop_loss", "note"
]


def _ensure_header(path=LOG_FILE):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def log_signal(symbol: str, price: float, atr: float = None, qty: int = 0,
               stop_loss: float = None, source: str = "suggestion", note: str = ""):
    """Append a signal record to CSV for later ML training or auditing."""
    _ensure_header()
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "source": source,
        "price": price,
        "atr": atr,
        "qty": qty,
        "stop_loss": stop_loss,
        "note": note,
    }
    try:
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writerow(row)
        return True
    except Exception:
        return False
