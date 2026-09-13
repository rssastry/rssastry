# StockAnalysis - Rules of Engagement (the Playbook)

_Auto-generated from `config.py` at 2026-09-12T12:34:27+00:00. Never edit by hand - edit the code, regenerate._

> This is the app's contract with you: what it believes, why, and > how it measures whether it is right. Review it whenever you are > about to override a recommendation.

## universe_and_styles: Universe, styles and holding periods

- Universe: NSE liquid universe (NIFTY 50 + Next 50 + liquid mid-caps), stored in `screener.NSE_STOCKS`.
- Styles: `intraday` (1-3 bars), `swing` (2-5 sessions, max-hold below), `positional` (1-4 weeks).
- Max holding period in completed bars: **intraday: 3 bars, swing: 15 bars, positional: 60 bars**.
- Intraday BUY is disabled by policy: daily bars cannot honestly support an intraday recommendation (`ALLOW_DAILY_BAR_INTRADAY_BUY = False`).
- ATR multiplier for stops by style: **intraday: 1.5, short_term: 1.5, swing: 2.5, positional: 3.0**.
- Target = entry + ATR multiple by style: **intraday: 3.0, short_term: 3.0, swing: 5.0, positional: 6.0**.

## entry_gate: The BUY gate (entry rules of engagement)

A candidate must clear ALL of the following to be offered as BUY. Any failure demotes it to WATCHLIST with the reason recorded ('eligibility_failures').

1. **Technical floor** - the technical score must clear the style floor (trend/momentum evidence is non-negotiable):
| Setting | Value |
|---|---|
| `intraday` | `70` |
| `short_term` | `70` |
| `swing` | `65` |
| `positional` | `70` |
2. **Ensemble floor** - the blended score must clear `BUY_MIN_ENSEMBLE = 50`.
3. **Fundamental evidence** - at least `MIN_FUNDAMENTAL_DATA_POINTS_FOR_BUY = 4` fundamental data points AND a quality score `>= 35` are required; missing fundamentals are treated as negative evidence, never neutral.
4. **Leverage & valuation caps** - debt/equity `<= 2.5` and forward/trailing P/E `<= 60`, both adjusted by sector-aware thresholds (Basic Materials, Communication Services, Consumer Cyclical, Consumer Defensive, Energy, Financial Services, Healthcare, Industrials, Technology, Utilities).
5. **Market regime** - NIFTY must be at/above its EMA50 (`MIN_MARKET_ABOVE_EMA_PCT`); an UNKNOWN regime FAILS CLOSED (`MARKET_REGIME_FAIL_CLOSED = True`): no market tape, no fresh BUY.
6. **Volume confirmation** - the signal bar must show real participation, with style-specific margins, plus ADX `>= 20` trend strength (`ADX 25` exception allowed only for positional without fresh crossover).
7. **Breakdown / dead-cat-bounce guard** - a recent high-volume crash day (`<= -4.0%` on `>= 1.8x` 20d-median volume) keeps the setup WATCHLIST until the price RECLAIMS the broken swing high (resolution lookback 20 bars), AND a fresh bullish trigger (`FRESH_TRIGGER_BARS = 3`) confirms the bounce.
8. **Reversal guard** - a recent high-volume distribution candle (`<= -2.0%` on `>= 1.5x` volume within 5 bars) blocks BUY unless reclaimed.
9. **Earnings blackout** - no BUY within `EARNINGS_BLACKOUT_DAYS = 3` days of an earnings event.
10. **AI veto** - the LLM second opinion is a real veto: SELL / HOLD / UNKNOWN, or a BUY with confidence below `AI_BUY_MIN_CONFIDENCE = 55`, downgrades the deterministic BUY to WATCHLIST.

## risk_limits: Position & portfolio risk limits

| Setting | Value |
|---|---|
| `RISK_PER_TRADE` | `0.01` |
| `FIXED_TXN_FEE` | `20.0` |
| `MAX_ACCOUNT_RISK_PCT` | `0.02` |
| `MAX_POSITION_PCT` | `0.2` |
| `MAX_SECTOR_PCT` | `0.3` |
| `MAX_POSITIONS` | `10` |
| `MAX_CORRELATION` | `0.7` |
| `MIN_RISK_REWARD` | `2.0` |
Stop distance is also style-capped so one bad bar or gap never exceeds a fixed % of price: **intraday: 4.0%, short_term: 4.0%, swing: 5.0%, positional: 6.0%**.
These limits are ENFORCED at portfolio.add time by `portfolio.check_portfolio_risk` and reviewed continuously by `discipline.py` (aging, concentration, attribution).

## exits: Exit conventions

- Stop-loss: entry minus style ATR multiple, capped by the style max-stop distance.
- Targets: T1 / T2 / T3 from the deterministic ATR plan; entries log the full plan.
- Time-based exit: a position open beyond its style max-hold (intraday: 3 bars, swing: 15 bars, positional: 60 bars) has run out of thesis; treat it as OVERDUE in `discipline.py` and as EXPIRED in `journal.py` resolution.
- The journal resolves each decision forward (stop-first intrabar, staged targets, max-hold expiry) on the frozen local CSVs - no look-ahead, no network.

## lessons: Institutional memory (why thresholds sit where they do)

- **HINDCOPPER 2026-08** - BUY offered at ~560 with a ~10.5% stop; a -7.2% high-volume crash blew straight through it. Hardened: stop-distance caps per style, low-conviction/wide-risk names excluded, unresolved breakdown blocks BUY until the broken swing high is reclaimed.
- **SUNPHARMA 2026-09** - BUY offered after a +0.14% bounce on 0.8x volume under an unreclaimed swing high printed by a -2.8% high-volume reversal. Hardened: volume confirmation margin (no boundary hits), reversal-reclaim guard blocks BUY, regime UNKNOWN fails closed.
- **Execution gap** - closed-trade attribution vs NIFTY (`discipline.py`) exists because backtests cannot capture the cost of bad fills; the ledger is the ground truth.

## validation_journal: Validation & journaling methodology

- Reproducibility: every report runs from frozen `raw_data/prices/*.csv` (see README); network is opt-in.
- Anti-lookahead: fundamental snapshots keyed by capture date; backfilled annuals carry `as_of` = FY-end + 120-day filing buffer.
- The decision journal (`journal.py`) closes the loop on every logged decision; `--hypothetical` lets WATCHLISTs be evaluated too (missed gems vs dodged bullets).
- Honesty rules: OPEN stays OPEN until forward bars exist; EXPIRED is a non-win; alpha is measured against NIFTY for the same window.
