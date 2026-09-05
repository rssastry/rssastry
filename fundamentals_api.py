import os
import json
import requests
from datetime import datetime

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'data_cache', 'fundamentals')
os.makedirs(CACHE_DIR, exist_ok=True)


def _get_api_key():
    return os.environ.get('FMP_API_KEY')


def _cache_path(symbol: str):
    return os.path.join(CACHE_DIR, f"{symbol.replace('.NS','')}.json")


def fetch_fmp_financials(symbol: str, force_refresh: bool = False) -> dict:
    """Fetch annual income, balance sheet, cash-flow from FinancialModelingPrep and cache result.

    Requires env var FMP_API_KEY. Returns dict with keys: income, balance, cashflow.
    """
    key = _get_api_key()
    symbol_clean = symbol.replace('.NS', '')
    path = _cache_path(symbol)
    if os.path.exists(path) and not force_refresh:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass

    if not key:
        return {}

    base = 'https://financialmodelingprep.com/api/v3'
    out = {}
    try:
        inc_url = f"{base}/income-statement/{symbol_clean}?period=annual&limit=5&apikey={key}"
        bal_url = f"{base}/balance-sheet-statement/{symbol_clean}?period=annual&limit=5&apikey={key}"
        cf_url  = f"{base}/cash-flow-statement/{symbol_clean}?period=annual&limit=5&apikey={key}"

        inc_r = requests.get(inc_url, timeout=10)
        bal_r = requests.get(bal_url, timeout=10)
        cf_r  = requests.get(cf_url, timeout=10)

        if inc_r.ok:
            out['income'] = inc_r.json()
        if bal_r.ok:
            out['balance'] = bal_r.json()
        if cf_r.ok:
            out['cashflow'] = cf_r.json()

        out['fetched_at'] = datetime.utcnow().isoformat()
        with open(path, 'w') as f:
            json.dump(out, f)
        return out
    except Exception:
        return {}


def compute_3yr_roce_and_reinvest(symbol: str) -> dict:
    """Compute 3-year average ROCE and cashflow-based reinvestment using FMP data.

    Returns dict: { 'avg_roce': float or None, 'avg_reinvest': float or None, 'years': n }
    """
    data = fetch_fmp_financials(symbol)
    inc = data.get('income') or []
    bal = data.get('balance') or []
    cf  = data.get('cashflow') or []

    # align by fiscalDate
    years = []
    for item in inc:
        years.append(item.get('date'))
    # compute per-year metrics for up to 3 recent matching years
    roce_vals = []
    reinv_vals = []
    count = 0
    for i, year in enumerate(years[:5]):
        # find matching entries
        inc_y = next((x for x in inc if x.get('date') == year), None)
        bal_y = next((x for x in bal if x.get('date') == year), None)
        cf_y  = next((x for x in cf if x.get('date') == year), None)
        if not inc_y or not bal_y:
            continue
        try:
            # EBIT/operatingIncome
            ebit = inc_y.get('operatingIncome') or inc_y.get('ebit') or inc_y.get('ebitda')
            total_assets = bal_y.get('totalAssets')
            current_liab = bal_y.get('totalCurrentLiabilities') or bal_y.get('currentLiabilities') or 0
            if ebit is not None and total_assets is not None:
                denom = float(total_assets) - float(current_liab or 0)
                if denom and float(denom) != 0:
                    roce = float(ebit) / float(denom)
                    roce_vals.append(roce)
        except Exception:
            pass
        try:
            # reinvest: capex / netIncome using cashflow and income
            capex = cf_y.get('capitalExpenditure') if cf_y else None
            netinc = inc_y.get('netIncome') or inc_y.get('netIncomeBasic') or inc_y.get('netIncomeApplicableToCommonStockholders')
            if capex is not None and netinc is not None and float(netinc) != 0:
                reinv = abs(float(capex)) / abs(float(netinc))
                reinv_vals.append(reinv)
        except Exception:
            pass
        count += 1
        if len(roce_vals) >= 3 and len(reinv_vals) >= 3:
            break

    out = {
        'avg_roce': round(sum(roce_vals)/len(roce_vals), 6) if roce_vals else None,
        'avg_reinvest': round(sum(reinv_vals)/len(reinv_vals), 6) if reinv_vals else None,
        'years_used': min(3, len(roce_vals), len(reinv_vals))
    }
    return out
