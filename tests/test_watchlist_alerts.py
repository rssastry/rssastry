"""Tests for alerts.check_watchlist_price_alerts and the promotable-watchlist
section of format_morning_summary (the watchlist improvements). Network-free --
live quotes and Telegram are monkeypatched."""
import alerts


def _pick(symbol="COALINDIA", level=430.0, style="swing", rec="WATCHLIST",
          promotable=False):
    p = {
        "symbol": symbol,
        "trading_style": style,
        "recommendation": rec,
        "entry_price": {"ideal": 424.0, "range_low": 420.0, "range_high": 430.0},
        "alert_on_price": {"buy_alert_at": level,
                           "sell_alert_at": None, "stop_alert_at": None},
    }
    if promotable:
        p["watchlist_promotable"] = True
    return p


def test_watchlist_alert_fires_once_per_level(monkeypatch, tmp_path):
    analysis = {"swing": [_pick()]}
    sent = []
    monkeypatch.setattr(alerts, "send_telegram",
                        lambda msg: sent.append(msg) or True)
    monkeypatch.setattr(alerts, "get_live_price_now", lambda sym: 430.0)
    monkeypatch.setattr(alerts, "_watchlist_state_file",
                        lambda: str(tmp_path / "fired.json"))
    res1 = alerts.check_watchlist_price_alerts(analysis)
    assert res1["fired"] == ["COALINDIA"]
    assert len(sent) == 1
    # Second run: the level already fired -> no duplicate alert.
    res2 = alerts.check_watchlist_price_alerts(analysis)
    assert res2["fired"] == []
    assert len(sent) == 1


def test_watchlist_alert_skips_candidates_without_level(monkeypatch, tmp_path):
    analysis = {"swing": [_pick(level=None)]}
    monkeypatch.setattr(alerts, "_watchlist_state_file",
                        lambda: str(tmp_path / "fired.json"))
    res = alerts.check_watchlist_price_alerts(analysis)
    assert res["checked"] == 0
    assert res["fired"] == []


def test_morning_summary_lists_promotable_watchlist_only():
    analysis = {
        "swing": [_pick(promotable=True),
                  _pick(symbol="TCS", level=3000.0, promotable=False)],
    }
    msg = alerts.format_morning_summary(analysis)
    section = msg.split("BLOCKED ONLY BY MARKET REGIME")[1]
    assert "COALINDIA" in section
    assert "TCS" not in section