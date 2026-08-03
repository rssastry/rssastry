"""
portfolio.py — Portfolio Tracker
Tracks holdings, P&L, and runs Hold/Sell analysis
"""

import json
import os
from datetime import datetime, date
from ai_analyst import AIAnalyst
import warnings
warnings.filterwarnings("ignore")

PORTFOLIO_FILE = "portfolio.json"


def load_portfolio() -> dict:
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)
    return {"holdings": [], "closed_trades": [], "last_updated": ""}

        
def save_portfolio(portfolio: dict):
    portfolio["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def clean(obj):
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items() if k != "ohlcv_30d"}
        elif isinstance(obj, list):
            return [clean(i) for i in obj]
        else:
            return str(obj) if hasattr(obj, 'isoformat') else obj

    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(clean(portfolio), f, indent=2)


def add_holding(symbol: str, buy_price: float, quantity: int,
                buy_date: str, target: float, stop_loss: float, style: str):
    portfolio = load_portfolio()
    holding   = {
        "symbol":     symbol.upper().replace(".NS", ""),
        "buy_price":  buy_price,
        "quantity":   quantity,
        "buy_date":   buy_date,
        "target":     target,
        "stop_loss":  stop_loss,
        "style":      style,
        "investment": round(buy_price * quantity, 2),
        "added_at":   datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    portfolio["holdings"].append(holding)
    save_portfolio(portfolio)
    print(f"  Added {symbol} to portfolio — "
          f"{quantity} shares @ Rs.{buy_price}")


def remove_holding(symbol: str, sell_price: float, quantity: int = None):
    portfolio = load_portfolio()
    symbol    = symbol.upper().replace(".NS", "")
    for i, h in enumerate(portfolio["holdings"]):
        if h["symbol"] == symbol:
            qty     = quantity or h["quantity"]
            pnl     = (sell_price - h["buy_price"]) * qty
            pnl_pct = ((sell_price - h["buy_price"]) / h["buy_price"]) * 100
            closed  = {
                **h,
                "sell_price": sell_price,
                "sell_date":  str(date.today()),
                "pnl":        round(pnl, 2),
                "pnl_pct":    round(pnl_pct, 2)
            }
            portfolio["closed_trades"].append(closed)
            portfolio["holdings"].pop(i)
            save_portfolio(portfolio)
            result = "PROFIT" if pnl > 0 else "LOSS"
            print(f"  Closed {symbol} [{result}]: "
                  f"P&L Rs.{pnl:+,.2f} ({pnl_pct:+.2f}%)")
            return
    print(f"  {symbol} not found in portfolio")


def show_portfolio():
    portfolio = load_portfolio()
    holdings  = portfolio.get("holdings", [])

    if not holdings:
        print("  Portfolio is empty.")
        print("  Add holdings with: add_holding('RELIANCE', 2840, 10, "
              "'2025-01-10', 2970, 2795, 'swing')")
        return

    print(f"\n{'='*70}")
    print(f"  PORTFOLIO — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")
    print(f"  {'Symbol':<12} {'Qty':>5} {'Buy':>8} {'CMP':>8} "
          f"{'P&L%':>7} {'P&L Rs':>10} {'Style':<12}")
    print(f"  {'─'*66}")

    total_invested = 0
    total_current  = 0

    for h in holdings:
        symbol = h["symbol"]
        try:
            from indicators import IndicatorEngine
            engine = IndicatorEngine(symbol + ".NS")
            engine.fetch()
            ind = engine.compute_all()
            cmp = ind.get("current_price", h["buy_price"])
        except Exception:
            cmp = h["buy_price"]

        qty         = h["quantity"]
        invested    = h["buy_price"] * qty
        current_val = cmp * qty
        pnl         = current_val - invested
        pnl_pct     = (pnl / invested) * 100
        direction   = "+" if pnl >= 0 else ""

        total_invested += invested
        total_current  += current_val

        print(f"  {symbol:<12} {qty:>5} "
              f"Rs.{h['buy_price']:>6.2f} "
              f"Rs.{cmp:>6.2f} "
              f"{pnl_pct:>+6.1f}% "
              f"Rs.{pnl:>+9,.0f}  "
              f"{h['style']:<12}")

    total_pnl     = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0

    print(f"  {'─'*66}")
    print(f"  {'TOTAL':<12} {'':>5} "
          f"Rs.{total_invested:>6,.0f} {'':>9} "
          f"{total_pnl_pct:>+6.1f}% "
          f"Rs.{total_pnl:>+9,.0f}")
    print(f"{'='*70}\n")

    # Closed trades summary
    closed = portfolio.get("closed_trades", [])
    if closed:
        total_realized = sum(t.get("pnl", 0) for t in closed)
        print(f"  Closed Trades: {len(closed)} | "
              f"Realized P&L: Rs.{total_realized:+,.2f}\n")

def clean_timestamps(obj):
        if isinstance(obj, dict):
            return {k: clean_timestamps(v) for k, v in obj.items()
                    if k != "ohlcv_30d"}
        elif isinstance(obj, list):
            return [clean_timestamps(i) for i in obj]
        else:
            return str(obj) if hasattr(obj, 'isoformat') else obj

def run_hold_sell_analysis():
    """AI-powered Hold/Sell review for all holdings."""
    portfolio = load_portfolio()
    holdings  = portfolio.get("holdings", [])

    if not holdings:
        print("  No holdings to analyze.")
        return []

    analyst = AIAnalyst()
    results = []
    print(f"\n  Running Hold/Sell AI analysis on "
          f"{len(holdings)} holdings...\n")

    for h in holdings:
        symbol = h["symbol"]
        print(f"  Analyzing {symbol}...", end=" ")
        result = analyst.analyze_portfolio_holding(
            symbol          = symbol,
            buy_price       = h["buy_price"],
            buy_date        = h["buy_date"],
            original_target = h["target"],
            original_sl     = h["stop_loss"]
        )
        if result:
            results.append(result)
            action  = result.get("action", "?")
            urgency = result.get("urgency", "")
            label   = {
                "HOLD":         "HOLD",
                "FULL_SELL":    "FULL SELL",
                "PARTIAL_SELL": "PARTIAL SELL",
                "ADD_MORE":     "ADD MORE"
            }.get(action, action)
            print(f"{label} [{urgency}]")
            reasoning = result.get("reasoning", "")[:100]
            print(f"     {reasoning}...")
        else:
            print("Analysis failed")

    with open("hold_sell_analysis.json", "w") as f:
        json.dump(clean_timestamps(results), f, indent=2, default=str)

    print(f"\n  Analysis complete. Results saved to hold_sell_analysis.json")
    return results


def show_closed_trades():
    """Show history of all closed/exited trades."""
    portfolio = load_portfolio()
    closed    = portfolio.get("closed_trades", [])

    if not closed:
        print("  No closed trades yet.")
        return

    print(f"\n{'='*70}")
    print(f"  CLOSED TRADES HISTORY")
    print(f"{'='*70}")
    print(f"  {'Symbol':<12} {'Buy':>8} {'Sell':>8} "
          f"{'P&L%':>7} {'P&L Rs':>10} {'Date':<12}")
    print(f"  {'─'*60}")

    total_pnl = 0
    for t in closed:
        pnl     = t.get("pnl", 0)
        pnl_pct = t.get("pnl_pct", 0)
        result  = "WIN " if pnl >= 0 else "LOSS"
        total_pnl += pnl
        print(f"  [{result}] {t['symbol']:<10} "
              f"Rs.{t['buy_price']:>6.2f} "
              f"Rs.{t['sell_price']:>6.2f} "
              f"{pnl_pct:>+6.1f}% "
              f"Rs.{pnl:>+9,.0f}  "
              f"{t.get('sell_date','?'):<12}")

    print(f"  {'─'*60}")
    print(f"  Total Realized P&L: Rs.{total_pnl:+,.2f}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    print("Portfolio Manager ready.")
    print("Commands available:")
    print("  add_holding('RELIANCE', 2840, 10, '2025-01-10', 2970, 2795, 'swing')")
    print("  show_portfolio()")
    print("  run_hold_sell_analysis()")
    print("  show_closed_trades()")
    print("  remove_holding('RELIANCE', 2950)")
    print()
    show_portfolio()