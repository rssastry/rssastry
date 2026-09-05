import warnings
warnings.filterwarnings("ignore")
import validate_buy_logic as v
from screener import StockScreener
from data_cache import fetch_history

df = fetch_history("SUNPHARMA.NS", period="2y", interval="1d").copy()
df.attrs["_symbol"] = "SUNPHARMA"
hi = v.HistoryIndicators(df)
t = hi.n - 2  # signal bar = second-to-last
print("signal bar date:", hi.index[t].date())

prod_df = fetch_history("SUNPHARMA.NS", period="2y", interval="1d").copy()
ind_prod = StockScreener().compute_indicators(prod_df)
ind_sim = hi.slice(t)

keys = ["current_price", "price_change_pct", "rsi", "macd_hist", "macd_crossover",
        "ema9", "ema21", "ema50", "adx", "atr", "atr_pct", "volume_ratio",
        "effective_vol_ratio", "multi_tf_confirm", "weekly_trend",
        "buy_rule_passed", "fresh_bullish_trigger", "recent_reversal_day",
        "reclaims_reversal_level", "high_52w", "pct_from_52w_high", "bb_pct",
        "volume", "avg_volume_20d"]
for k in keys:
    p = ind_prod.get(k, "MISSING")
    s = ind_sim.get(k, "MISSING")
    mark = "" if str(p) == str(s) else "   <<<< DIFF"
    if isinstance(p, float) and isinstance(s, float):
        mark = "" if abs(p - s) < 0.5 else "   <<<< DIFF"
    print("{:<24} prod={!s:>24}  sim={!s:>24}{}".format(k, p, s, mark))

# gate check both ways
ok_prod, fails_prod = StockScreener().evaluate_buy_eligibility(ind_prod, "positional")
ok_sim, fails_sim = StockScreener().evaluate_buy_eligibility(ind_sim, "positional")
print("\nprod gate positional BUY:", ok_prod, "| fails:", fails_prod)
print("sim  gate positional BUY:", ok_sim, "| fails:", fails_sim)