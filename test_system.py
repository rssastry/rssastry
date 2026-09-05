"""Quick verification of the current trading system.

Runs import + object-level smoke checks over the modules that power the daily
scan and the buy-suggestion pipeline. Requires no network access - the
indicator engine, screener classes, config and portfolio helpers are local.

Run:  python test_system.py
"""
import warnings
warnings.filterwarnings("ignore")


def test_imports():
    from config import (MAX_POSITIONS, MAX_CORRELATION, MAX_SECTOR_PCT,
                        MAX_ACCOUNT_RISK_PCT, MAX_STOP_DISTANCE_PCT_BY_STYLE,
                        BUY_MIN_ENSEMBLE, VOLUME_CONFIRMATION_MARGIN,
                        MARKET_REGIME_FAIL_CLOSED)
    print(f"[OK] config: max_pos={MAX_POSITIONS}, corr={MAX_CORRELATION}, "
          f"sector_cap={MAX_SECTOR_PCT}, risk_cap={MAX_ACCOUNT_RISK_PCT}")
    print(f"  buy_min_ensemble={BUY_MIN_ENSEMBLE}, "
          f"vol_margin={VOLUME_CONFIRMATION_MARGIN}, "
          f"regime_fail_closed={MARKET_REGIME_FAIL_CLOSED}")
    print(f"  stop_caps={MAX_STOP_DISTANCE_PCT_BY_STYLE}")

    from indicators import IndicatorEngine
    print("[OK] indicators imports OK")

    from screener import StockScreener, market_regime_blocks_buy
    blocked, reason = market_regime_blocks_buy("unknown")
    assert blocked and "fail-closed" in reason, "regime fail-closed broken"
    assert not market_regime_blocks_buy("bullish")[0]
    assert market_regime_blocks_buy("bearish")[0]
    print("[OK] screener imports OK; market-regime fail-closed verified")

    from ai_analyst import AIAnalyst
    print("[OK] ai_analyst imports OK")

    from data_cache import fetch_history
    print("[OK] data_cache imports OK")

    from portfolio import (load_portfolio, validate_holding_fields,
                           check_portfolio_risk, rank_buy_candidates,
                           allocate_portfolio_buy_candidates)
    ok, fails = validate_holding_fields("TEST", 100.0, 10, target=110.0,
                                        stop_loss=95.0, style="swing")
    assert ok, fails
    ok2, fails2 = validate_holding_fields("TEST", 100.0, 0, target=110.0,
                                          stop_loss=95.0, style="swing")
    assert not ok2, "zero quantity should be invalid"
    print("[OK] portfolio imports + validation OK")

    from portfolio_backtest import run_portfolio_backtest
    print("[OK] portfolio_backtest imports OK")

    from backtest import run_backtest
    print("[OK] backtest imports OK")

    print("\nAll system smoke checks passed.")


if __name__ == "__main__":
    try:
        test_imports()
    except Exception as e:
        print(f"FAILED: {e}")
        raise