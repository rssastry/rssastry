"""
portfolio_backtest.py — portfolio-level backtest for EMA trend strategy

Simulates an equal-weighted portfolio that:
- scans the universe daily for buy signals (EMA21>EMA50 crossover with confirmation)
- opens positions at next-day open, equal weight up to `max_positions`
- exits when EMA21<EMA50 or price < EMA50 or ATR stop hit

Outputs `portfolio_backtest_report.json` with equity curve and metrics.
"""
import json
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import yfinance as yf
from ta.trend import EMAIndicator, MACD
from price_store import load_adjusted
from config import RISK_PER_TRADE, FIXED_TXN_FEE
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
    ind = pd.DataFrame({'open': df['Open'], 'close': close, 'high': high, 'low': low,
                        'ema_s': ema_s, 'ema_l': ema_l, 'macd': macd, 'rsi': rsi,
                        'atr': atr, 'vol': vol}, index=df.index)
    return ind


def fetch_all_data(universe, start, end, short=21, long=50):
    data = {}
    for s in universe:
        try:
            df = load_adjusted(s, start=start, end=end, interval='1d')
            if df is None or len(df) < 60:
                continue
            # normalize timezone-aware index to tz-naive for consistent comparisons
            try:
                if getattr(df.index, 'tz', None) is not None:
                    df.index = df.index.tz_localize(None)
            except Exception:
                pass
            data[s] = compute_indicators(df, short=short, long=long)
        except Exception:
            continue
    return data


def run_portfolio_backtest(universe=None, start='2018-01-01', end=None,
                           initial_cash=100000, max_positions=10,
                           txn_cost=0.001, slippage=0.0005,
                           short=15, long=50, vol_thresh=1.5, atr_mult=3,
                           risk_per_trade=RISK_PER_TRADE, fixed_txn_fee=FIXED_TXN_FEE):
    if universe is None:
        universe = NSE_STOCKS
    if end is None:
        end = datetime.today().strftime('%Y-%m-%d')

    print('Fetching historical data (this may take a few minutes)...')
    data = fetch_all_data(universe, start, end, short=short, long=long)
    symbols = sorted(data.keys())
    if not symbols:
        print('No symbols with enough data')
        return

    # build calendar (intersection of dates)
    dates = None
    for df in data.values():
        if dates is None:
            dates = set(df.index)
        else:
            dates &= set(df.index)
    dates = sorted(list(dates))
    dates = [d for d in dates if d >= pd.to_datetime(start)]

    cash = initial_cash
    positions = {}  # symbol -> {'qty', 'entry_price', 'entry_date', 'entry_atr'}
    equity_curve = []
    portfolio_value = initial_cash

    for today in dates[:-1]:
        # collect buy signals for today (generate for next open)
        buys = []
        sells = []
        for s in symbols:
            df = data[s]
            if today not in df.index:
                continue
            idx = df.index.get_loc(today)
            if idx < 1 or idx+1 >= len(df):
                continue
            today_row = df.iloc[idx]
            prev_row = df.iloc[idx-1]

            # buy signal detection
            buy_signal = False
            if prev_row['ema_s'] <= prev_row['ema_l'] and today_row['ema_s'] > today_row['ema_l']:
                # confirmation
                vol_window = df['vol'].iloc[max(0, idx-20):idx]
                avg_vol20 = vol_window.mean() if len(vol_window) > 0 else 0
                vol_ratio = today_row['vol'] / avg_vol20 if avg_vol20 > 0 else 0
                if (vol_ratio >= vol_thresh or today_row['macd'] > 0) and 45 <= (today_row['rsi'] or 0) <= 65:
                    buy_signal = True

            # sell detection for positions
            if s in positions:
                in_pos = positions[s]
                sell_signal = False
                if prev_row['ema_s'] >= prev_row['ema_l'] and today_row['ema_s'] < today_row['ema_l']:
                    sell_signal = True
                if today_row['close'] < today_row['ema_l']:
                    sell_signal = True
                if today_row['close'] < in_pos['entry_price'] - atr_mult * in_pos['entry_atr']:
                    sell_signal = True
                if sell_signal:
                    sells.append(s)

            if buy_signal and s not in positions:
                buys.append(s)

        # execute sells at next day's open
        next_day = pd.to_datetime(today) + pd.Timedelta(days=1)
        # find nearest available date in calendar
        nxt = None
        for d in dates:
            if d > today:
                nxt = d
                break
        if nxt is None:
            break

        # process sells first to free cash
        for s in sells:
            if s not in positions:
                continue
            df = data[s]
            if nxt not in df.index:
                continue
            row = df.loc[nxt]
            price = row['open'] * (1 - slippage)
            cost = price * txn_cost + fixed_txn_fee
            exit_price = price - price * txn_cost
            qty = positions[s]['qty']
            proceeds = qty * exit_price - fixed_txn_fee
            cash += proceeds
            del positions[s]

        # allocate using ATR-based sizing to limit per-trade risk
        available_slots = max(0, max_positions - len(positions))
        if buys and available_slots > 0:
            buys = sorted(buys)[:available_slots]
            for s in buys:
                df = data[s]
                if nxt not in df.index:
                    continue
                row = df.loc[nxt]
                price = row['open'] * (1 + slippage)
                atr = row.get('atr', None)
                if atr is None or atr <= 0:
                    continue
                # risk per trade (INR)
                portfolio_value = cash + sum([p['qty'] * data[t]['close'].iloc[-1] for t, p in positions.items() if t in data])
                risk_amt = portfolio_value * risk_per_trade
                stop_distance = atr * atr_mult
                qty = int(risk_amt // stop_distance) if stop_distance>0 else 0
                if qty <= 0:
                    continue
                # ensure we have enough cash
                cost = qty * price + fixed_txn_fee + qty * price * txn_cost
                if cost > cash:
                    # scale down qty
                    qty = int((cash - fixed_txn_fee) // (price * (1 + txn_cost)))
                    if qty <= 0:
                        continue
                    cost = qty * price + fixed_txn_fee + qty * price * txn_cost
                cash -= cost
                positions[s] = {'qty': qty, 'entry_price': price + price*txn_cost, 'entry_date': nxt, 'entry_atr': row['atr']}

        # compute portfolio value at close of today
        pv = cash
        for s, pos in positions.items():
            df = data.get(s)
            if df is None:
                continue
            if today in df.index:
                price = df.loc[today]['close']
            else:
                # use last available
                price = df['close'].iloc[-1]
            pv += pos['qty'] * price
        equity_curve.append({'date': str(today.date()), 'portfolio_value': pv})

    # finalize: compute metrics
    pv_series = np.array([p['portfolio_value'] for p in equity_curve])
    dates_series = [pd.to_datetime(p['date']) for p in equity_curve]
    returns = np.diff(pv_series) / pv_series[:-1]
    total_return = pv_series[-1] / pv_series[0] - 1 if len(pv_series)>1 else 0.0
    years = (dates_series[-1] - dates_series[0]).days / 365.25 if len(dates_series)>1 else 1
    cagr = (1 + total_return) ** (1/years) - 1 if years>0 else 0.0
    ann_vol = np.std(returns) * np.sqrt(252) if len(returns)>1 else 0.0
    sharpe = (cagr / ann_vol) if ann_vol>0 else None
    peak = np.maximum.accumulate(pv_series)
    drawdowns = (pv_series - peak) / peak
    max_dd = float(np.min(drawdowns)) if len(drawdowns)>0 else 0.0

    out = {
        'initial_cash': initial_cash,
        'final_value': float(pv_series[-1]) if len(pv_series)>0 else initial_cash,
        'total_return': round(float(total_return),4),
        'cagr': round(float(cagr),4),
        'annual_volatility': round(float(ann_vol),4),
        'sharpe': round(float(sharpe),4) if sharpe is not None else None,
        'max_drawdown': round(float(max_dd),4),
        'equity_curve': equity_curve,
        'positions_count': len(positions),
    }

    with open('portfolio_backtest_report.json', 'w') as f:
        json.dump(out, f, indent=2, default=str)

    print('Portfolio backtest complete. Report saved to portfolio_backtest_report.json')


if __name__ == '__main__':
    run_portfolio_backtest()
