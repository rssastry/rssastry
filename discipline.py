"""
discipline.py - Portfolio discipline & attribution: aging, concentration,
and realized P&L versus the market.

The portfolio module enforces limits at ADD time (position size, sector,
correlation). This module is the on-going REVIEW layer a Sr. analyst needs:

  - position_aging     : how long each OPEN holding has run, in completed
                         trading bars, versus its style max-hold
                         (STYLE_MAX_HOLD_BARS). A swing position open 40 bars
                         is not a swing position anymore - it needs a review
                         or an explicit re-commitment.
  - concentration      : sector weights (from local PIT snapshots - no
                         network), per-position share, and a Herfindahl index
                         so concentration/overdiversification are both visible.
  - realized_ledger    : every closed trade's realized return versus the
                         NIFTY buy-and-hold return over the SAME window
                         (alpha). This is the honest report card of whether
                         the edge is real or just beta.
  - unrealized_now     : current open P&L% versus NIFTY over the held window.

Everything runs from local data (portfolio.json + raw_data/prices CSVs).
Output: portfolio_discipline_report.json.

CLI:
    python discipline.py [--out portfolio_discipline_report.json]
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone

import pandas as pd

from config import STYLE_MAX_HOLD_BARS
from price_store import load_adjusted
from market_breadth import _sector_for
import paths

PORTFOLIO_FILE = paths.path("portfolio.json")
NIFTY_SYMBOL = "^NSEI"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_portfolio(path: str = PORTFOLIO_FILE) -> dict:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            pass
    return {"holdings": [], "closed_trades": [], "last_updated": ""}


def _trading_bars_between(symbol: str, start: str, end: str,
                          price_loader=None) -> int | None:
    """Completed trading bars of the symbol in [start, end). None when no data."""
    loader = price_loader or load_adjusted
    df = loader(symbol, period=None, interval="1d")
    if df is None or df.empty:
        return None
    mask = (df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end))
    return int(mask.sum())


def position_aging(portfolio: dict = None, as_of: str = None,
                   price_loader=None) -> list[dict]:
    """Per holding: age in bars, style max-hold, and OVERDUE flag."""
    portfolio = portfolio if portfolio is not None else load_portfolio()
    as_of = as_of or date.today().isoformat()
    rows = []
    for holding in portfolio.get("holdings", []):
        symbol = str(holding.get("symbol", "")).upper().replace(".NS", "")
        buy_date = str(holding.get("buy_date") or holding.get("added_at"))[:10]
        style = str(holding.get("style") or "positional").lower()
        max_hold = int(STYLE_MAX_HOLD_BARS.get(style, 60))
        bars = _trading_bars_between(symbol, buy_date, as_of,
                                     price_loader=price_loader)
        if bars is None:
            # No local price history: fall back to calendar days.
            try:
                bars = (pd.Timestamp(as_of) - pd.Timestamp(buy_date)).days
            except Exception:
                bars = 0
            age_basis = "calendar_days_fallback"
        else:
            age_basis = "trading_bars"
        rows.append({
            "symbol": symbol,
            "style": style,
            "buy_date": buy_date,
            "open_bars": bars,
            "max_hold_bars": max_hold,
            "age_basis": age_basis,
            "overdue": bars is not None and bars > max_hold,
        })
    return rows


def concentration(portfolio: dict = None,
                  sector_lookup=None) -> dict:
    """Position shares, sector weights (PIT snapshots) and a Herfindahl index."""
    portfolio = portfolio if portfolio is not None else load_portfolio()
    lookup = sector_lookup or _sector_for
    holdings = portfolio.get("holdings", [])
    positions = []
    total = 0.0
    for holding in holdings:
        qty = float(holding.get("quantity", 0) or 0)
        price = float(holding.get("buy_price", 0) or 0)
        notional = qty * price
        symbol = str(holding.get("symbol", "")).upper().replace(".NS", "")
        total += notional
        positions.append({"symbol": symbol, "notional": notional})
    if total <= 0:
        return {"positions": 0, "total_notional": 0.0,
                "hhi": None, "sector_weights": {}, "top_position_share": None}
    shares = {p["symbol"]: p["notional"] / total for p in positions}
    sector_weights = {}
    for p in positions:
        sector = lookup(p["symbol"]) or "Unknown"
        sector_weights[sector] = sector_weights.get(sector, 0.0) + p["notional"] / total
    hhi = round(sum(share ** 2 for share in shares.values()), 4)
    return {
        "positions": len(positions),
        "total_notional": round(total, 2),
        "per_position_share": {k: round(v, 4) for k, v in shares.items()},
        "sector_weights": {k: round(v, 4) for k, v in
                           sorted(sector_weights.items(), key=lambda kv: -kv[1])},
        "hhi": hhi,
        "top_position_share": round(max(shares.values()), 4),
    }


def _nifty_return(start: str, end: str, nifty_sym: str = NIFTY_SYMBOL,
                  price_loader=None) -> float | None:
    loader = price_loader or load_adjusted
    df = loader(nifty_sym, period=None, interval="1d")
    if df is None or df.empty:
        return None
    try:
        start_close = float(df["Close"].loc[df.index >= pd.Timestamp(start)].iloc[0])
        end_close = float(df["Close"].loc[df.index <= pd.Timestamp(end)].iloc[-1])
    except (IndexError, KeyError):
        return None
    if start_close <= 0:
        return None
    return end_close / start_close - 1.0


def realized_ledger(portfolio: dict = None, nifty_sym: str = NIFTY_SYMBOL,
                    price_loader=None) -> list[dict]:
    """Closed trades with realized return and NIFTY alpha over the window."""
    portfolio = portfolio if portfolio is not None else load_portfolio()
    rows = []
    for trade in portfolio.get("closed_trades", []):
        symbol = str(trade.get("symbol", "")).upper().replace(".NS", "")
        buy_date = str(trade.get("buy_date"))[:10] or ""
        sell_date = str(trade.get("sell_date"))[:10] or ""
        buy_price = float(trade.get("buy_price", 0) or 0)
        sell_price = float(trade.get("sell_price", 0) or 0)
        pnl_pct = float(trade.get("pnl_pct", 0) or 0)
        nifty_ret = _nifty_return(buy_date, sell_date, nifty_sym,
                                  price_loader=price_loader)
        rows.append({
            "symbol": symbol,
            "buy_date": buy_date,
            "sell_date": sell_date,
            "realized_pnl_pct": round(pnl_pct, 2),
            "exit": str(trade.get("exit_reason") or "MANUAL").upper(),
            "nifty_buyhold_pct": (round(nifty_ret * 100, 2)
                                  if nifty_ret is not None else None),
            "alpha_pct": (round(pnl_pct - nifty_ret * 100, 2)
                          if nifty_ret is not None else None),
            "traded": round(buy_price, 2),
            "closed": round(sell_price, 2),
        })
    return rows


def unrealized_now(portfolio: dict = None, nifty_sym: str = NIFTY_SYMBOL,
                   price_loader=None) -> list[dict]:
    """Open holdings: current P&L% vs NIFTY over the same held window."""
    portfolio = portfolio if portfolio is not None else load_portfolio()
    loader = price_loader or load_adjusted
    rows = []
    for holding in portfolio.get("holdings", []):
        symbol = str(holding.get("symbol", "")).upper().replace(".NS", "")
        buy_date = str(holding.get("buy_date") or "")[:10]
        buy_price = float(holding.get("buy_price", 0) or 0)
        df = loader(symbol, period=None, interval="1d")
        if df is None or df.empty or not buy_price or not buy_date:
            continue
        try:
            current = float(df["Close"].iloc[-1])
        except (IndexError, KeyError):
            continue
        pnl_pct = (current / buy_price - 1) * 100
        nifty_ret = _nifty_return(buy_date, date.today().isoformat(),
                                  nifty_sym, price_loader=loader)
        rows.append({
            "symbol": symbol,
            "buy_date": buy_date,
            "current_price": round(current, 2),
            "unrealized_pnl_pct": round(pnl_pct, 2),
            "nifty_buyhold_pct": (round(nifty_ret * 100, 2)
                                  if nifty_ret is not None else None),
            "alpha_pct": (round(pnl_pct - nifty_ret * 100, 2)
                          if nifty_ret is not None else None),
        })
    return rows


def positives_ratio(rows: list) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if (r.get("alpha_pct") or 0) > 0) / len(rows)


def build_discipline_report(out: str = None, portfolio: dict = None) -> dict:
    out = out or paths.path("portfolio_discipline_report.json")
    aging = position_aging(portfolio=portfolio)
    conc = concentration(portfolio=portfolio)
    closed = realized_ledger(portfolio=portfolio)
    open_rows = unrealized_now(portfolio=portfolio)
    report = {
        "generated_at": _utc_now(),
        "portfolio_updated": (portfolio or {}).get("last_updated"),
        "position_aging": aging,
        "concentration": conc,
        "realized_ledger": closed,
        "unrealized": open_rows,
        "summary": {
            "open_positions": len(aging),
            "overdue_positions": sum(1 for r in aging if r["overdue"]),
            "hhi": conc["hhi"],
            "top_position_share": conc["top_position_share"],
            "closed_trades": len(closed),
            "closed_alpha_win_pct": round(100.0 * positives_ratio(closed), 1),
            "net_realized_pnl_pct": round(
                sum(r["realized_pnl_pct"] for r in closed), 2),
            "closed_exit_reasons": dict(
                __import__("collections").Counter(r["exit"] for r in closed)),
        },
    }
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    return report


def _nifty_str(row: dict) -> str:
    value = row.get("nifty_buyhold_pct")
    return "n/a" if value is None else f"{value:+.2f}%"


def _print_report(report: dict):
    print("=" * 66)
    print("PORTFOLIO DISCIPLINE REPORT")
    print("=" * 66)
    s = report["summary"]
    print(f"Open positions         : {s['open_positions']} "
          f"(OVERDUE {s['overdue_positions']})")
    print(f"Concentration (HHI)    : {s['hhi']}  "
          f"top position {s['top_position_share'] or 0:.1%}")
    print(f"Closed trades          : {s['closed_trades']}  "
          f"alpha win {s['closed_alpha_win_pct']}%  "
          f"net realized {s['net_realized_pnl_pct']}%")
    print("-" * 66)
    print("Position aging:")
    for row in report["position_aging"]:
        flag = "  <-- OVERDUE" if row["overdue"] else ""
        print(f"  {row['symbol']:<14}{row['style']:<11}"
              f"open {row['open_bars']:>4} bars / max {row['max_hold_bars']:>3}"
              f"{flag}")
    print("-" * 66)
    print("Sector weights:")
    for sector, weight in report["concentration"]["sector_weights"].items():
        print(f"  {sector:<22} {weight:.1%}")
    print("-" * 66)
    print("Realized edge vs NIFTY (closed):")
    for row in report["realized_ledger"]:
        alpha = "n/a" if row["alpha_pct"] is None else f"{row['alpha_pct']:+.2f}%"
        print(f"  {row['symbol']:<14} P&L {row['realized_pnl_pct']:+.2f}%  "
              f"NIFTY {_nifty_str(row)}  alpha {alpha}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="portfolio_discipline_report.json")
    args = ap.parse_args()
    report = build_discipline_report(out=args.out)
    _print_report(report)
    print(f"\nSaved: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())