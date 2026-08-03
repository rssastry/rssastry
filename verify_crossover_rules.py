import numpy as np
import pandas as pd
from ta.trend import EMAIndicator
from indicators import IndicatorEngine

# Build a synthetic series that should trigger both bullish and bearish crossover checks.
dates = pd.date_range('2024-01-01', periods=90, freq='D')
close = np.concatenate([
    np.linspace(100, 110, 30),
    np.linspace(110, 170, 30),
    np.linspace(170, 130, 30),
])
open_ = close - 0.5
high = close + 1.0
low = close - 1.0
volume = np.ones(90, dtype=float) * 1_000_000
volume[60] = 3_500_000

frame = pd.DataFrame({
    'Open': open_,
    'High': high,
    'Low': low,
    'Close': close,
    'Volume': volume,
}, index=dates)

engine = IndicatorEngine('TEST.NS')
engine.df = frame
result = engine.compute_all()

print('buy_rule_passed:', result.get('buy_rule_passed'))
print('sell_rule_passed:', result.get('sell_rule_passed'))
print('buy_rule_details:', result.get('buy_rule_details'))
print('sell_rule_details:', result.get('sell_rule_details'))
