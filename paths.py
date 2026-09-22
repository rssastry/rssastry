"""paths.py — Where StockAnalysis keeps durable state.

Render free tier runs on an EPHEMERAL filesystem: every file the app writes
at runtime (Parquet caches, SQLite stores, price CSVs, JSON results, the
signals CSV) is wiped the moment the instance is recycled or redeployed, and
the web-service start command never launches the bundled daily scheduler.

To make state survive restarts / redeploys, point all writers AND readers at
durable storage with the ``SA_DATA_DIR`` environment variable — e.g. a Render
Persistent Disk mounted at /var/data on a paid instance::

    SA_DATA_DIR=/var/data

Everything below honors that override while remaining byte-for-byte
backward-compatible when it is unset (all paths stay working-directory /
repo-relative, exactly as before). Reading resolves to the same root as
writing, so the dashboard and the scanner always agree about where data lives.
"""
import os

_DATA_ROOT = os.environ.get("SA_DATA_DIR", "").strip()
# allow tests / containers to explicitly disable the override
if _DATA_ROOT.lower() in ("0", "false", "no", "off"):
    _DATA_ROOT = ""


def state_root() -> str:
    """Durable-state root; '' means the process's working directory."""
    return _DATA_ROOT


def path(rel: str) -> str:
    """Map a repo-relative state file (e.g. 'ai_analysis.json') onto its
    durable location. Byte-identical to ``rel`` when SA_DATA_DIR is unset."""
    if _DATA_ROOT:
        return os.path.join(_DATA_ROOT, rel)
    return rel


def dir_path(rel: str) -> str:
    """Like :func:`path` but also ensures the target directory exists."""
    resolved = path(rel)
    os.makedirs(resolved, exist_ok=True)
    return resolved