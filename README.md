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

## Local price files (raw_data/prices)

`raw_data/prices/<SYMBOL>.csv` holds a frozen, per-symbol daily OHLCV history
(the yfinance raw export header `Date,Adj Close,Close,High,Low,Open,Volume`,
CRLF, float64 precision). These files are the local, provider-independent
source for validations and backtests:

```text
.venv\Scripts\python.exe update_price_files.py            # update the universe
.venv\Scripts\python.exe update_price_files.py --dry-run  # report only
.venv\Scripts\python.exe update_price_files.py -s RELIANCE,TCS
```

- The post-close scan (`schedular.job_morning_scan`) refreshes them as Step 0,
  on market days only, so each file ends at the latest completed trading session.
- Existing rows are never re-rendered (byte-preserving merge): only genuinely
  new dates are appended, duplicates are skipped, and a mid-file gap is
  back-filled. Symbols without a CSV yet are back-filled with 5 years.
- A symbol that the data provider currently refuses (throttle / delisted-flag)
  is reported as failed and retried on the next scan; the scan itself continues.
- `price_store.fetch_or_fallback` lets validations/backtests consume these CSVs
  automatically and silently fall back to live yfinance when a file is absent.

Each screener run records the quality fields it received in
`data_cache/fundamental_snapshots/<SYMBOL>.jsonl`, keyed by capture date. Keep
these files backed up. They become useful for point-in-time tests after enough
history has accumulated, but they do not recreate older data.

## Historical fundamentals (free backfill from yfinance statements)

`backfill_fundamental_history.py` reconstructs 5+ years of *point-in-time*
annual fundamentals for the whole universe, for free, from the per-fiscal-year
statements yfinance already exposes (`Ticker.income_stmt`, `.balance_sheet`,
`.cashflow`). Each completed fiscal year becomes one dated record in the same
`data_cache/fundamental_snapshots/<SYMBOL>.jsonl` files the validation harness
reads — no schema change:

```text
.venv\Scripts\python.exe backfill_fundamental_history.py                 # all local symbols
.venv\Scripts\python.exe backfill_fundamental_history.py --dry-run        # report only
.venv\Scripts\python.exe backfill_fundamental_history.py -s RELIANCE.NS,TCS.NS
.venv\Scripts\python.exe backfill_fundamental_history.py --force          # regenerate statement rows
```

- Row `as_of` = fiscal-year end + a 120-day filing buffer, so a signal bar
  dated before `as_of` can never see that annual report (anti-lookahead).
- The newest fiscal-year column is skipped by default (`--no-skip-latest` to
  include it) because Yahoo still labels it an estimate; the daily
  `yfinance.info` captures already cover the recent window.
- Reconstructed fields use the exact names the gate/scorers consume:
  `returnOnEquity`, `returnOnCapitalEmployed`, `debtToEquity`,
  `profitMargins`, `operatingMargins`, `freeCashflow`, `earningsGrowth`,
  `payoutRatio`, `capitalExpenditures`, plus per-share `eps` / `bvps`.
- Statements carry no market prices, so valuation is reconstructed at use
  time: `fundamental_snapshots.apply_price_valuation` computes a point-in-time
  `trailingPE` / `priceToBook` from the signal-bar close times the FY EPS /
  BVPS. `validate_buy_logic.py` calls it for every historical signal bar.
- `marketCap`, `forwardPE`, `heldPercentInsiders` and sector remain
  current-only (not reconstructible from annual statements); those rows simply
  stay absent until daily snapshots accumulate for that window.

For a true five-year fundamental backtest, use a provider that supplies
point-in-time historical fundamentals and valuation ratios. Import each value
with both `period_end` and `available_date`; the backtest must use
`available_date` so it never uses information before publication.
