"""console.py — Keep Python text streams from crashing scan logs on Windows.

On Windows, ``sys.stdout``/``sys.stderr`` default to the locale codec
(cp1252, alias ``charmap``) whenever they are pipes/logs rather than the
interactive terminal. Several scan modules print warning/status symbols —
⚠ (U+26A0), ✅, ❌, ₹, … — that cp1252 cannot encode, so an ordinary
``print()`` raises ``UnicodeEncodeError`` and aborts the scan. This is the
source of the dashboard "Run Morning Scan" error::

    Error: 'charmap' codec can't encode character '\\u26a0' in position 2 ...

``scripts/run_scan_job.ps1`` already sets ``PYTHONIOENCODING=utf-8`` before
Python starts, but that environment variable cannot help a process that is
already running (the Streamlit dashboard, or an IDE terminal launch).
:func:`force_utf8_stdio` fixes stdout/stderr in-process, after the streams
were opened, so a scan never dies on a console/logging print.
"""

import sys


def force_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 so ``print()`` never raises.

    Best effort: if a stream is closed, detached or uses an exotic wrapper
    that cannot be reconfigured, the process simply keeps its current
    settings — the guard exists only to make logging output non-fatal.
    ``errors="backslashreplace"`` guarantees that even a character the
    underlying codec cannot represent is escaped instead of raised.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass