"""
tune.py — Parameter tuning for EMA trend strategy using simple walk-forward

Performs a grid search over EMA short/long windows, volume confirmation, and ATR multiplier.
Saves results to `tuning_results.json` with aggregate portfolio CAGR for each parameter set.
"""
import json
import itertools
from datetime import datetime
import numpy as np
import pandas as pd
import yfinance as yf
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from screener import NSE_STOCKS


def compute_indicators(df, short=21, long=50):
    close = df['Close']
    high = df['High']
    low = df['Low']
    vol = df['Volume']
    ema_s = EMAIndicator(close, window=short).ema_indicator()
    ema_l = EMAIndicator(close, window=long).ema_indicator()
    macd = MACD(close).macd_diff()
    rsi = RSIIndicator(close, window=14).rsi()
    atr = AverageTrueRange(high, low, close, window=14).average_true_range()
    ind = pd.DataFrame({'open': df['Open'], 'close': close, 'ema_s': ema_s, 'ema_l': ema_l,
                        'macd': macd, 'rsi': rsi, 'atr': atr, 'vol': vol}, index=df.index)
    return ind


def backtest_portfolio_with_params(universe, start, end, short, long, vol_thresh, atr_mult):
    # Use portfolio-level backtester to evaluate parameter set for consistency with portfolio objective
    from portfolio_backtest import run_portfolio_backtest
    # run backtest (will write portfolio_backtest_report.json)
    try:
        run_portfolio_backtest(universe=universe, start=start, end=end, short=short, long=long, vol_thresh=vol_thresh, atr_mult=atr_mult)
        with open('portfolio_backtest_report.json') as f:
            rep = json.load(f)
        return rep.get('cagr')
    except Exception:
        return None


def run_grid():
    # Reduced grid for faster tuning run — adjust if you want a larger search
    shorts = [15, 21]
    longs = [50, 100]
    vol_th = [1.5]
    atr_mults = [3]
    start = '2018-01-01'
    end = datetime.today().strftime('%Y-%m-%d')

    results = []
    for short, long, vol_t, atr_m in itertools.product(shorts, longs, vol_th, atr_mults):
        if short >= long:
            continue
        print(f"Testing short={short} long={long} vol={vol_t} atr={atr_m}")
        avg_cagr = backtest_portfolio_with_params(NSE_STOCKS, start, end, short, long, vol_t, atr_m)
        results.append({'short': short, 'long': long, 'vol_thresh': vol_t, 'atr_mult': atr_m, 'avg_cagr': avg_cagr})
    with open('tuning_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print('Tuning complete. Results saved to tuning_results.json')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Tuning harness')
    parser.add_argument('--walkforward', action='store_true', help='Run walk-forward tuning')
    parser.add_argument('--start', type=str, default='2015-01-01')
    parser.add_argument('--end', type=str, default=datetime.today().strftime('%Y-%m-%d'))
    parser.add_argument('--train-years', type=int, default=3)
    parser.add_argument('--test-years', type=int, default=1)
    parser.add_argument('--save', type=str, default='tuning_walkforward.json')
    args = parser.parse_args()

    if args.walkforward:
        # expanded grid for walk-forward
        shorts = [10, 15, 21]
        longs = [50, 100, 150]
        vol_th = [1.2, 1.5, 2.0]
        atr_mults = [2, 3]

        # walk-forward windows
        start = args.start
        end = args.end
        train_years = args.train_years
        test_years = args.test_years

        # build rolling windows
        from dateutil.relativedelta import relativedelta
        import pandas as pd

        sdate = pd.to_datetime(start)
        edate = pd.to_datetime(end)
        windows = []
        cur_train_start = sdate
        while True:
            train_end = cur_train_start + relativedelta(years=train_years) - pd.Timedelta(days=1)
            test_start = train_end + pd.Timedelta(days=1)
            test_end = test_start + relativedelta(years=test_years) - pd.Timedelta(days=1)
            if test_end > edate:
                break
            windows.append({'train_start': str(cur_train_start.date()), 'train_end': str(train_end.date()),
                            'test_start': str(test_start.date()), 'test_end': str(test_end.date())})
            # advance by test period (walk forward)
            cur_train_start = cur_train_start + relativedelta(years=test_years)

        all_results = {'windows': [], 'summary': {}}
        from collections import Counter
        best_counts = Counter()
        oos_perfs = []

        for w in windows:
            print(f"Window: {w['train_start']} -> {w['train_end']} | Test: {w['test_start']} -> {w['test_end']}")
            # evaluate grid on training
            best_score = None
            best_params = None
            for short, long, vol_t, atr_m in itertools.product(shorts, longs, vol_th, atr_mults):
                if short >= long:
                    continue
                score = backtest_portfolio_with_params(NSE_STOCKS, w['train_start'], w['train_end'], short, long, vol_t, atr_m)
                if score is None:
                    continue
                if best_score is None or score > best_score:
                    best_score = score
                    best_params = {'short': short, 'long': long, 'vol_thresh': vol_t, 'atr_mult': atr_m}
            if best_params is None:
                print('  No viable params for this window')
                continue
            print(f"  Best params on train: {best_params} -> avg_cagr {best_score}")
            best_counts[tuple(best_params.items())] += 1
            # evaluate selected params on test window
            oos = backtest_portfolio_with_params(NSE_STOCKS, w['test_start'], w['test_end'], **best_params)
            print(f"  OOS performance (avg_cagr): {oos}")
            if oos is not None:
                oos_perfs.append(oos)
            all_results['windows'].append({'window': w, 'best_params': best_params, 'train_score': best_score, 'oos_score': oos})

        # summary
        from statistics import mean
        all_results['summary']['num_windows'] = len(all_results['windows'])
        all_results['summary']['avg_oos_cagr'] = mean(oos_perfs) if oos_perfs else None
        all_results['summary']['best_param_frequency'] = {str(k): v for k, v in best_counts.items()}

        with open(args.save, 'w') as f:
            json.dump(all_results, f, indent=2, default=str)
        print('Walk-forward tuning complete. Results saved to', args.save)
    else:
        run_grid()
