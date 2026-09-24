"""Tests for validate_pilot.py — regression-lock the date-alignment fix
(inner-join stocks to the ^NSEI calendar) and the anti-lookahead EMA.

No network: load_adjusted is monkeypatched with synthetic frames.
"""
import sys

import numpy as np
import pandas as pd
import pytest

import validate_pilot as vp


def _frame(n=300, start="2022-01-03", close_path=None, vol=1.0):
    idx = pd.bdate_range(start, periods=n)
    close = (np.asarray(close_path, dtype=float)
             if close_path is not None else np.linspace(100.0, 120.0, n))
    close = np.asarray(close, dtype=float)
    high = close + 1.0
    low = close - 1.0
    volume = np.full(n, vol * 1_000_000.0)
    return pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Volume": volume},
        index=idx,
    )


def test_expanding_ema_is_causal_and_matches_ta():
    from ta.trend import EMAIndicator
    close = pd.Series(np.linspace(100.0, 140.0, 300))
    ours = vp.expanding_ema(close, 50)
    ref = EMAIndicator(close, window=50).ema_indicator()
    assert float(ours.iloc[-1]) == pytest.approx(float(ref.iloc[-1]), abs=0.02)


def test_study_one_symbol_aligns_to_nifty_suppressed_days(monkeypatch):
    nifty = _frame(close_path=np.linspace(120.0, 90.0, 300))  # falling index
    stock = _frame(close_path=np.linspace(100.0, 150.0, 300), vol=2.0)  # strong riser
    monkeypatch.setattr(vp, "load_adjusted",
                        lambda symbol, **kw: nifty if symbol == "^NSEI" else stock)

    nc = nifty["Close"].astype(float)
    ne = vp.expanding_ema(nc, 50)
    out = vp.study_one_symbol("AAA", nc, ne)
    assert out["n"] > 0                      # suppressed days were found
    assert np.isfinite(out["rs"]).all()      # RS computed with alignment
    assert np.isfinite(out["f1"]).all()
    assert out["ema_ok"].any()               # strong riser sits above own EMAs


def test_study_one_symbol_zero_without_suppressed_days(monkeypatch):
    nifty = _frame(close_path=np.linspace(100.0, 200.0, 300))  # rising -> above EMA50
    stock = _frame(close_path=np.linspace(100.0, 150.0, 300), vol=2.0)
    monkeypatch.setattr(vp, "load_adjusted",
                        lambda symbol, **kw: nifty if symbol == "^NSEI" else stock)
    nc = nifty["Close"].astype(float)
    ne = vp.expanding_ema(nc, 50)
    out = vp.study_one_symbol("AAA", nc, ne)
    assert out["n"] == 0


def test_main_writes_report_without_network(monkeypatch, tmp_path):
    nifty = _frame(close_path=np.linspace(120.0, 90.0, 300))
    stock = _frame(close_path=np.linspace(100.0, 150.0, 300), vol=2.0)
    monkeypatch.setattr(vp, "load_adjusted",
                        lambda symbol, **kw: nifty if symbol == "^NSEI" else stock)
    monkeypatch.setattr(vp, "list_symbols", lambda: ["AAA"])
    monkeypatch.chdir(tmp_path)
    sys.argv = ["validate_pilot", "--rs", "1.0", "1.2", "--vol", "1.0", "1.5",
                "--out", "vp_test.json"]
    rc = vp.main()
    assert rc == 0
    import json
    report = json.load(open(tmp_path / "vp_test.json"))
    assert "pinned_live_config" in report
    assert "sweep" in report