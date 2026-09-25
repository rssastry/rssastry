"""
scheduler.py — Daily Run Scheduler
Orchestrates the full pipeline automatically
"""

import schedule
import time
import json
import os
from datetime import datetime
from screener import StockScreener
from ai_analyst import AIAnalyst
from portfolio import show_portfolio, run_hold_sell_analysis
from alerts import send_morning_summary, send_portfolio_alert, send_telegram
import paths
import warnings
warnings.filterwarnings("ignore")


def is_market_day() -> bool:
    """Skip weekends AND NSE holidays."""
    from config import NSE_HOLIDAYS_2026
    today = datetime.today()
    if today.weekday() >= 5:
        return False
    # Check NSE holiday list
    date_str = today.strftime("%Y-%m-%d")
    if date_str in NSE_HOLIDAYS_2026:
        return False
    return True


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def get_live_price(symbol: str) -> float:
    """Get the current intraday price using 1-minute bars."""
    try:
        import yfinance as yf
        from fundamental_snapshots import resolve_provider_ticker
        local_sym = symbol if ".NS" in symbol else symbol + ".NS"
        sym = resolve_provider_ticker(local_sym)
        df = yf.Ticker(sym).history(period="1d", interval="1m")
        if df is not None and not df.empty:
            return round(float(df["Close"].iloc[-1]), 2)
        return 0.0
    except Exception:
        return 0.0


# ─────────────────────────────────────────────
# Job 1 — Post-Close Scan (15:45 PM)
# Runs AFTER market close so daily volume is confirmed.
# ─────────────────────────────────────────────
def job_morning_scan():
    if not is_market_day():
        log("Weekend or NSE holiday — skipping scan.")
        return

    log("Starting post-close scan...")
    send_telegram(
        f"<b>Market scan starting...</b>\n"
        f"{datetime.now().strftime('%d %b %Y, %H:%M IST')}"
    )

    try:
        # Step 0: Refresh the local price files (raw_data/prices/*.csv). Best
        # effort — a failed provider fetch must not block the scan itself.
        try:
            from update_price_files import update_all_price_files
            res = update_all_price_files()
            log(f"Price files: {res['updated']} updated, "
                f"{res['backfilled']} new, {res['merged']} gap-filled, "
                f"{res['unchanged']} unchanged, {res['failed']} failed")
        except Exception as e:
            log(f"Price file update skipped: {e}")

        # Capture fundamentals after the close so the snapshot date matches
        # the completed price bar used by the screener and future validation.
        try:
            from fundamental_snapshots import capture_snapshots
            from screener import NSE_STOCKS
            snapshot_res = capture_snapshots(NSE_STOCKS)
            log(f"Fundamental snapshots: {snapshot_res['captured']} captured, "
                f"{snapshot_res['failed']} failed")
        except Exception as e:
            log(f"Fundamental snapshot capture skipped: {e}")

        # Step 1: Screen
        screener = StockScreener()
        results  = screener.screen(
            styles=["intraday", "swing", "positional"],
            top_n=15
        )
        log("Screener done. Running AI analysis...")

        # Step 2: AI analyze
        analyst  = AIAnalyst()
        analysis = analyst.analyze_top_picks(results, delay_seconds=3)

        # Step 2b: Close the loop - journal today's decisions, resolve what
        # has matured, refresh market context and discipline reports (best
        # effort; the scan itself must never depend on these).
        try:
            from run import _bible_journal_default
            _bible_journal_default()
        except Exception as e:
            log(f"Decision journal step skipped: {e}")
        try:
            from market_breadth import build_market_snapshot
            build_market_snapshot()
            from discipline import build_discipline_report
            build_discipline_report()
            log("Market context + discipline reports refreshed.")
        except Exception as e:
            log(f"Context refresh skipped: {e}")

        # Step 3: Send morning summary
        send_morning_summary(analysis)
        log("Post-close scan complete.")

    except Exception as e:
        log(f"Post-close scan failed: {e}")
        send_telegram(f"<b>Post-close scan error:</b> {e}")


# ─────────────────────────────────────────────
# Job 2 — Midday Portfolio Review (12:30 PM)
# ─────────────────────────────────────────────
def job_midday_review():
    if not is_market_day():
        return

    log("Midday portfolio review...")
    try:
        results = run_hold_sell_analysis()
        for r in results:
            # Alert only urgent actions
            if r.get("action") in ("FULL_SELL", "PARTIAL_SELL") or \
               r.get("urgency") == "Immediate":
                send_portfolio_alert(r)

        log(f"Midday review done. {len(results)} holdings checked.")

    except Exception as e:
        log(f"Midday review failed: {e}")


# ─────────────────────────────────────────────
# Job 3 — Pre-Close SL Check (3:00 PM)
# ─────────────────────────────────────────────
def job_preclose_check():
    if not is_market_day():
        return

    log("Pre-close stop loss check...")
    try:
        # Watchlist buy-level alerts: fire once when a watchlist name trades at
        # its computed buy level (automates the manual COALINDIA-style tracking).
        try:
            from alerts import check_watchlist_price_alerts
            _res = check_watchlist_price_alerts()
            if _res.get("fired"):
                log(f"Watchlist buy-level alerts fired: {', '.join(_res['fired'])}")
        except Exception as exc:
            log(f"Watchlist alert check skipped: {exc}")

        _portfolio_file = paths.path("portfolio.json")
        if not os.path.exists(_portfolio_file):
            log("No portfolio file found.")
            return

        with open(_portfolio_file) as f:
            portfolio = json.load(f)

        from indicators import IndicatorEngine

        for h in portfolio.get("holdings", []):
            symbol = h["symbol"]

            # Use live intraday price for stop-loss/target alerts
            cmp = get_live_price(symbol)
            if cmp <= 0:
                # Fallback to daily-bar close if live quote unavailable
                engine = IndicatorEngine(symbol + ".NS")
                if not engine.fetch():
                    continue
                ind = engine.compute_all()
                cmp = ind.get("current_price", 0)

            sl  = h.get("stop_loss", 0)
            tgt = h.get("target", 0)

            if cmp > 0 and cmp <= sl:
                send_telegram(
                    f"<b>STOP LOSS HIT - {symbol}</b>\n"
                    f"CMP Rs.{cmp} has hit SL Rs.{sl}\n"
                    f"Consider exiting immediately!\n"
                    f"Time: {datetime.now().strftime('%H:%M IST')}"
                )
                log(f"SL alert sent for {symbol}")

            elif cmp > 0 and cmp >= tgt:
                send_telegram(
                    f"<b>TARGET HIT - {symbol}</b>\n"
                    f"CMP Rs.{cmp} has reached Target Rs.{tgt}\n"
                    f"Consider booking profits!\n"
                    f"Time: {datetime.now().strftime('%H:%M IST')}"
                )
                log(f"Target alert sent for {symbol}")

        log("Pre-close check done.")

    except Exception as e:
        log(f"Pre-close check failed: {e}")


# ─────────────────────────────────────────────
# Job 4 — EOD Summary (4:00 PM)
# ─────────────────────────────────────────────
def job_eod_summary():
    if not is_market_day():
        return

    log("Sending EOD summary...")
    try:
        # Build portfolio P&L summary
        pnl_text = ""
        _portfolio_file = paths.path("portfolio.json")
        if os.path.exists(_portfolio_file):
            with open(_portfolio_file) as f:
                portfolio = json.load(f)
            holdings = portfolio.get("holdings", [])
            if holdings:
                from indicators import IndicatorEngine
                total_inv = 0
                total_cur = 0
                for h in holdings:
                    engine = IndicatorEngine(h["symbol"] + ".NS")
                    if engine.fetch():
                        ind = engine.compute_all()
                        cmp = ind.get("current_price", h["buy_price"])
                    else:
                        cmp = h["buy_price"]
                    total_inv += h["buy_price"] * h["quantity"]
                    total_cur += cmp * h["quantity"]
                total_pnl     = total_cur - total_inv
                total_pnl_pct = (total_pnl / total_inv * 100) if total_inv else 0
                direction     = "UP" if total_pnl >= 0 else "DOWN"
                pnl_text = (
                    f"\nPortfolio P&L: Rs.{total_pnl:+,.0f} "
                    f"({total_pnl_pct:+.2f}%) {direction}"
                )

        send_telegram(
            f"<b>Market Closed - EOD Summary</b>\n"
            f"Date: {datetime.now().strftime('%d %b %Y')}"
            f"{pnl_text}\n"
            f"Next scan: Tomorrow 15:45 PM IST\n"
            f"Open dashboard for full details."
        )
        log("EOD summary sent.")

    except Exception as e:
        log(f"EOD summary failed: {e}")


# ─────────────────────────────────────────────
# Manual trigger for testing
# ─────────────────────────────────────────────
def run_now(job: str = "morning"):
    """Manually trigger any job without waiting for schedule."""
    jobs = {
        "morning":  job_morning_scan,
        "midday":   job_midday_review,
        "preclose": job_preclose_check,
        "eod":      job_eod_summary,
    }
    fn = jobs.get(job)
    if fn:
        log(f"Manually running: {job}")
        fn()
    else:
        log(f"Unknown job '{job}'. Options: {list(jobs.keys())}")


# ─────────────────────────────────────────────
# Scheduler Entry Point
# ─────────────────────────────────────────────
def run_scheduler():
    from config import (
        MORNING_SCAN_TIME, MIDDAY_REVIEW_TIME,
        PRECLOSE_CHECK_TIME, EOD_SUMMARY_TIME,
    )
    log("Scheduler started.")
    log("Jobs scheduled:")
    log(f"  {MORNING_SCAN_TIME} — Post-close scan + AI analysis + Telegram alert")
    log(f"  {MIDDAY_REVIEW_TIME} — Portfolio hold/sell review")
    log(f"  {PRECLOSE_CHECK_TIME} — Stop loss and target checks")
    log(f"  {EOD_SUMMARY_TIME} — EOD portfolio summary")
    log("Press Ctrl+C to stop.\n")

    schedule.every().day.at(MORNING_SCAN_TIME).do(job_morning_scan)
    schedule.every().day.at(MIDDAY_REVIEW_TIME).do(job_midday_review)
    schedule.every().day.at(PRECLOSE_CHECK_TIME).do(job_preclose_check)
    schedule.every().day.at(EOD_SUMMARY_TIME).do(job_eod_summary)

    while True:
        schedule.run_pending()
        time.sleep(30)


# ─────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        run_now(sys.argv[1])
    else:
        run_scheduler()