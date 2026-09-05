"""
strategies.py — Encodes investor-inspired scoring rules

Provides lightweight, explainable Buffett-style and
Jhunjhunwala-inspired scoring functions that accept the
indicator dictionary (from `screener.py`) and a fundamentals
`info` dict from `yfinance.Ticker.info`.

These are heuristic rule-encodings for research and screening
purposes only — not financial advice.
"""
from typing import Tuple, List, Dict

def _safe_get(d: Dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


# ── Sector-aware quality thresholds ───────────────────────────────
# Different sectors have different normal ranges for ROE, margins, P/B, etc.
# Banks are leveraged by nature; software has high margins; commodities are cyclical.
SECTOR_THRESHOLDS = {
    "Financial Services": {
        "roe_min": 0.12, "roe_good": 0.18,
        "debt_max": 8.0, "debt_good": 4.0,
        "margin_min": 0.10, "margin_good": 0.20,
        "pb_max": 2.5, "pb_good": 1.5,
        "pe_max": 20, "pe_good": 15,
        "roce_min": 0.10, "roce_good": 0.15,
    },
    "Technology": {
        "roe_min": 0.20, "roe_good": 0.30,
        "debt_max": 1.0, "debt_good": 0.5,
        "margin_min": 0.20, "margin_good": 0.30,
        "pb_max": 6.0, "pb_good": 4.0,
        "pe_max": 30, "pe_good": 25,
        "roce_min": 0.20, "roce_good": 0.30,
    },
    "Basic Materials": {
        "roe_min": 0.10, "roe_good": 0.15,
        "debt_max": 2.0, "debt_good": 1.0,
        "margin_min": 0.08, "margin_good": 0.15,
        "pb_max": 2.0, "pb_good": 1.2,
        "pe_max": 15, "pe_good": 10,
        "roce_min": 0.10, "roce_good": 0.15,
    },
    "Healthcare": {
        "roe_min": 0.15, "roe_good": 0.22,
        "debt_max": 1.5, "debt_good": 0.8,
        "margin_min": 0.15, "margin_good": 0.25,
        "pb_max": 5.0, "pb_good": 3.0,
        "pe_max": 25, "pe_good": 20,
        "roce_min": 0.15, "roce_good": 0.22,
    },
    "Energy": {
        "roe_min": 0.10, "roe_good": 0.15,
        "debt_max": 2.0, "debt_good": 1.0,
        "margin_min": 0.08, "margin_good": 0.15,
        "pb_max": 2.0, "pb_good": 1.2,
        "pe_max": 15, "pe_good": 10,
        "roce_min": 0.10, "roce_good": 0.15,
    },
    "Consumer Defensive": {
        "roe_min": 0.15, "roe_good": 0.25,
        "debt_max": 1.5, "debt_good": 0.8,
        "margin_min": 0.12, "margin_good": 0.20,
        "pb_max": 6.0, "pb_good": 4.0,
        "pe_max": 30, "pe_good": 25,
        "roce_min": 0.15, "roce_good": 0.25,
    },
    "Consumer Cyclical": {
        "roe_min": 0.12, "roe_good": 0.20,
        "debt_max": 2.0, "debt_good": 1.0,
        "margin_min": 0.08, "margin_good": 0.15,
        "pb_max": 4.0, "pb_good": 2.5,
        "pe_max": 25, "pe_good": 20,
        "roce_min": 0.12, "roce_good": 0.20,
    },
    "Industrials": {
        "roe_min": 0.12, "roe_good": 0.20,
        "debt_max": 2.0, "debt_good": 1.0,
        "margin_min": 0.08, "margin_good": 0.15,
        "pb_max": 4.0, "pb_good": 2.5,
        "pe_max": 25, "pe_good": 20,
        "roce_min": 0.12, "roce_good": 0.20,
    },
    "Utilities": {
        "roe_min": 0.10, "roe_good": 0.15,
        "debt_max": 3.0, "debt_good": 2.0,
        "margin_min": 0.10, "margin_good": 0.20,
        "pb_max": 3.0, "pb_good": 2.0,
        "pe_max": 20, "pe_good": 15,
        "roce_min": 0.08, "roce_good": 0.12,
    },
    "Communication Services": {
        "roe_min": 0.12, "roe_good": 0.20,
        "debt_max": 3.0, "debt_good": 2.0,
        "margin_min": 0.10, "margin_good": 0.20,
        "pb_max": 4.0, "pb_good": 2.5,
        "pe_max": 25, "pe_good": 20,
        "roce_min": 0.10, "roce_good": 0.15,
    },
}

# Default thresholds for unknown sectors
DEFAULT_THRESHOLDS = {
    "roe_min": 0.15, "roe_good": 0.25,
    "debt_max": 2.0, "debt_good": 1.0,
    "margin_min": 0.10, "margin_good": 0.20,
    "pb_max": 4.0, "pb_good": 2.5,
    "pe_max": 25, "pe_good": 20,
    "roce_min": 0.15, "roce_good": 0.25,
}


def get_sector_thresholds(sector: str) -> dict:
    """Return sector-appropriate thresholds, falling back to defaults."""
    if not sector:
        return DEFAULT_THRESHOLDS
    # Match by keyword to handle variations like "Financial Services" vs "Banks"
    sector_lower = sector.lower()
    for key, thresholds in SECTOR_THRESHOLDS.items():
        if key.lower() in sector_lower or sector_lower in key.lower():
            return thresholds
    return DEFAULT_THRESHOLDS


def score_buffett(indicators: dict, fundamentals: dict, sector: str = None) -> Tuple[int, List[str]]:
    """Buffett-style heuristic scoring for quality + valuation discipline."""
    score = 0
    reasons = []
    t = get_sector_thresholds(sector)

    roe = _safe_get(fundamentals, 'returnOnEquity', default=None)
    if roe is not None:
        try:
            if roe >= t["roe_good"]:
                score += 25; reasons.append(f"High ROE: {roe:.2f}")
            elif roe >= t["roe_min"]:
                score += 12; reasons.append(f"Decent ROE: {roe:.2f}")
        except Exception:
            pass

    debt = _safe_get(fundamentals, 'debtToEquity', default=None)
    if debt is not None:
        try:
            if debt <= t["debt_good"]:
                score += 20; reasons.append(f"Low D/E: {debt:.2f}")
            elif debt <= t["debt_max"]:
                score += 8; reasons.append(f"Moderate D/E: {debt:.2f}")
        except Exception:
            pass

    fcf = _safe_get(fundamentals, 'freeCashflow', default=None)
    if fcf is not None:
        try:
            if fcf > 0:
                score += 20; reasons.append("Positive free cash flow")
        except Exception:
            pass

    margins = _safe_get(fundamentals, 'profitMargins', 'operatingMargins', default=None)
    if margins is not None:
        try:
            if margins >= t["margin_good"]:
                score += 15; reasons.append(f"Healthy margins: {margins:.2f}")
            elif margins >= t["margin_min"]:
                score += 6; reasons.append(f"Acceptable margins: {margins:.2f}")
        except Exception:
            pass

    pb = _safe_get(fundamentals, 'priceToBook', default=None)
    pe = _safe_get(fundamentals, 'trailingPE', 'forwardPE', default=None)
    if pb is not None:
        try:
            if pb <= t["pb_good"]:
                score += 10; reasons.append(f"Low P/B: {pb:.2f}")
        except Exception:
            pass
    if pe is not None:
        try:
            if pe <= t["pe_good"]:
                score += 10; reasons.append(f"Reasonable P/E: {pe:.2f}")
        except Exception:
            pass

    rsi = indicators.get('rsi')
    if rsi is not None and 30 <= rsi <= 65:
        score += 5; reasons.append(f"RSI in reasonable range: {rsi}")

    return min(int(round(score)), 100), reasons


def score_graham(indicators: dict, fundamentals: dict, sector: str = None) -> Tuple[int, List[str]]:
    """Graham-style value discipline: margin of safety, low debt, reasonable valuation."""
    score = 0
    reasons = []
    t = get_sector_thresholds(sector)

    pb = _safe_get(fundamentals, 'priceToBook', default=None)
    if pb is not None:
        try:
            if pb <= t["pb_good"]:
                score += 30; reasons.append(f"Strong Graham value: P/B {pb:.2f}")
            elif pb <= t["pb_max"]:
                score += 18; reasons.append(f"Reasonable Graham value: P/B {pb:.2f}")
        except Exception:
            pass

    pe = _safe_get(fundamentals, 'trailingPE', 'forwardPE', default=None)
    if pe is not None:
        try:
            if pe <= t["pe_good"]:
                score += 25; reasons.append(f"Graham-style earnings valuation: PE {pe:.2f}")
            elif pe <= t["pe_max"]:
                score += 12; reasons.append(f"Acceptable PE: {pe:.2f}")
        except Exception:
            pass

    debt = _safe_get(fundamentals, 'debtToEquity', default=None)
    if debt is not None:
        try:
            if debt <= t["debt_good"]:
                score += 20; reasons.append(f"Low leverage: D/E {debt:.2f}")
            elif debt <= t["debt_max"]:
                score += 8; reasons.append(f"Moderate leverage: D/E {debt:.2f}")
        except Exception:
            pass

    fcf = _safe_get(fundamentals, 'freeCashflow', default=None)
    if fcf is not None:
        try:
            if fcf > 0:
                score += 15; reasons.append("Positive free cash flow supports safety")
        except Exception:
            pass

    return min(int(round(score)), 100), reasons


def score_lynch(indicators: dict, fundamentals: dict) -> Tuple[int, List[str]]:
    """Lynch-style scoring: understandable growth companies with fair valuation."""
    score = 0
    reasons = []

    growth = _safe_get(fundamentals, 'earningsQuarterlyGrowth', 'earningsGrowth', default=None)
    if growth is not None:
        try:
            if growth >= 0.20:
                score += 30; reasons.append(f"Strong growth: {growth:.2f}")
            elif growth >= 0.10:
                score += 18; reasons.append(f"Healthy growth: {growth:.2f}")
        except Exception:
            pass

    pe = _safe_get(fundamentals, 'trailingPE', 'forwardPE', default=None)
    if pe is not None and growth is not None:
        try:
            peg = float(pe) / (float(growth) * 100 if growth > 0 else 1)
            if peg <= 1.5:
                score += 20; reasons.append(f"PEG-friendly: {peg:.2f}")
            elif peg <= 2.5:
                score += 10; reasons.append(f"Reasonable PEG: {peg:.2f}")
        except Exception:
            pass

    rsi = indicators.get('rsi')
    if rsi is not None and 40 <= rsi <= 70:
        score += 15; reasons.append(f"Healthy RSI for growth entry: {rsi}")

    market_cap = _safe_get(fundamentals, 'marketCap', default=None)
    if market_cap is not None:
        try:
            if 2e9 <= market_cap <= 8e10:
                score += 15; reasons.append("Mid-cap / quality growth profile")
        except Exception:
            pass

    return min(int(round(score)), 100), reasons


def score_templeton(indicators: dict, fundamentals: dict) -> Tuple[int, List[str]]:
    """Templeton-style contrarian turnaround score: value in dislocation and catalyst recovery."""
    score = 0
    reasons = []

    price_drop = indicators.get('pct_from_52w_high', 0)
    if price_drop is not None and price_drop < -20:
        score += 25; reasons.append(f"Material dislocation: {price_drop:.2f}% below 52w high")
    elif price_drop is not None and price_drop < -10:
        score += 12; reasons.append(f"Moderate value gap: {price_drop:.2f}% below 52w high")

    vol_ratio = indicators.get('volume_ratio', 0)
    if vol_ratio is not None and vol_ratio >= 1.5:
        score += 20; reasons.append(f"Recovery volume: {vol_ratio:.2f}x average")
    elif vol_ratio is not None and vol_ratio >= 1.2:
        score += 10; reasons.append(f"Improving volume: {vol_ratio:.2f}x average")

    rsi = indicators.get('rsi')
    if rsi is not None and rsi < 45:
        score += 15; reasons.append(f"Oversold setup: RSI {rsi}")
    elif rsi is not None and 45 <= rsi <= 60:
        score += 10; reasons.append(f"Recovery zone: RSI {rsi}")

    change_pct = indicators.get('price_change_pct', 0)
    if change_pct is not None and change_pct > 0:
        score += 10; reasons.append(f"Positive recovery day: +{change_pct:.2f}%")

    return min(int(round(score)), 100), reasons


def score_greenblatt(indicators: dict, fundamentals: dict, sector: str = None) -> Tuple[int, List[str]]:
    """Greenblatt-style: high ROIC and earnings yield, simple quality-adjusted valuation."""
    score = 0
    reasons = []
    t = get_sector_thresholds(sector)

    roce = _safe_get(fundamentals, 'returnOnCapitalEmployed', default=None)
    if roce is not None:
        try:
            if roce >= t["roce_good"]:
                score += 35; reasons.append(f"Excellent ROIC: {roce:.2f}")
            elif roce >= t["roce_min"]:
                score += 20; reasons.append(f"Strong ROIC: {roce:.2f}")
        except Exception:
            pass

    pe = _safe_get(fundamentals, 'trailingPE', 'forwardPE', default=None)
    if pe is not None:
        try:
            if pe <= t["pe_good"]:
                score += 25; reasons.append(f"High earnings yield: PE {pe:.2f}")
            elif pe <= t["pe_max"]:
                score += 12; reasons.append(f"Reasonable earnings yield: PE {pe:.2f}")
        except Exception:
            pass

    fcf = _safe_get(fundamentals, 'freeCashflow', default=None)
    if fcf is not None:
        try:
            if fcf > 0:
                score += 15; reasons.append("Positive cash generation")
        except Exception:
            pass

    return min(int(round(score)), 100), reasons


def score_marks(indicators: dict, fundamentals: dict) -> Tuple[int, List[str]]:
    """Marks-style risk discipline: avoid poor liquidity, weak trend, and excessive uncertainty."""
    score = 0
    reasons = []

    adx = indicators.get('adx', 0)
    if adx is not None and adx >= 25:
        score += 25; reasons.append(f"Trend is strong: ADX {adx}")
    elif adx is not None and adx >= 20:
        score += 12; reasons.append(f"Adequate trend: ADX {adx}")
    else:
        score -= 5; reasons.append(f"Weak trend: ADX {adx}")

    debt = _safe_get(fundamentals, 'debtToEquity', default=None)
    if debt is not None:
        try:
            if debt <= 1:
                score += 20; reasons.append(f"Balance sheet discipline: D/E {debt:.2f}")
            elif debt <= 2:
                score += 8; reasons.append(f"Moderate leverage: D/E {debt:.2f}")
        except Exception:
            pass

    vol_ratio = indicators.get('volume_ratio', 0)
    if vol_ratio is not None and vol_ratio >= 1.2:
        score += 15; reasons.append(f"Healthy participation: {vol_ratio:.2f}x volume")

    change_pct = indicators.get('price_change_pct', 0)
    if change_pct is not None and abs(change_pct) <= 2.0:
        score += 10; reasons.append(f"Controlled daily move: {change_pct:.2f}%")
    elif change_pct is not None and change_pct < -3.0:
        score -= 10; reasons.append(f"Excessive downside move: {change_pct:.2f}%")

    score = max(0, min(int(round(score)), 100))
    return score, reasons


def score_rakesh(indicators: dict, fundamentals: dict) -> Tuple[int, List[str]]:
    """Jhunjhunwala-inspired heuristic scoring.

    Focuses on mid-cap / promoter conviction, earnings momentum
    and reasonable valuation. These are heuristic and tuned for
    screening rather than exact replication of any individual's
    process.
    """
    score = 0
    reasons = []

    market_cap = _safe_get(fundamentals, 'marketCap', default=None)
    if market_cap is not None:
        try:
            # favour mid-cap range (heuristic). YFinance marketCap in native currency/units.
            if 2e9 <= market_cap <= 8e10:
                score += 20; reasons.append("Mid-cap/large growth segment")
        except Exception:
            pass

    earnings_growth = _safe_get(fundamentals, 'earningsQuarterlyGrowth', 'earningsGrowth', default=None)
    if earnings_growth is not None:
        try:
            if earnings_growth >= 0.15:
                score += 30; reasons.append(f"Strong earnings growth: {earnings_growth:.2f}")
            elif earnings_growth >= 0.05:
                score += 12; reasons.append(f"Earnings growth: {earnings_growth:.2f}")
        except Exception:
            pass

    insider = _safe_get(fundamentals, 'heldPercentInsiders', default=None)
    if insider is not None:
        try:
            if insider >= 0.10:
                score += 15; reasons.append(f"High insider/promoter holding: {insider:.2f}")
        except Exception:
            pass

    # Technical and momentum checks (Jhunjhunwala often used conviction + momentum)
    macd = indicators.get('macd_hist')
    if macd is not None and macd > 0:
        score += 10; reasons.append("Positive MACD histogram")

    rsi = indicators.get('rsi')
    if rsi is not None and 40 <= rsi <= 70:
        score += 10; reasons.append(f"Healthy RSI: {rsi}")

    # valuation softness: prefer reasonable PE
    pe = _safe_get(fundamentals, 'trailingPE', 'forwardPE', default=None)
    if pe is not None:
        try:
            if pe <= 30:
                score += 10; reasons.append(f"Acceptable P/E: {pe:.2f}")
        except Exception:
            pass

    return min(int(round(score)), 100), reasons


def score_roce_reinvest(indicators: dict, fundamentals: dict, roce_threshold: float = None, reinvest_threshold: float = 0.6, sector: str = None) -> tuple:
    """Score companies by ROCE and reinvestment rate.

    Returns (score 0-100, reasons list, metrics dict).
    Uses best-effort fallbacks from yfinance `info` keys.
    """
    score = 0
    reasons = []
    metrics = {"roce": None, "reinvest": None}

    # Use sector-aware ROCE threshold if not explicitly provided
    if roce_threshold is None:
        t = get_sector_thresholds(sector)
        roce_threshold = t["roce_min"]

    # Try direct ROCE if available
    roce = _safe_get(fundamentals, 'returnOnCapitalEmployed', default=None)
    # Prefer FinancialModelingPrep computed 3-year ROCE if available (via fundamentals_api)
    try:
        from fundamentals_api import compute_3yr_roce_and_reinvest
        sym = fundamentals.get('symbol') or fundamentals.get('ticker')
        if sym:
            fmp_metrics = compute_3yr_roce_and_reinvest(sym if sym.endswith('.NS') or '.' in sym else sym + '.NS')
            if fmp_metrics.get('avg_roce') is not None:
                roce = fmp_metrics.get('avg_roce')
            if fmp_metrics.get('avg_reinvest') is not None:
                metrics['reinvest'] = fmp_metrics.get('avg_reinvest')
    except Exception:
        pass
    if roce is None:
        # Best-effort compute: use EBITDA (approx) over (Total Assets - Current Liabilities)
        ebitda = _safe_get(fundamentals, 'ebitda', default=None)
        total_assets = _safe_get(fundamentals, 'totalAssets', default=None)
        current_liab = _safe_get(fundamentals, 'currentLiabilities', 'totalCurrentLiabilities', default=None)
        try:
            if ebitda is not None and total_assets is not None and current_liab is not None:
                denom = (total_assets - current_liab)
                if denom and denom != 0:
                    roce = float(ebitda) / float(denom)
        except Exception:
            roce = None

    if roce is not None:
        try:
            metrics['roce'] = round(float(roce), 4)
            if float(roce) >= roce_threshold:
                score += 50; reasons.append(f"ROCE {metrics['roce']*100:.1f}% > {roce_threshold*100:.0f}%")
            elif float(roce) >= (roce_threshold - 0.03):
                score += 25; reasons.append(f"ROCE {metrics['roce']*100:.1f}% (near threshold)")
        except Exception:
            pass

    # Reinvestment: prefer payoutRatio fallback to capex/netIncome
    reinvest = None
    payout = _safe_get(fundamentals, 'payoutRatio', default=None)
    if payout is not None:
        try:
            reinvest = 1.0 - float(payout)
        except Exception:
            reinvest = None

    if reinvest is None:
        capex = _safe_get(fundamentals, 'capitalExpenditures', 'capitalExpenditure', default=None)
        netincome = _safe_get(fundamentals, 'netIncomeToCommon', 'netIncome', default=None)
        try:
            if capex is not None and netincome is not None and float(netincome) != 0:
                reinvest = abs(float(capex)) / abs(float(netincome))
        except Exception:
            reinvest = None

    if reinvest is not None:
        try:
            metrics['reinvest'] = round(float(reinvest), 4)
            if float(reinvest) >= reinvest_threshold:
                score += 50; reasons.append(f"Reinvest {metrics['reinvest']*100:.0f}% >= {reinvest_threshold*100:.0f}%")
            elif float(reinvest) >= (reinvest_threshold - 0.2):
                score += 20; reasons.append(f"Reinvest {metrics['reinvest']*100:.0f}% (moderate)")
        except Exception:
            pass

    # If neither metric present, give neutral small score
    if metrics['roce'] is None and metrics['reinvest'] is None:
        reasons.append("Insufficient ROCE/reinvestment data")
        score += 10

    return min(int(round(score)), 100), reasons, metrics
