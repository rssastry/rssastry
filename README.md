# StockAnalysis
Analyze the stocks

## Deploy to Render (dashboard)

The dashboard is a **Streamlit** app (`dashboard.py`). Render must NOT use its
default `gunicorn app:app` start command — gunicorn is a WSGI server and cannot
serve Streamlit.

**Blueprint (recommended):** after pushing, Render → **New + → Blueprint** →
select this repo. `render.yaml` in the repo root wires the build and start
commands, health check path, and Python version automatically.

**Manual web service:** set these exactly on the service:

- Environment:      `Python 3`
- Build command:    `pip install -r requirements.txt`
- Start command:    `streamlit run dashboard.py --server.address 0.0.0.0 --server.port $PORT`
- Health check path: `/`

A `Procfile` with the correct start command is included as a fallback, but an
explicit Start Command in the Render dashboard always wins. After changing the
start command, trigger **Manual Deploy → Deploy latest commit**.

Add API keys (GROQ_API_KEY, TELEGRAM_BOT_TOKEN, KITE_*, …) as Render environment
variables, not a `.env` file.

## Free tier reality check (data resets + missing daily scans)

Two things about the **free** Render plan bite this app:

1. **The filesystem is ephemeral.** A free web service spins down after ~15
   minutes of inactivity and is recycled; every file the app writes at runtime
   — `data_cache/` Parquet + SQLite + fundamental snapshots, refreshed
   `raw_data/prices/*.csv`, `ai_analysis.json`, `screener_results.json`,
   `signals_log.csv` — is wiped on the next restart / redeploy. Only files in
   git survive a fresh deployment.
2. **The daily scheduler never runs.** The web-service start command only
   launches Streamlit (`streamlit run dashboard.py`). The bundled scheduler
   (`python run.py scheduler`) is a separate long-running process that Render
   does not start, so nothing scans automatically — you would have to click
   **▶ Run Morning Scan** in the sidebar yourself every day.

### Recommended fix — GitHub Actions daily scan (free)

`.github/workflows/daily-scan.yml` runs the full post-close scan on GitHub's
free runners every weekday at 15:45 IST and commits the fresh results back to
`main`. Because Render has `autoDeploy: true`, the dashboard redeploys with
the latest `ai_analysis.json` / `screener_results.json` / refreshed price
CSVs automatically — so it stops "starting from fresh" and always shows the
latest scan.

1. Push this repo to GitHub.
2. Add at least **`GROQ_API_KEY`** as a repository secret
   (`Settings → Secrets and variables → Actions`); `GEMINI_API_KEY` /
   `OPENROUTER_API_KEY` are fallbacks, `TELEGRAM_*` are optional alerts.
3. Trigger a first run manually via the **Actions → Daily Market Scan →
   Run workflow** button; after that it runs on the schedule.

Note: scans commit only small text/CSV outputs (price files, JSON reports,
snapshots) so the repo stays manageable. The ai_analysis results reflect the
deterministic gates — a *bearish market regime (NIFTY below EMA50) suppresses
all BUYs by design*, so a zero-BUY report is usually the filter working, not
a deployment failure.

### Paid-plan alternative — persistent disk

For state with zero reliance on git, upgrade to a paid plan, add a Render
**Persistent Disk** mounted at e.g. `/var/data`, and set the **`SA_DATA_DIR`**
environment variable to that path. Every writable path in the app (Parquet
cache, SQLite stores, price CSVs, snapshots, JSON reports) honors it via
`paths.py`; reads automatically fall back to the git-tracked files until the
disk has been seeded. Seed the disk once by copying the current
`data_cache/` and `raw_data/prices/` from a working copy into it.

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
