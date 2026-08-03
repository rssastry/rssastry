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
R:R Ratio   : {analysis.get('risk_reward_ratio','N/A')}
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


def send_portfolio_alert(result: dict):
    msg = format_portfolio_alert(result)
    ok  = send_telegram(msg)
    if ok:
        print(f"  Portfolio alert sent: "
              f"{result.get('symbol')} {result.get('action')}")


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