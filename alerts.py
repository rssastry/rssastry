"""
alerts.py — Alert System
Sends Buy/Sell/Hold alerts via Telegram and Email
"""

import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv
import requests
import warnings
warnings.filterwarnings("ignore")

load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GMAIL_USER       = os.getenv("GMAIL_USER")
GMAIL_PASSWORD   = os.getenv("GMAIL_PASSWORD")


# ─────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────
def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("  Telegram not configured in .env")
        return False
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML"
        }
        r = requests.post(url, data=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"  Telegram error: {e}")
        return False


def format_buy_alert(analysis: dict) -> str:
    ind  = analysis.get("indicators", {})
    ep   = analysis.get("entry_price", {})
    tp   = analysis.get("target_prices", {})
    ap   = analysis.get("alert_on_price", {})
    rec  = analysis.get("recommendation", "")
    conf = analysis.get("confidence_score", 0)
    style= analysis.get("trading_style", "").upper()
    emoji= "BUY" if rec == "BUY" else "SELL" if rec == "SELL" else "HOLD"

    signals_text = ""
    for s in analysis.get("key_signals", []):
        signals_text += f"  - {s}\n"

    return f"""
<b>{emoji} ALERT - {analysis.get('symbol','')} [{style}]</b>
----------------------------------------
Entry Zone  : Rs.{ep.get('range_low',0)} - Rs.{ep.get('range_high',0)}
Ideal Entry : Rs.{ep.get('ideal',0)}
Target 1    : Rs.{tp.get('T1',0)}
Target 2    : Rs.{tp.get('T2',0)}
Target 3    : Rs.{tp.get('T3',0)}
Stop Loss   : Rs.{analysis.get('stop_loss',0)}
R:R to T1    : {analysis.get('risk_reward_t1','N/A')}
R:R to T2    : {analysis.get('risk_reward_ratio','N/A')}
Hold        : {analysis.get('hold_duration','N/A')}
Confidence  : {conf}/100
Risk Level  : {analysis.get('risk_level','N/A')}
----------------------------------------
Key Signals:
{signals_text}
Summary: {analysis.get('analysis_summary','')}
----------------------------------------
Buy alert at  : Rs.{ap.get('buy_alert_at',0)}
Sell alert at : Rs.{ap.get('sell_alert_at',0)}
Stop alert at : Rs.{ap.get('stop_alert_at',0)}
Time: {datetime.now().strftime('%d-%b-%Y %H:%M')}
""".strip()


def format_portfolio_alert(result: dict) -> str:
    action  = result.get("action", "")
    urgency = result.get("urgency", "")
    pnl     = result.get("pnl_percent", 0)
    pnl_dir = "UP" if pnl >= 0 else "DOWN"

    return f"""
<b>PORTFOLIO ALERT - {result.get('symbol','')} : {action}</b>
----------------------------------------
Urgency        : {urgency}
Current P&L    : {pnl:+.2f}% ({pnl_dir})
Revised Target : Rs.{result.get('revised_target',0)}
Revised SL     : Rs.{result.get('revised_stop_loss',0)}
Risk Flag      : {result.get('risk_flag','None')}
----------------------------------------
Reasoning: {result.get('reasoning','')}
Time: {datetime.now().strftime('%d-%b-%Y %H:%M')}
""".strip()


def format_morning_summary(all_analysis: dict) -> str:
    date_str = datetime.now().strftime('%d %b %Y')
    lines    = [
        f"<b>MORNING PICKS - {date_str}</b>",
        "----------------------------------------"
    ]

    for style, picks in all_analysis.items():
        buys = [p for p in picks if p.get("recommendation") == "BUY"]
        if not buys:
            continue
        lines.append(f"\n<b>{style.upper()}</b>")
        for i, p in enumerate(buys[:5], 1):
            ep = p.get("entry_price", {})
            tp = p.get("target_prices", {})
            lines.append(
                f"  {i}. <b>{p['symbol']}</b> | "
                f"Entry Rs.{ep.get('ideal',0)} | "
                f"T1 Rs.{tp.get('T1',0)} | "
                f"SL Rs.{p.get('stop_loss',0)} | "
                f"Conf {p.get('confidence_score',0)}%"
            )

    lines.append(f"\nTime: {datetime.now().strftime('%H:%M IST')}")

    # Watchlist that would qualify but for the market-regime filter: the scan
    # tags these with watchlist_promotable (e.g. COALINDIA-type names).
    promote = [p for style, picks in all_analysis.items()
               if isinstance(picks, list)
               for p in picks if isinstance(p, dict) and p.get("watchlist_promotable")]
    if promote:
        lines.append("\n<b>WATCHLIST - BLOCKED ONLY BY MARKET REGIME</b>")
        for i, p in enumerate(promote[:8], 1):
            ep = p.get("entry_price", {})
            lines.append(
                f"  {i}. <b>{p.get('symbol','')}</b> | "
                f"Entry Rs.{ep.get('ideal',0)} | "
                f"Style {p.get('trading_style', p.get('style',''))}"
            )
        lines.append("  (NIFTY below EMA50 -- trade only with reduced size)")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Email
# ─────────────────────────────────────────────
def send_email(subject: str, body_html: str, to_email: str = None) -> bool:
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print("  Gmail not configured in .env")
        return False
    to = to_email or GMAIL_USER
    try:
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = GMAIL_USER
        msg["To"]      = to
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, to, msg.as_string())
        return True
    except Exception as e:
        print(f"  Email error: {e}")
        return False


# ─────────────────────────────────────────────
# Convenience senders
# ─────────────────────────────────────────────
def send_buy_alert(analysis: dict):
    msg = format_buy_alert(analysis)
    ok  = send_telegram(msg)
    if ok:
        print(f"  Telegram alert sent: "
              f"{analysis.get('symbol')} {analysis.get('recommendation')}")


# ─────────────────────────────────────────────
# Watchlist buy-level monitoring
# ─────────────────────────────────────────────
def get_live_price_now(symbol: str, interval: str = "1m") -> float:
    """Live intraday quote for one symbol; 0.0 on any failure."""
    try:
        from fundamental_snapshots import resolve_provider_ticker
        import yfinance as yf
        local = symbol if ".NS" in symbol else symbol + ".NS"
        df = yf.Ticker(resolve_provider_ticker(local)).history(
            period="1d", interval=interval)
        if df is not None and not df.empty:
            return round(float(df["Close"].iloc[-1]), 2)
    except Exception:
        pass
    return 0.0


def _watchlist_state_file() -> str:
    import paths
    from config import CACHE_DIR
    return os.path.join(CACHE_DIR, "watchlist_alerts_fired.json")


def check_watchlist_price_alerts(analysis: dict = None, tolerance_pct: float = 1.0) -> dict:
    """Fire ONE-TIME Telegram alerts when a candidate trades at its computed
    ``buy_alert_at`` level.

    The analysis already produces buy levels for every candidate but nothing
    monitored them -- users were left to eyeball watchlists manually (the
    COALINDIA experience). This closes that gap. Alert state is persisted
    under CACHE_DIR so each level fires only once until the level changes.

    Returns {"fired": [symbols], "checked": n, "failed": [symbols]}.
    """
    import time
    import paths
    if analysis is None:
        try:
            with open(paths.path("ai_analysis.json")) as fh:
                data = json.load(fh)
            analysis = data.get("analysis", {})
        except Exception:
            return {"fired": [], "checked": 0, "failed": [], "error": "no analysis"}

    candidates: dict = {}
    for style, picks in analysis.items():
        if not isinstance(picks, list):
            continue
        for p in picks:
            if not isinstance(p, dict):
                continue
            level = (p.get("alert_on_price") or {}).get("buy_alert_at")
            sym = p.get("symbol")
            try:
                level_f = float(level)
            except (TypeError, ValueError):
                level_f = 0.0
            if not sym or level_f <= 0:
                continue
            candidates.setdefault(sym, {
                "level": level_f,
                "style": p.get("trading_style") or p.get("style", ""),
                "rec": p.get("recommendation", ""),
            })

    state_file = _watchlist_state_file()
    fired_state = {}
    if os.path.exists(state_file):
        try:
            with open(state_file) as fh:
                fired_state = json.load(fh)
        except Exception:
            fired_state = {}

    fired, failed = [], []
    for sym, info in candidates.items():
        live = get_live_price_now(sym)
        if live <= 0:
            failed.append(sym)
            continue
        hit = abs(live - info["level"]) / info["level"] <= tolerance_pct / 100.0
        key = f"{sym}:{info['style']}:{info['level']}"
        if hit and not fired_state.get(key):
            send_telegram(
                f"<b>WAIT BUY LEVEL HIT - {sym}</b>\n"
                f"Live Rs.{live} is at your buy level Rs.{info['level']}\n"
                f"Watchlist rec: {info['rec']} | style: {info['style']}\n"
                f"Time: {datetime.now().strftime('%H:%M IST')}"
            )
            fired_state[key] = datetime.now().isoformat(timespec="seconds")
            fired.append(sym)
        time.sleep(0.4)

    try:
        parent = os.path.dirname(state_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(state_file, "w") as fh:
            json.dump(fired_state, fh, indent=2, sort_keys=True)
    except Exception:
        pass
    return {"fired": fired, "checked": len(candidates), "failed": failed}


def send_portfolio_alert(result: dict):
    msg = format_portfolio_alert(result)
    ok  = send_telegram(msg)
    if ok:
        print(f"  Portfolio alert sent: "
              f"{result.get('symbol')} {result.get('action')}")


# ─────────────────────────────────────────────
# Open-position stop / target monitoring
# ─────────────────────────────────────────────
def _position_monitor_state_file() -> str:
    from config import CACHE_DIR
    return os.path.join(CACHE_DIR, "position_alerts_fired.json")


def _load_portfolio_dict() -> dict:
    import paths
    try:
        with open(paths.path("portfolio.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def position_monitor_status(portfolio: dict = None, quote_fn=None) -> list:
    """Per-holding live status against the stored stop/target plan. No alerts.

    Each row: symbol, style, quantity, buy_price, stop_loss, target, live_price,
    pnl_pct, dist_to_stop_pct, dist_to_target_pct, status, trigger_level.
    status is STOP_HIT / TARGET_HIT / OK / NO_QUOTE.
    """
    quote_fn = quote_fn or get_live_price_now
    portfolio = portfolio if portfolio is not None else _load_portfolio_dict()
    rows = []
    for h in portfolio.get("holdings", []):
        symbol = str(h.get("symbol", "")).upper().replace(".NS", "")
        try:
            buy_price = float(h.get("buy_price", 0) or 0)
            qty = int(h.get("quantity", 0) or 0)
            stop = float(h.get("stop_loss", 0) or 0)
            target = float(h.get("target", 0) or 0)
        except (TypeError, ValueError):
            continue
        style = str(h.get("style") or "positional").lower()
        live = quote_fn(symbol)
        row = {
            "symbol": symbol, "style": style, "quantity": qty,
            "buy_price": buy_price, "stop_loss": stop, "target": target,
            "live_price": live,
        }
        if live <= 0:
            row.update({"status": "NO_QUOTE", "pnl_pct": None,
                        "dist_to_stop_pct": None, "dist_to_target_pct": None,
                        "trigger_level": None})
        else:
            pnl_pct = (live / buy_price - 1) * 100 if buy_price else 0.0
            row["pnl_pct"] = round(pnl_pct, 2)
            row["dist_to_stop_pct"] = (
                round((live - stop) / live * 100, 2) if stop and stop > 0 else None)
            row["dist_to_target_pct"] = (
                round((target - live) / live * 100, 2) if target and target > 0 else None)
            if stop and stop > 0 and live <= stop:
                row["status"], row["trigger_level"] = "STOP_HIT", stop
            elif target and target > 0 and live >= target:
                row["status"], row["trigger_level"] = "TARGET_HIT", target
            else:
                row["status"], row["trigger_level"] = "OK", None
        rows.append(row)
    return rows


def check_position_alerts(portfolio: dict = None, quote_fn=None) -> dict:
    """Fire ONE-TIME Telegram alerts when an open holding trades at its stored
    stop-loss or target.

    State persists under CACHE_DIR so each level fires only once until the
    level changes (mirrors the watchlist-buy-level alert pattern). Call this
    from the 12:30 / 15:00 scheduled checks, the morning scan, or
    `python run.py monitor`.

    Returns {"fired": [...], "checked": n, "failed": [symbols]}.
    """
    rows = position_monitor_status(portfolio=portfolio, quote_fn=quote_fn)
    state_file = _position_monitor_state_file()
    fired_state = {}
    if os.path.exists(state_file):
        try:
            with open(state_file) as fh:
                fired_state = json.load(fh)
        except Exception:
            fired_state = {}

    fired, failed = [], []
    for r in rows:
        if r["status"] in ("STOP_HIT", "TARGET_HIT"):
            level = r.get("trigger_level")
            key = f"{r['symbol']}:{r['status'].lower()}:{level}"
            if not fired_state.get(key):
                label = "STOP-LOSS" if r["status"] == "STOP_HIT" else "TARGET"
                send_telegram(
                    f"<b>{r['symbol']} {label} HIT</b>\n"
                    f"Entry Rs.{r['buy_price']} x {r['quantity']} "
                    f"[{r['style']}]\n"
                    f"Live Rs.{r['live_price']} "
                    f"(P&L {r['pnl_pct']:+.2f}% from entry)\n"
                    f"{label} level Rs.{level:g}\n"
                    f"Time: {datetime.now().strftime('%H:%M IST')}"
                )
                fired_state[key] = datetime.now().isoformat(timespec="seconds")
                fired.append(f"{r['symbol']}:{r['status']}")
        elif r["status"] == "NO_QUOTE":
            failed.append(r["symbol"])

    try:
        parent = os.path.dirname(state_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(state_file, "w") as fh:
            json.dump(fired_state, fh, indent=2, sort_keys=True)
    except Exception:
        pass

    return {"fired": fired, "checked": len(rows), "failed": failed}


def send_morning_summary(all_analysis: dict):
    msg = format_morning_summary(all_analysis)
    ok  = send_telegram(msg)
    if ok:
        print("  Morning summary sent to Telegram")


def send_price_alert(symbol: str, price: float, alert_type: str):
    label = {"BUY": "BUY LEVEL", "SELL": "SELL TARGET", "STOP": "STOP LOSS"}.get(
        alert_type, alert_type
    )
    msg = (
        f"<b>PRICE ALERT - {symbol}</b>\n"
        f"Price Rs.{price:.2f} has reached {label}\n"
        f"Time: {datetime.now().strftime('%d-%b-%Y %H:%M')}"
    )
    send_telegram(msg)


# ─────────────────────────────────────────────
# Test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    test_msg = (
        f"<b>Stock Analyst Bot Connected!</b>\n"
        f"System is live as of "
        f"{datetime.now().strftime('%d-%b-%Y %H:%M')}"
    )
    ok = send_telegram(test_msg)
    print("Telegram test:", "OK" if ok else "Failed - check .env")