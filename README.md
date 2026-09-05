# StockAnalysis
Analyze the stocks

## Historical data maintenance

The application stores daily OHLCV data in `data_cache/` as period-specific
Parquet files. The default validation window is configured in `config.py` as
`HISTORICAL_DATA_PERIOD = "5y"`. The cache key includes the symbol, requested
period, date range, and interval, so a five-year daily dataset is not mixed with
shorter or intraday data.

Run a five-year validation with:

```text
.venv\Scripts\python.exe validate_buy_logic.py --symbols 140 --period 5y --json validation_5y.json
```

Refresh is automatic when a cached file is older than `CACHE_TTL_HOURS`.
Keep the cache directory persistent and rerun the validation after each scan or
at least weekly. Review `history_period`, `symbols_tested`, and the number of
trades in the generated report before trusting performance conclusions. A
five-year price/volume history does not provide five years of historical
fundamentals; those must be stored as dated snapshots if the fundamental score
is to be backtested without look-ahead bias.

Each screener run records the quality fields it received in
`data_cache/fundamental_snapshots/<SYMBOL>.jsonl`, keyed by capture date. Keep
these files backed up. They become useful for point-in-time tests after enough
history has accumulated, but they do not recreate older data.

For a true five-year fundamental backtest, use a provider that supplies
point-in-time historical fundamentals and valuation ratios. Import each value
with both `period_end` and `available_date`; the backtest must use
`available_date` so it never uses information before publication.
