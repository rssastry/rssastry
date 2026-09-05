# config.py — shared configuration constants

# Count completed trading bars, not calendar days (Friday -> Monday is one bar).
CROSSOVER_RECENCY_BARS = 2
RISK_PER_TRADE = 0.01  # fraction of portfolio risked per trade
FIXED_TXN_FEE = 20.0   # INR per trade fixed fee
MAX_VOLUME_RATIO = 10.0 # cap computed volume ratio
MIN_DAILY_HISTORY = 260  # supports reliable EMA50 and genuine 52-week context
MIN_RISK_REWARD = 2.0
# A cache is only a performance aid; it must not bridge different data requests.
CACHE_TTL_HOURS = 6
CACHE_DIR = 'data_cache'
# Keep enough daily history for multi-year walk-forward validation. The cache
# key includes the period, so this does not mix 5y data with shorter requests.
HISTORICAL_DATA_PERIOD = "5y"

# ── Risk & validation ─────────────────────────────────────────────
MIN_QUANTITY = 1
MIN_STOP_LOSS_PCT = 0.5      # stop must be at least 0.5% below entry
MAX_STOP_LOSS_PCT = 15.0     # stop must be at most 15% below entry
MIN_TARGET_PCT = 2.0         # target must be at least 2% above entry
MAX_TARGET_PCT = 100.0       # target must be at most 100% above entry
MAX_ACCOUNT_RISK_PCT = 0.02  # max 2% of account risked per position
MAX_POSITION_PCT = 0.20      # max 20% of account in a single position
MAX_SECTOR_PCT = 0.30        # max 30% of account in a single sector
MAX_POSITIONS = 10           # maximum simultaneous open positions
MAX_CORRELATION = 0.70       # max pairwise correlation for new position vs existing

# ── Strategy-specific parameters ──────────────────────────────────
# ATR multipliers for stop-loss by style
# "intraday" is kept as an alias for "short_term" (1-3 day swing using daily bars)
ATR_MULT = {
    "intraday": 1.5,
    "short_term": 1.5,
    "swing": 2.5,
    "positional": 3.0,
}

# Target as multiple of ATR distance from entry (deterministic)
TARGET_ATR_MULT = {
    "intraday": 3.0,
    "short_term": 3.0,
    "swing": 5.0,
    "positional": 6.0,
}

# ── Market regime / risk filters ──────────────────────────────────
MARKET_REGIME_LOOKBACK = 20
MARKET_REGIME_EMA = 50
MIN_MARKET_ABOVE_EMA_PCT = 0.0  # NIFTY must be at/above its EMA50 to allow new buys

# ── Breakdown / dead-cat-bounce guard ─────────────────────────────
# A high-volume selloff day followed by an up-day bounce is the classic
# "dead-cat bounce" / bull-trap structure. Unless that bounce reclaims the
# swing high that was broken AND carries a fresh bullish trigger, the setup
# must be treated as WATCHLIST, never a BUY. HINDCOPPER on 2026-08-26 is the
# canonical case: -7.2% crash on 4.2x volume, then +4.4% bounce that stalled
# ₹30 below the broken 586.75 swing high (bounce-fade).
BREAKDOWN_LOOKBACK_BARS = 2      # completed bars (excl. today) scanned for a crash day
CRASH_DAY_PCT = -4.0             # daily % change <= this marks a breakdown session
CRASH_DAY_VOL_MULT = 1.8         # crash session volume >= this multiple of 20d median
FRESH_TRIGGER_BARS = 3           # fresh MACD/EMA bullish cross must be within this many bars
BOUNCE_HIST_MIN_SAMPLES = 12     # min samples for the empirical bounce-fade statistics

# ── Strong-recommendation gates (added after HINDCOPPER 2026-08 loss) ──
# The HINDCOPPER case: BUY offered 2026-08-21 @ 560 with a ~10.5% stop distance,
# then a -7.2% high-volume crash (2026-08-24) blew straight through it. Hardened
# rules below keep low-conviction / wide-risk / unreclaimed-breakdown names out
# of the BUY list entirely.

# ── SUNPHARMA 2026-09-03 review: volume-boundary + reversal gaps ──────
# SUNPHARMA was offered as a positional BUY on 2026-09-02 after a +0.14%
# bounce on 0.8x volume, buying directly under the 1984.8 swing-high that a
# -2.8% high-volume reversal (2.3x) had just printed on 2026-09-01. The stock
# faded -0.8% the very next session. The guards below close those gaps:
#   1) volume confirmation must be a real surplus, not a boundary hit;
#   2) a recent high-volume reversal that has not been reclaimed blocks BUY.

# Minimum volume ratio to accept a BUY. Positional was a lenient 0.8x which let
# a no-volume bounce through; every style now needs at least average volume.
# (Actual thresholds live in SCREEN_CRITERIA in screener.py; this buffer
# requires the ratio to exceed the minimum by a real margin, so a recorded
# 1.0x (rounded) can not squeak past a 1.0x minimum.)
VOLUME_CONFIRMATION_MARGIN = 1.10

# A recent high-volume down-reversal (distribution) candle near the signal bar
# warns that the "positive day" is likely a low-volume bounce into overhead
# supply. Unless the latest close reclaims the broken swing high, the setup is
# WATCHLIST not BUY.
REVERSAL_LOOKBACK_BARS = 5      # completed bars scanned BEFORE the signal bar
REVERSAL_DAY_PCT = -2.0         # daily close-to-close move <= this = reversal session
REVERSAL_DAY_VOL_MULT = 1.5     # reversal session volume >= this multiple of 20d median

# Market-regime filter fail-closed behavior. When ^NSEI data is unavailable the
# regime is "unknown". If FAIL_CLOSED is True, an unknown regime suppresses BUY
# (downgrade to WATCHLIST) instead of silently passing — the system cannot
# confirm a supportive tape, so it must not issue fresh BUYs.
MARKET_REGIME_FAIL_CLOSED = True

# A candidate below this ensemble score never reaches the BUY gate at all
# (was a lenient 35). Marginal picks do not consume AI budget.
BUY_MIN_ENSEMBLE = 50

# AI is a real second opinion (veto), not a label: if the AI read is SELL/HOLD,
# UNKNOWN, or a BUY with confidence below this floor, the deterministic BUY is
# downgraded to WATCHLIST with the reason recorded.
AI_BUY_MIN_CONFIDENCE = 55

# Maximum distance (in % of price) from entry to the ATR stop. One bad day or
# gap must never exceed this. Prevents the ~10% swing stops that turned a
# single crash day into an oversized loss. Style copy of ATR_MULT.
# Tightened after SUNPHARMA 2026-09: the previous 8% positional cap still
# allowed a 5.6% stop (3x ATR) on a 1.9%-ATR stock that immediately faded.
MAX_STOP_DISTANCE_PCT_BY_STYLE = {
    "intraday":    4.0,
    "short_term":  4.0,
    "swing":       5.0,
    "positional":  6.0,
}

# A high-volume breakdown stays "unresolved" (blocking BUY) until the price
# RECLAIMS the broken swing high — not just for BREAKDOWN_LOOKBACK_BARS after
# the crash. HINDCOPPER crashed 08-24 and never reclaimed 586.75; the old 2-bar
# lookback let the guard expire while the stock was still below the broken high.
BREAKDOWN_RESOLUTION_LOOKBACK = 20

# ── Earnings event filter ─────────────────────────────────────────
EARNINGS_BLACKOUT_DAYS = 3  # suppress BUY within N days of earnings announcement

# ── Scheduler ─────────────────────────────────────────────────────
# NSE market hours (IST)
NSE_OPEN_HOUR = 9
NSE_OPEN_MINUTE = 15
NSE_CLOSE_HOUR = 15
NSE_CLOSE_MINUTE = 30

# Daily scan should run AFTER market close so daily volume is confirmed
MORNING_SCAN_TIME = "15:45"
MIDDAY_REVIEW_TIME = "12:30"
PRECLOSE_CHECK_TIME = "15:00"
EOD_SUMMARY_TIME = "16:00"

# NSE holiday list (YYYY-MM-DD) — update annually
NSE_HOLIDAYS_2026 = {
    "2026-01-26",  # Republic Day
    "2026-03-03",  # Holi
    "2026-03-25",  # Ramzan Id
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-09-07",  # Ganesh Chaturthi
    "2026-10-02",  # Gandhi Jayanti
    "2026-10-19",  # Dasara
    "2026-11-09",  # Diwali
    "2026-11-10",  # Diwali Balipratipada
    "2026-12-25",  # Christmas
}