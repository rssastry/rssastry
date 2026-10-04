"""Committed dashboard smoke test.

Boots a real render of the default "Dashboard" page headlessly through
Streamlit's AppTest and asserts it completes without exceptions or error
elements. The default page only reads local JSON/CSVs (no live quotes, no LLM,
no button clicks), so it is network-free and safe for CI. The Portfolio page is
NOT exercised here because it fetches live quotes via yfinance.
"""
import os
import pathlib

import pytest

pytest.importorskip("streamlit")

pytestmark = pytest.mark.slow
REPO = str(pathlib.Path(__file__).resolve().parent.parent)


def test_dashboard_default_page_renders_without_exceptions():
    from streamlit.testing.v1 import AppTest

    old = os.getcwd()
    os.chdir(REPO)
    try:
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=60)
        at.run(timeout=120)
    finally:
        os.chdir(old)
    assert len(at.exception) == 0, [e.value for e in at.exception]
    assert len(at.error) == 0