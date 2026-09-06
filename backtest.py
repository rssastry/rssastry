"""
backtest.py — simple backtest harness for trend buy/exit rules

Rules implemented:
- Buy when EMA21 crosses above EMA50 and (volume spike OR MACD>0) and RSI in [45,65].
- Exit when EMA21 crosses below EMA50 OR price < EMA50 OR price < entry_price - 3*ATR.

Trades execute at next day's Open. Transaction cost and slippage are applied.

Outputs a brief summary to stdout and saves `backtest_report.json` with trades and metrics.
"""
import json
from datetime import datetime
import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange
from screener import NSE_STOCKS


def compute_indicators(df):
    close = df['Close']
    high = df['High']
    low = df['Low']
    vol = df['Volume']

    ema21 = EMAIndicator(close, window=21).ema_indicator()
    ema50 = EMAIndicator(close, window=50).ema_indicator()
    macd = MACD(close).macd_diff()
    rsi = RSIIndicator(close, window=14).rsi()
    atr = AverageTrueRange(high, low, close, window=14).average_true_range()

    ind = pd.DataFrame({
        'close': close,
        'open': df['Open'],
        'ema21': ema21,
        'ema50': ema50,
        'macd': macd,
        'rsi': rsi,
        'atr': atr,
        'vol': vol,
    }, index=df.index)
    return ind


def backtest_symbol(symbol, start='2016-01-01', end=None, txn_cost=0.001, slippage=0.0005):
    from price_store import load_adjusted
    df = load_adjusted(symbol, start=start, end=end)
    if df is None or len(df) < 300:
        return None

    ind = compute_indicators(df)

    positions = []
    in_pos = False
    entry_price = None
    entry_date = None
    entry_atr = None

    for i in range(51, len(ind)-1):
        today = ind.iloc[i]
        prev = ind.iloc[i-1]

        # detect cross: ema21 crosses above ema50
        buy_signal = False
        if prev['ema21'] <= prev['ema50'] and today['ema21'] > today['ema50']:
            # confirmation: volume spike or macd positive
            avg_vol20 = ind['vol'].iloc[i-20:i].mean() if i-20 >= 0 else ind['vol'].iloc[:i].mean()
            vol_ratio = (today['vol'] / avg_vol20) if avg_vol20 and avg_vol20>0 else 0
            if (vol_ratio >= 1.5 or today['macd'] > 0) and 45 <= (today['rsi'] or 0) <= 65:
                buy_signal = True

        # sell detection
        sell_signal = False
        if in_pos:
            # ema21 crosses below ema50
            if prev['ema21'] >= prev['ema50'] and today['ema21'] < today['ema50']:
                sell_signal = True
            # price below ema50
            if today['close'] < today['ema50']:
                sell_signal = True
            # atr trailing stop
            if today['close'] < entry_price - 3 * entry_atr:
                sell_signal = True

        # execute buy at next day's open
        if buy_signal and not in_pos:
            nxt = ind.iloc[i+1]
            price = nxt['open'] * (1 + slippage)
            cost = price * txn_cost
            entry_price = price + cost
            entry_date = nxt.name.strftime('%Y-%m-%d')
            entry_atr = today['atr'] if not np.isnan(today['atr']) else 0
            in_pos = True

        # execute sell at next day's open
        if sell_signal and in_pos:
            nxt = ind.iloc[i+1]
            price = nxt['open'] * (1 - slippage)
            cost = price * txn_cost
            exit_price = price - cost
            exit_date = nxt.name.strftime('%Y-%m-%d')
            ret = (exit_price / entry_price) - 1
            holding_days = (pd.to_datetime(exit_date) - pd.to_datetime(entry_date)).days
            positions.append({
                'entry_date': entry_date,
                'entry_price': round(entry_price,4),
                'exit_date': exit_date,
                'exit_price': round(exit_price,4),
                'return': round(ret,4),
                'holding_days': holding_days,
            })
            in_pos = False
            entry_price = None
            entry_date = None
            entry_atr = None

    # if still in position at end, close at last close
    if in_pos:
        last = ind.iloc[-1]
        exit_price = last['close'] * (1 - slippage) - last['close'] * txn_cost
        exit_date = ind.index[-1].strftime('%Y-%m-%d')
        ret = (exit_price / entry_price) - 1
        holding_days = (pd.to_datetime(exit_date) - pd.to_datetime(entry_date)).days
        positions.append({
            'entry_date': entry_date,
            'entry_price': round(entry_price,4),
            'exit_date': exit_date,
            'exit_price': round(exit_price,4),
            'return': round(ret,4),
            'holding_days': holding_days,
        })

    if not positions:
        return {'symbol': symbol, 'trades': [], 'total_return': 0.0}

    # compute metrics
    returns = [p['return'] for p in positions]
    total_return = np.prod([1 + r for r in returns]) - 1
    wins = sum(1 for r in returns if r > 0)
    win_rate = wins / len(returns)
    avg_return = np.mean(returns)
    avg_holding = np.mean([p['holding_days'] for p in positions])

    years = (ind.index[-1] - ind.index[0]).days / 365.25
    if years > 0:
        cagr = (1 + total_return) ** (1/years) - 1
    else:
        cagr = 0.0

    # max drawdown on equity curve of sequential trades (simplified)
    equity = [1]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    eq = np.array(equity[1:])
    peak = np.maximum.accumulate(eq)
    drawdowns = (eq - peak) / peak
    max_dd = float(np.min(drawdowns)) if len(drawdowns)>0 else 0.0

    return {
        'symbol': symbol,
        'trades': positions,
        'total_return': round(float(total_return),4),
        'cagr': round(float(cagr),4),
        'win_rate': round(float(win_rate),4),
        'avg_return_per_trade': round(float(avg_return),4),
        'avg_holding_days': round(float(avg_holding),1),
        'max_drawdown': round(float(max_dd),4),
        'num_trades': len(positions),
    }


def run_backtest(universe=None, years=5):
    if universe is None:
        universe = NSE_STOCKS
    end = datetime.today().strftime('%Y-%m-%d')
    start = (datetime.today().year - years, datetime.today().month, datetime.today().day)
    start_str = f"{datetime.today().year-years}-01-01"

    results = []
    for s in universe:
        print(f"Backtesting {s}...", end='\r')
        try:
            r = backtest_symbol(s, start=start_str, end=end)
            if r:
                results.append(r)
        except Exception as e:
            continue

    # aggregate
    traded = [r for r in results if r.get('num_trades',0) > 0]
    summary = {
        'symbols_tested': len(results),
        'symbols_with_trades': len(traded),
        'avg_cagr': None,
        'median_cagr': None,
    }
    if traded:
        cagr_vals = [r['cagr'] for r in traded]
        summary['avg_cagr'] = round(float(np.mean(cagr_vals)),4)
        summary['median_cagr'] = round(float(np.median(cagr_vals)),4)

    out = {'summary': summary, 'per_symbol': results}
    with open('backtest_report.json', 'w') as f:
        json.dump(out, f, indent=2, default=str)

    print('\nBacktest complete. Report saved to backtest_report.json')


if __name__ == '__main__':
    run_backtest()
