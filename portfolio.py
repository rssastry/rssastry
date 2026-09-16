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
from indicators import IndicatorEngine
from typing import List, Dict, Any, Optional

PORTFOLIO_FILE = "portfolio.json"

# Stores the failure reasons from the most recent add_holding() call
# so callers (e.g. the dashboard) can surface them to the user.
last_add_failures: List[str] = []


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


# ── Sector & correlation risk helpers ─────────────────────────────
_sector_cache = {}


def get_sector(symbol: str) -> str:
    """Fetch sector for a symbol with caching to avoid repeated API calls."""
    sym = symbol.upper().replace(".NS", "")
    if sym in _sector_cache:
        return _sector_cache[sym]
    try:
        import yfinance as yf
        from fundamental_snapshots import resolve_provider_ticker
        info = yf.Ticker(resolve_provider_ticker(sym + ".NS")).info or {}
        sector = info.get("sector") or ""
        _sector_cache[sym] = sector
        return sector
    except Exception:
        _sector_cache[sym] = ""
        return ""


def get_correlation(sym1: str, sym2: str) -> float:
    """Compute 60-day daily-return correlation between two symbols."""
    try:
        from data_cache import fetch_history
        df1 = fetch_history(sym1 + ".NS", period="6mo", interval='1d')
        df2 = fetch_history(sym2 + ".NS", period="6mo", interval='1d')
        if df1 is None or df2 is None or df1.empty or df2.empty:
            return 0.0
        r1 = df1["Close"].pct_change().dropna()
        r2 = df2["Close"].pct_change().dropna()
        # Align on common dates
        common = r1.index.intersection(r2.index)
        if len(common) < 20:
            return 0.0
        return float(r1.loc[common].corr(r2.loc[common]))
    except Exception:
        return 0.0


def check_portfolio_risk(symbol: str, sector: str = None, cash: float = None,
                         notional: float = None, risk_amount: float = None) -> tuple[bool, list[str]]:
    """Check if adding a new position violates portfolio risk limits.

    Returns (is_allowed, list_of_failure_messages).
    """
    from config import (MAX_CORRELATION, MAX_POSITION_PCT, MAX_SECTOR_PCT,
                        MAX_POSITIONS, MAX_ACCOUNT_RISK_PCT)

    failures = []
    portfolio = load_portfolio()
    holdings = portfolio.get("holdings", [])
    clean_sym = str(symbol).upper().replace(".NS", "")
    projected_notional = float(notional or 0.0)

    # Position count guard: prevent over-diversifying into a portfolio that is
    # effectively all concentrated positions.
    if len(holdings) >= MAX_POSITIONS and not any(
        str(h.get("symbol", "")).upper().replace(".NS", "") == clean_sym
        for h in holdings
    ):
        failures.append(f"Portfolio already has {MAX_POSITIONS} positions; no new buy allowed")

    # Cash-based position sizing cap.
    if cash is not None:
        cash_val = float(cash)
        if cash_val > 0 and projected_notional > cash_val * MAX_POSITION_PCT:
            failures.append(
                f"Position notional {projected_notional:,.0f} exceeds max {MAX_POSITION_PCT * 100:.0f}% "
                f"of cash ({cash_val * MAX_POSITION_PCT:,.0f})"
            )
        if (cash_val > 0 and risk_amount is not None
                and float(risk_amount) > cash_val * MAX_ACCOUNT_RISK_PCT):
            failures.append(
                f"Single position risk {float(risk_amount):,.0f} exceeds max {MAX_ACCOUNT_RISK_PCT * 100:.0f}% "
                f"of account cash ({cash_val * MAX_ACCOUNT_RISK_PCT:,.0f})"
            )

    # Sector concentration guard.
    sector_name = (sector or get_sector(symbol)).strip()
    if sector_name:
        sector_total_value = sum(
            float(h.get("investment", 0) or h.get("buy_price", 0) * h.get("quantity", 0) or 0.0)
            for h in holdings
            if str(h.get("sector") or get_sector(h.get("symbol", ""))).strip().lower() == sector_name.lower()
        )
        budget = float(cash) if cash is not None else max(
            sum(float(h.get("investment", 0) or h.get("buy_price", 0) * h.get("quantity", 0) or 0.0) for h in holdings),
            projected_notional,
        )
        if budget > 0:
            sector_limit = budget * MAX_SECTOR_PCT
            if sector_total_value + projected_notional > sector_limit:
                failures.append(
                    f"Sector exposure {sector_total_value + projected_notional:,.0f} exceeds max "
                    f"{MAX_SECTOR_PCT * 100:.0f}% of capital ({sector_limit:,.0f}) for {sector_name}"
                )

    # Correlation check
    for h in holdings:
        hsym = str(h.get("symbol", "")).upper().replace(".NS", "")
        if hsym == clean_sym:
            continue
        corr = get_correlation(clean_sym, hsym)
        if corr > MAX_CORRELATION:
            failures.append(
                f"Correlation {corr:.2f} with {hsym} exceeds max {MAX_CORRELATION:.2f}"
            )

    return not failures, failures


def validate_holding_fields(symbol: str, buy_price: float, quantity: int,
                            target: float, stop_loss: float,
                            style: str = None) -> tuple[bool, list[str]]:
    """Basic validation for holding fields.

    Quantity, buy price and style are enforced. `target` and `stop_loss` are
    intentionally NOT validated — they are informational bookkeeping values and
    must never block adding/updating a stock in the portfolio.

    Returns (is_valid, list_of_failure_messages).
    """
    from config import MIN_QUANTITY
    failures = []

    if quantity is None or int(quantity) < MIN_QUANTITY:
        failures.append(f"quantity must be >= {MIN_QUANTITY}")

    if buy_price is None or float(buy_price) <= 0:
        failures.append("buy_price must be > 0")

    if style is not None and style not in ("intraday", "swing", "positional"):
        failures.append(f"style must be one of intraday/swing/positional (got '{style}')")

    return not failures, failures


def add_holding(symbol: str, buy_price: float, quantity: int,
                buy_date: str, target: float, stop_loss: float, style: str,
                cash: float = None):
    """Add a holding with basic validation (quantity, buy_price, style).

    `target` and `stop_loss` are stored as informational fields but are not
    validated — they never block adding a stock to the portfolio.

    On failure, the reasons are stored in the module-level `last_add_failures`
    list so callers can display them to the user.

    `cash` (optional) is the available budget / account cash for this position.
    It is no longer used to cap position size (the notional cap was relaxed).
    A symbol already held cannot be added again (use update_holding or
    remove_holding instead) — this prevents accidental double buys.
    """
    global last_add_failures

    ok, failures = validate_holding_fields(
        symbol, buy_price, quantity, target, stop_loss, style
    )
    if not ok:
        last_add_failures.clear()
        last_add_failures.extend(failures)
        print(f"  Cannot add {symbol}:")
        for f in failures:
            print(f"    - {f}")
        return False

    # ── Duplicate-position guard ──────────────────────────────────
    # A buy is a controlled, single event per symbol. Two entries for the
    # same symbol (double-click, or adding the same name across styles)
    # is a classic double-buy mistake — reject it here at the source.
    portfolio = load_portfolio()
    clean_sym = str(symbol).upper().replace(".NS", "")
    existing = [h for h in portfolio.get("holdings", [])
                if str(h.get("symbol", "")).upper().replace(".NS", "") == clean_sym]
    if existing:
        reason = (f"{clean_sym} is already in your portfolio "
                  f"(qty {existing[0].get('quantity')}). "
                  "Use Edit Position to change quantity, or Close it first, "
                  "before buying again.")
        last_add_failures.clear()
        last_add_failures.append(reason)
        print(f"  Cannot add {symbol} — duplicate position prevented.")
        return False

    # Portfolio-level risk checks (sector cap, correlation, position cap)
    notional = float(buy_price) * int(quantity)
    stop_risk = None
    try:
        if float(stop_loss) < float(buy_price):
            stop_risk = (float(buy_price) - float(stop_loss)) * int(quantity)
    except (TypeError, ValueError):
        pass
    risk_ok, risk_failures = check_portfolio_risk(
        symbol, notional=notional, cash=cash, risk_amount=stop_risk
    )
    if not risk_ok:
        last_add_failures.clear()
        last_add_failures.extend(risk_failures)
        print(f"  Cannot add {symbol} — portfolio risk limits:")
        for f in risk_failures:
            print(f"    - {f}")
        return False

    holding   = {
        "symbol":     clean_sym,
        "buy_price":  float(buy_price),
        "quantity":   int(quantity),
        "buy_date":   buy_date,
        "target":     float(target),
        "stop_loss":  float(stop_loss),
        "style":      style,
        "investment": round(float(buy_price) * int(quantity), 2),
        "added_at":   datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    portfolio["holdings"].append(holding)
    save_portfolio(portfolio)
    last_add_failures.clear()
    print(f"  Added {symbol} to portfolio — "
          f"{quantity} shares @ Rs.{buy_price}")
    return True


def remove_holding(symbol: str, sell_price: float, quantity: int = None):
    portfolio = load_portfolio()
    symbol    = symbol.upper().replace(".NS", "")
    for i, h in enumerate(portfolio["holdings"]):
        if h["symbol"] == symbol:
            existing_qty = h.get("quantity", 0)
            sell_qty = int(quantity) if quantity is not None else existing_qty
            if sell_qty <= 0:
                print(f"  Invalid sell quantity: {sell_qty}")
                return

            sell_qty = min(sell_qty, existing_qty)
            pnl     = (sell_price - h["buy_price"]) * sell_qty
            pnl_pct = ((sell_price - h["buy_price"]) / h["buy_price"]) * 100 if h.get("buy_price") else 0

            # If selling all shares -> move to closed_trades
            if sell_qty >= existing_qty:
                closed  = {
                    **h,
                    "sell_price": sell_price,
                    "sell_date":  str(date.today()),
                    "pnl":        round(pnl, 2),
                    "pnl_pct":    round(pnl_pct, 2),
                    "closed_qty": sell_qty
                }
                portfolio["closed_trades"].append(closed)
                portfolio["holdings"].pop(i)
                save_portfolio(portfolio)
                result = "PROFIT" if pnl > 0 else "LOSS"
                print(f"  Closed {symbol} [{result}]: "
                      f"P&L Rs.{pnl:+,.2f} ({pnl_pct:+.2f}%)")
                return

            # Partial close: reduce holding quantity and record realized part in closed_trades
            remaining_qty = existing_qty - sell_qty
            h["quantity"] = remaining_qty
            h["investment"] = round(h.get("buy_price", 0) * remaining_qty, 2)
            closed_part = {
                **{k: v for k, v in h.items() if k != 'quantity'},
                "sell_price": sell_price,
                "sell_date":  str(date.today()),
                "pnl":        round(pnl, 2),
                "pnl_pct":    round(pnl_pct, 2),
                "closed_qty": sell_qty
            }
            portfolio["closed_trades"].append(closed_part)
            portfolio["holdings"][i] = h
            save_portfolio(portfolio)
            print(f"  Partially closed {symbol}: sold {sell_qty}, remaining {remaining_qty}")
            return
    print(f"  {symbol} not found in portfolio")


def get_sector_leader(candidates: List[Dict[str, Any]], sector: str) -> Optional[Dict[str, Any]]:
    """Find the highest-ranked candidate (by ensemble score) in a given sector."""
    sector_candidates = [
        c for c in candidates
        if str(c.get("sector") or "").strip().lower() == sector.lower()
    ]
    if not sector_candidates:
        return None
    return max(sector_candidates, key=lambda x: float(x.get("ensemble_score", 0) or 0))


def compute_relative_strength(candidate: Dict[str, Any], sector_leader: Optional[Dict[str, Any]]) -> float:
    """Score relative strength vs sector leader.

    If the candidate is the leader or close to it, return a bonus.
    Otherwise, penalize for underperformance vs sector momentum.
    """
    if sector_leader is None:
        return 0.0
    
    cand_score = float(candidate.get("ensemble_score", 0) or 0)
    leader_score = float(sector_leader.get("ensemble_score", 0) or 0)
    
    # If candidate is the leader or very close (within 3 points), bonus
    if leader_score <= 0:
        return 0.0
    
    gap = cand_score - leader_score
    if gap >= -3.0:
        return 10.0  # matching or very close to leader
    elif gap >= -8.0:
        return 5.0   # moderately below leader
    else:
        return 0.0   # significantly lagging sector


def rank_buy_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rank BUY candidates by portfolio-aware quality, not raw technical score alone.

    The ranking blends ensemble score, quality score, historical signal quality,
    confirmation quality, and relative strength vs sector leader while penalizing
    weak or noisy setups.
    """
    ranked = []
    
    # Group by sector to find leaders for RS comparison
    sectors = set(str(c.get("sector") or "").strip() or "Unknown" for c in candidates)
    sector_leaders = {s: get_sector_leader(candidates, s) for s in sectors}
    
    for item in candidates:
        try:
            win = float(item.get("sig_win_pct", 50) or 50)
            samples = int(item.get("sig_samples", 0) or 0)
            quality = float(item.get("quality_score", item.get("ensemble_score", 0)) or 0)
            ensemble = float(item.get("ensemble_score", 0) or 0)
            adx = float(item.get("adx", 0) or 0)
            tf = bool(item.get("multi_tf_confirm", False))
            sector = str(item.get("sector") or "").strip() or "Unknown"

            ev_bonus = max(0.0, (win - 50) / 50.0)
            sample_bonus = min(10.0, samples / 25.0)
            adx_bonus = max(0.0, min(8.0, (adx - 20) / 5.0))
            tf_bonus = 8.0 if tf else 0.0
            quality_bonus = quality / 10.0
            rs_bonus = compute_relative_strength(item, sector_leaders.get(sector))

            score = (ensemble * 0.55) + (quality_bonus * 10.0) + (ev_bonus * 20.0) + (sample_bonus * 2.0) + adx_bonus + tf_bonus + rs_bonus
            item = dict(item)
            item["portfolio_rank_score"] = round(float(score), 2)
            item["relative_strength_score"] = round(rs_bonus, 2)
            item["sector"] = sector
            ranked.append(item)
        except Exception:
            item = dict(item)
            item["portfolio_rank_score"] = float(item.get("ensemble_score", 0) or 0)
            item["relative_strength_score"] = 0.0
            item["sector"] = str(item.get("sector") or "").strip() or "Unknown"
            ranked.append(item)

    ranked.sort(key=lambda x: x.get("portfolio_rank_score", 0), reverse=True)
    return ranked


def allocate_portfolio_buy_candidates(candidates: List[Dict[str, Any]], cash: float,
                                     max_positions: int = 10) -> List[Dict[str, Any]]:
    """Allocate ranked BUY candidates while respecting portfolio exposure caps.

    The selection is intentionally conservative: a single sector should only have
    one active allocation in the initial buy list, and no candidate can consume
    more than the sector exposure budget for the available cash.
    """
    from config import MAX_SECTOR_PCT, MAX_POSITION_PCT, MAX_ACCOUNT_RISK_PCT

    ranked = rank_buy_candidates(candidates)
    allocations: List[Dict[str, Any]] = []
    sector_totals: Dict[str, float] = {}
    selected_sectors: set[str] = set()
    remaining_cash = float(cash or 0.0)
    used_positions = 0

    for item in ranked:
        if used_positions >= max_positions:
            break

        price = float(item.get("current_price", 0) or 0)
        if price <= 0:
            continue

        sector = str(item.get("sector") or "").strip() or "Unknown"
        if sector in selected_sectors:
            continue

        sector_cap = remaining_cash * MAX_SECTOR_PCT if remaining_cash > 0 else 0.0
        current_sector_value = sector_totals.get(sector, 0.0)
        if current_sector_value >= sector_cap and sector_cap > 0:
            continue

        max_notional = min(remaining_cash, float(cash) * MAX_POSITION_PCT)
        if max_notional <= 0:
            break

        risk_cap = max(0.0, float(cash) * MAX_ACCOUNT_RISK_PCT)
        notional = min(max_notional, risk_cap if risk_cap > 0 else max_notional)
        qty = max(1, int(notional // price)) if price > 0 else 0
        final_notional = qty * price
        if final_notional <= 0:
            continue

        if final_notional > remaining_cash:
            final_notional = remaining_cash
            qty = max(1, int(final_notional // price)) if price > 0 else 0
            final_notional = qty * price
        if final_notional <= 0:
            continue

        if current_sector_value + final_notional > sector_cap and sector_cap > 0:
            allowed = max(0.0, sector_cap - current_sector_value)
            if allowed <= 0:
                continue
            qty = max(1, int(allowed // price)) if price > 0 else 0
            final_notional = qty * price
            if final_notional <= 0:
                continue

        allocations.append({
            **item,
            "qty": int(qty),
            "notional": round(float(final_notional), 2),
            "sector": sector,
        })
        sector_totals[sector] = current_sector_value + final_notional
        selected_sectors.add(sector)
        remaining_cash -= final_notional
        used_positions += 1

    return allocations


def compute_position_size(cash: float, atr: float, atr_mult: float = 3.0, risk_per_trade: float = None) -> int:
    """Compute position size (quantity) given cash, ATR and ATR multiplier.

    Uses `RISK_PER_TRADE` from config if `risk_per_trade` not provided.
    Returns integer quantity (0 if can't compute).
    """
    from config import RISK_PER_TRADE
    if risk_per_trade is None:
        risk_per_trade = RISK_PER_TRADE
    try:
        risk_amt = float(cash) * float(risk_per_trade)
        stop_distance = float(atr) * float(atr_mult)
        if stop_distance <= 0:
            return 0
        qty = int(risk_amt // stop_distance)
        return max(qty, 0)
    except Exception:
        return 0


def compute_position_and_stop(cash: float, price: float, atr: float,
                              atr_mult: float = 3.0, risk_per_trade: float = None) -> dict:
    """Compute quantity and ATR-based stop price given available cash and current price.

    Returns a dict: {"qty": int, "stop_price": float, "risk_amount": float}
    """
    try:
        qty = compute_position_size(cash, atr, atr_mult=atr_mult, risk_per_trade=risk_per_trade)
        stop_price = None
        if atr is not None and atr > 0 and price is not None and price > 0:
            stop_price = round(max(0.0, float(price) - float(atr) * float(atr_mult)), 2)
        risk_amt = float(cash) * (risk_per_trade if risk_per_trade is not None else __import__('config').RISK_PER_TRADE)
        return {"qty": int(qty), "stop_price": stop_price, "risk_amount": round(risk_amt, 2)}
    except Exception:
        return {"qty": 0, "stop_price": None, "risk_amount": 0.0}


def update_holding(symbol: str, buy_price: float = None, quantity: int = None,
                   buy_date: str = None, target: float = None,
                   stop_loss: float = None, style: str = None):
    """Update an existing holding's fields. Only non-None args are applied.

    Validates the resulting holding before saving.
    """
    portfolio = load_portfolio()
    symbol = symbol.upper().replace('.NS', '')
    for i, h in enumerate(portfolio.get("holdings", [])):
        if h.get("symbol") == symbol:
            # Build a candidate holding with the new values
            candidate = dict(h)
            if buy_price is not None:
                candidate["buy_price"] = float(buy_price)
            if quantity is not None:
                candidate["quantity"] = int(quantity)
            if buy_date is not None:
                candidate["buy_date"] = str(buy_date)
            if target is not None:
                candidate["target"] = float(target)
            if stop_loss is not None:
                candidate["stop_loss"] = float(stop_loss)
            if style is not None:
                candidate["style"] = style

            ok, failures = validate_holding_fields(
                symbol,
                candidate.get("buy_price", 0),
                candidate.get("quantity", 0),
                candidate.get("target", 0),
                candidate.get("stop_loss", 0),
                candidate.get("style"),
            )
            if not ok:
                print(f"  Cannot update {symbol}:")
                for f in failures:
                    print(f"    - {f}")
                return False

            h.update(candidate)
            # recompute investment
            try:
                h["investment"] = round(h.get("buy_price", 0) * h.get("quantity", 0), 2)
            except Exception:
                pass
            portfolio["holdings"][i] = h
            save_portfolio(portfolio)
            print(f"  Updated holding {symbol}")
            return True
    print(f"  {symbol} not found in portfolio")
    return False


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


def evaluate_hard_hold_sell_rule(symbol: str, buy_price: float, current_price: float,
                                stop_loss: float, target: float, pnl_pct: float,
                                ind: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Return an objective risk-based action before AI is allowed to override it.

    The stop-loss rule is PRIMARY. The broad -12% fallback is removed because it
    can permit a loss far beyond the planned stop. ADD_MORE is disabled until
    pyramiding is separately tested.
    """
    # Stop loss is the primary risk control
    if current_price <= stop_loss:
        return {
            "symbol": symbol,
            "action": "FULL_SELL",
            "urgency": "Immediate",
            "reasoning": "Stop loss has been triggered. Risk is now controlled by exiting the position.",
            "revised_target": target,
            "revised_stop_loss": current_price * 0.98,
            "pnl_percent": round(pnl_pct, 2),
            "risk_flag": "Trailing SL hit",
            "action_price": round(current_price, 2),
            "decision_source": "hard_rule",
        }

    # Trend weakness: use price/EMA structure + directional movement, not ADX alone.
    # ADX < 20 means weak trend, not necessarily bearish.
    if pnl_pct <= -8 and ind is not None:
        # Bearish requires price below EMA21 AND (bearish MACD crossover OR -DI > +DI)
        price_below_ema21 = current_price < ind.get("ema21", current_price)
        macd_bearish = ind.get("macd_crossover") == "bearish"
        adx_neg_above_pos = ind.get("adx_neg", 0) > ind.get("adx_pos", 0)
        bearish_trend = price_below_ema21 and (macd_bearish or adx_neg_above_pos)

        if bearish_trend:
            return {
                "symbol": symbol,
                "action": "PARTIAL_SELL",
                "urgency": "This week",
                "reasoning": "Price is below EMA21 with bearish directional structure. Reduce exposure while keeping optionality.",
                "revised_target": max(target, current_price * 1.02),
                "revised_stop_loss": max(stop_loss, current_price * 0.985),
                "pnl_percent": round(pnl_pct, 2),
                "risk_flag": "Sector weakness",
                "action_price": round(current_price, 2),
                "decision_source": "hard_rule",
            }

    # ADD_MORE is DISABLED until pyramiding is separately tested.
    # if pnl_pct >= 15 and ind is not None:
    #     strong_trend = (
    #         ind.get("ema9", 0) > ind.get("ema21", 0) > ind.get("ema50", 0)
    #         and current_price > ind.get("ema21", 0)
    #         and ind.get("macd_hist", 0) > 0
    #     )
    #     if strong_trend:
    #         return {
    #             "symbol": symbol,
    #             "action": "ADD_MORE",
    #             "urgency": "No rush",
    #             "reasoning": "Trend remains strong and the position is already delivering healthy gains. Add only if risk remains disciplined.",
    #             "revised_target": max(target, current_price * 1.12),
    #             "revised_stop_loss": max(stop_loss, current_price * 0.97),
    #             "pnl_percent": round(pnl_pct, 2),
    #             "risk_flag": "None",
    #             "action_price": round(current_price, 2),
    #             "decision_source": "hard_rule",
    #         }

    if current_price >= target and pnl_pct >= 8:
        return {
            "symbol": symbol,
            "action": "PARTIAL_SELL",
            "urgency": "This week",
            "reasoning": "Target has been reached and some profit should be booked to protect gains.",
            "revised_target": target,
            "revised_stop_loss": max(stop_loss, current_price * 0.98),
            "pnl_percent": round(pnl_pct, 2),
            "risk_flag": "None",
            "action_price": round(current_price, 2),
            "decision_source": "hard_rule",
        }

    return None


def run_hold_sell_analysis():
    """AI-powered Hold/Sell review for all holdings with hard risk gates first.

    If AI analysis fails, a deterministic HOLD – data unavailable fallback is recorded.
    """
    portfolio = load_portfolio()
    holdings  = portfolio.get("holdings", [])

    if not holdings:
        print("  No holdings to analyze.")
        return []

    analyst = AIAnalyst()
    results = []
    print(f"\n  Running Hold/Sell review on {len(holdings)} holdings...\n")

    for h in holdings:
        symbol = h["symbol"]
        print(f"  Analyzing {symbol}...", end=" ")

        try:
            engine = IndicatorEngine(symbol + ".NS")
            engine.fetch()
            ind = engine.compute_all()
        except Exception:
            ind = {}

        current_price = ind.get("current_price", h["buy_price"])
        pnl_pct = ((current_price - h["buy_price"]) / h["buy_price"]) * 100 if h.get("buy_price") else 0

        hard_rule = evaluate_hard_hold_sell_rule(
            symbol=symbol,
            buy_price=h["buy_price"],
            current_price=current_price,
            stop_loss=h["stop_loss"],
            target=h["target"],
            pnl_pct=pnl_pct,
            ind=ind,
        )

        if hard_rule:
            results.append(hard_rule)
            action = hard_rule.get("action", "?")
            urgency = hard_rule.get("urgency", "")
            label = {
                "HOLD": "HOLD",
                "FULL_SELL": "FULL SELL",
                "PARTIAL_SELL": "PARTIAL SELL",
                "ADD_MORE": "ADD MORE"
            }.get(action, action)
            print(f"{label} [{urgency}] (hard rule)")
            reasoning = hard_rule.get("reasoning", "")[:100]
            print(f"     {reasoning}...")
            continue

        result = analyst.analyze_portfolio_holding(
            symbol          = symbol,
            buy_price       = h["buy_price"],
            buy_date        = h["buy_date"],
            original_target = h["target"],
            original_sl     = h["stop_loss"]
        )
        if result:
            result["decision_source"] = "AI"
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
            # Deterministic fallback: HOLD – data unavailable
            fallback = {
                "symbol": symbol,
                "action": "HOLD",
                "urgency": "No rush",
                "reasoning": "AI analysis failed. No decision recorded — holding with existing stop-loss and target.",
                "revised_target": h["target"],
                "revised_stop_loss": h["stop_loss"],
                "pnl_percent": round(pnl_pct, 2),
                "risk_flag": "Data unavailable",
                "action_price": round(current_price, 2),
                "decision_source": "fallback",
            }
            results.append(fallback)
            print("HOLD [No rush] (fallback — data unavailable)")

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


def generate_signal(symbol: str) -> Dict[str, Any]:
    """Return buy/sell signal info for a symbol using IndicatorEngine."""
    sym = symbol.upper().replace('.NS', '')
    engine = IndicatorEngine(sym + ".NS")
    ok = engine.fetch()
    if not ok:
        return {"symbol": symbol, "error": "no data"}
    ind = engine.compute_all()
    buy = ind.get("buy_rule_passed", False)
    sell = ind.get("sell_rule_passed", False)
    return {
        "symbol": sym,
        "buy": bool(buy),
        "sell": bool(sell),
        "rsi": ind.get("rsi"),
        "ema21": ind.get("ema21"),
        "ema50": ind.get("ema50"),
        "atr": ind.get("atr")
    }


def suggest_buys(cash: float, max_positions: int = 10, universe: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Scan universe and suggest buy orders with quantity based on equal-weight allocation.

    Uses the main screener's deterministic BUY gate (not just the EMA-crossover rule),
    sorts by ensemble score, and enforces that notional value fits available cash.

    Returns a list of suggestions: symbol, target_qty, estimated_price, allocation
    """
    from screener import StockScreener, NSE_STOCKS
    from config import MAX_POSITION_PCT

    if universe is None:
        universe = NSE_STOCKS

    # Risk circuit breaker: when the account is bleeding past the daily-loss
    # or drawdown floors, no fresh BUY suggestions are generated. This is the
    # automation kill-switch that prevents a losing system from averaging in.
    try:
        from circuit_breaker import RiskCircuitBreaker
        allowed, reason = RiskCircuitBreaker().pre_trade_check()
        if not allowed:
            print(f"  suggest_buys blocked by circuit breaker: {reason}")
            return []
    except Exception as exc:  # never fail the whole suggestion run on breaker error
        print(f"  suggest_buys: circuit breaker unavailable ({exc}); continuing")

    # Run the main screener to get deterministic BUY candidates
    screener = StockScreener()
    # Use a small top_n to keep it fast; we'll re-rank below
    results = screener.screen(styles=["swing", "positional"], top_n=50)

    # Collect BUY candidates from the screener output
    candidates = []
    for style in ("swing", "positional"):
        for stock in results.get(style, []):
            if stock.get("recommendation") == "BUY":
                candidates.append({
                    "symbol": stock["symbol"],
                    "yf_symbol": stock["yf_symbol"],
                    "price": stock.get("current_price", 0),
                    "atr": stock.get("atr", 0),
                    "ensemble_score": stock.get("ensemble_score", 0),
                    "style": style,
                })

    # Deduplicate by symbol (keep highest score)
    seen = {}
    for c in candidates:
        sym = c["symbol"]
        if sym not in seen or c["ensemble_score"] > seen[sym]["ensemble_score"]:
            seen[sym] = c
    candidates = list(seen.values())

    # Sort by ensemble score (not price)
    candidates.sort(key=lambda x: x.get("ensemble_score", 0), reverse=True)
    candidates = candidates[:max_positions]

    # Compute position sizes that fit within available cash
    suggestions = []
    remaining_cash = float(cash)
    for c in candidates:
        price = c.get("price") or 0
        atr = c.get("atr") or 0
        if price <= 0 or atr <= 0:
            continue

        # Position size from risk, capped by available cash and max position % of account
        pos = compute_position_and_stop(remaining_cash, price, atr, atr_mult=3.0)
        qty = pos.get("qty", 0)
        stop_price = pos.get("stop_price")

        # Cap notional value to available cash and max position % of total account
        max_notional = min(remaining_cash, float(cash) * MAX_POSITION_PCT)
        max_qty_by_cash = int(max_notional // price) if price > 0 else 0
        qty = min(qty, max_qty_by_cash)

        if qty <= 0:
            continue

        notional = qty * price

        # Portfolio-level risk check (sector cap, correlation)
        risk_amount = None
        if stop_price is not None and stop_price < price:
            risk_amount = (price - stop_price) * qty
        risk_ok, risk_failures = check_portfolio_risk(
            c["symbol"], notional=notional, cash=cash,
            risk_amount=risk_amount
        )
        if not risk_ok:
            continue

        remaining_cash -= notional

        sugg = {
            'symbol': c['symbol'],
            'est_price': price,
            'atr': atr,
            'qty': qty,
            'stop_loss': stop_price,
            'notional': round(notional, 2),
            'ensemble_score': c.get('ensemble_score', 0),
            'style': c.get('style', 'swing'),
        }
        # log suggestion for audit / ML
        try:
            from signal_logger import log_signal
            log_signal(c['symbol'], price, atr=atr, qty=qty, stop_loss=stop_price, source='suggest_buys')
        except Exception:
            pass
        suggestions.append(sugg)

    return suggestions


def save_buy_suggestions(suggestions: List[Dict[str, Any]], path: str = "buy_suggestions.json"):
    try:
        with open(path, "w") as f:
            json.dump(suggestions, f, indent=2)
        return True
    except Exception:
        return False