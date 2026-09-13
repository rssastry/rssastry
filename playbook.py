"""
playbook.py - Living "Rules of Engagement" generator.

The system's brain is scattered across config.py constants, screener gate
functions and case-study comments. This module renders it into ONE dated,
reviewable, versioned document (docs/playbook.md) plus a structured
playbook.json for the dashboard - the "scripture" of the bible.

Every constant shown is read LIVE from config at generation time, so the
playbook can never drift from the code. Case-study lessons are recorded as
institutional memory (they explain WHY a threshold sits where it does).

CLI:
    python playbook.py [--out docs/playbook.md] [--json docs/playbook.json]
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

import config
import strategies


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _kv_table(items: list) -> str:
    lines = ["| Setting | Value |", "|---|---|"]
    for key, value in items:
        lines.append(f"| `{key}` | `{value}` |")
    return "\n".join(lines) + "\n"


def build_playbook() -> dict:
    hold_bars = ", ".join(f"{k}: {v} bars" for k, v in
                          config.STYLE_MAX_HOLD_BARS.items())
    atr_mults = ", ".join(f"{k}: {v}" for k, v in config.ATR_MULT.items())
    stop_caps = ", ".join(f"{k}: {v}%" for k, v in
                          config.MAX_STOP_DISTANCE_PCT_BY_STYLE.items())
    sectors = ", ".join(sorted(str(x) for x in strategies.SECTOR_THRESHOLDS))

    sections = {
        "universe_and_styles": {
            "title": "Universe, styles and holding periods",
            "body": (
                "- Universe: NSE liquid universe (NIFTY 50 + Next 50 + liquid "
                "mid-caps), stored in `screener.NSE_STOCKS`.\n"
                "- Styles: `intraday` (1-3 bars), `swing` (2-5 sessions, "
                "max-hold below), `positional` (1-4 weeks).\n"
                f"- Max holding period in completed bars: **{hold_bars}**.\n"
                "- Intraday BUY is disabled by policy: daily bars cannot "
                "honestly support an intraday recommendation "
                f"(`ALLOW_DAILY_BAR_INTRADAY_BUY = "
                f"{config.ALLOW_DAILY_BAR_INTRADAY_BUY}`).\n"
                f"- ATR multiplier for stops by style: **{atr_mults}**.\n"
                f"- Target = entry + ATR multiple by style: "
                f"**{_fmt_mults(config.TARGET_ATR_MULT)}**.\n"
            ),
        },
        "entry_gate": {
            "title": "The BUY gate (entry rules of engagement)",
            "body": (
                "A candidate must clear ALL of the following to be offered as "
                "BUY. Any failure demotes it to WATCHLIST with the reason "
                "recorded ('eligibility_failures').\n\n"
                "1. **Technical floor** - the technical score must clear the "
                "style floor (trend/momentum evidence is non-negotiable):\n"
                f"{_kv_table(list(config.MIN_TECHNICAL_SCORE_FOR_BUY.items()))}"
                "2. **Ensemble floor** - the blended score must clear "
                f"`BUY_MIN_ENSEMBLE = {config.BUY_MIN_ENSEMBLE}`.\n"
                "3. **Fundamental evidence** - at least "
                f"`MIN_FUNDAMENTAL_DATA_POINTS_FOR_BUY = "
                f"{config.MIN_FUNDAMENTAL_DATA_POINTS_FOR_BUY}` fundamental "
                "data points AND a quality score "
                f"`>= {config.MIN_FUNDAMENTAL_QUALITY_FOR_BUY}` are required; "
                "missing fundamentals are treated as negative evidence, never "
                "neutral.\n"
                "4. **Leverage & valuation caps** - debt/equity "
                f"`<= {config.MAX_FUNDAMENTAL_DEBT_TO_EQUITY}` and forward/"
                "trailing P/E "
                f"`<= {config.MAX_FUNDAMENTAL_PE}`, both adjusted by "
                f"sector-aware thresholds ({sectors}).\n"
                "5. **Market regime** - NIFTY must be at/above its EMA50 "
                "(`MIN_MARKET_ABOVE_EMA_PCT`); an UNKNOWN regime FAILS CLOSED "
                f"(`MARKET_REGIME_FAIL_CLOSED = "
                f"{config.MARKET_REGIME_FAIL_CLOSED}`): no market tape, no "
                "fresh BUY.\n"
                "6. **Volume confirmation** - the signal bar must show real "
                "participation, with style-specific margins, plus ADX "
                f"`>= {config.ADX_MIN_FOR_BUY}` trend strength (`ADX 25` "
                "exception allowed only for positional without fresh "
                "crossover).\n"
                "7. **Breakdown / dead-cat-bounce guard** - a recent "
                "high-volume crash day ("
                f"`<= {config.CRASH_DAY_PCT}%` on "
                f"`>= {config.CRASH_DAY_VOL_MULT}x` 20d-median volume) keeps "
                "the setup WATCHLIST until the price RECLAIMS the broken "
                "swing high "
                f"(resolution lookback {config.BREAKDOWN_RESOLUTION_LOOKBACK} "
                "bars), AND a fresh bullish trigger "
                f"(`FRESH_TRIGGER_BARS = {config.FRESH_TRIGGER_BARS}`) "
                "confirms the bounce.\n"
                "8. **Reversal guard** - a recent high-volume distribution "
                "candle ("
                f"`<= {config.REVERSAL_DAY_PCT}%` on "
                f"`>= {config.REVERSAL_DAY_VOL_MULT}x` volume within "
                f"{config.REVERSAL_LOOKBACK_BARS} bars) blocks BUY unless "
                "reclaimed.\n"
                f"9. **Earnings blackout** - no BUY within "
                f"`EARNINGS_BLACKOUT_DAYS = {config.EARNINGS_BLACKOUT_DAYS}` "
                "days of an earnings event.\n"
                "10. **AI veto** - the LLM second opinion is a real veto: "
                "SELL / HOLD / UNKNOWN, or a BUY with confidence below "
                f"`AI_BUY_MIN_CONFIDENCE = {config.AI_BUY_MIN_CONFIDENCE}`, "
                "downgrades the deterministic BUY to WATCHLIST.\n"
            ),
        },
    }
    return _with_remaining_sections(sections, hold_bars, stop_caps)


def _fmt_mults(values: dict) -> str:
    return ", ".join(f"{k}: {v}" for k, v in values.items())


def _with_remaining_sections(sections: dict, hold_bars: str,
                             stop_caps: str) -> dict:
    sections["risk_limits"] = {
        "title": "Position & portfolio risk limits",
        "body": _kv_table([
            ("RISK_PER_TRADE", config.RISK_PER_TRADE),
            ("FIXED_TXN_FEE", config.FIXED_TXN_FEE),
            ("MAX_ACCOUNT_RISK_PCT", config.MAX_ACCOUNT_RISK_PCT),
            ("MAX_POSITION_PCT", config.MAX_POSITION_PCT),
            ("MAX_SECTOR_PCT", config.MAX_SECTOR_PCT),
            ("MAX_POSITIONS", config.MAX_POSITIONS),
            ("MAX_CORRELATION", config.MAX_CORRELATION),
            ("MIN_RISK_REWARD", config.MIN_RISK_REWARD),
        ]) + (
            "Stop distance is also style-capped so one bad bar or gap "
            f"never exceeds a fixed % of price: **{stop_caps}**.\n"
            "These limits are ENFORCED at portfolio.add time by "
            "`portfolio.check_portfolio_risk` and reviewed continuously by "
            "`discipline.py` (aging, concentration, attribution)."
        ),
    }
    sections["exits"] = {
        "title": "Exit conventions",
        "body": (
            "- Stop-loss: entry minus style ATR multiple, capped by the "
            "style max-stop distance.\n"
            "- Targets: T1 / T2 / T3 from the deterministic ATR plan; "
            "entries log the full plan.\n"
            "- Time-based exit: a position open beyond its style max-hold ("
            f"{hold_bars}) has run out of thesis; treat it as OVERDUE in "
            "`discipline.py` and as EXPIRED in `journal.py` resolution.\n"
            "- The journal resolves each decision forward (stop-first "
            "intrabar, staged targets, max-hold expiry) on the frozen "
            "local CSVs - no look-ahead, no network."
        ),
    }
    sections["lessons"] = {
        "title": "Institutional memory (why thresholds sit where they do)",
        "body": (
            "- **HINDCOPPER 2026-08** - BUY offered at ~560 with a ~10.5% "
            "stop; a -7.2% high-volume crash blew straight through it. "
            "Hardened: stop-distance caps per style, low-conviction/"
            "wide-risk names excluded, unresolved breakdown blocks BUY "
            "until the broken swing high is reclaimed.\n"
            "- **SUNPHARMA 2026-09** - BUY offered after a +0.14% bounce "
            "on 0.8x volume under an unreclaimed swing high printed by a "
            "-2.8% high-volume reversal. Hardened: volume confirmation "
            "margin (no boundary hits), reversal-reclaim guard blocks "
            "BUY, regime UNKNOWN fails closed.\n"
            "- **Execution gap** - closed-trade attribution vs NIFTY "
            "(`discipline.py`) exists because backtests cannot capture "
            "the cost of bad fills; the ledger is the ground truth."
        ),
    }
    sections["validation_journal"] = {
        "title": "Validation & journaling methodology",
        "body": (
            "- Reproducibility: every report runs from frozen "
            "`raw_data/prices/*.csv` (see README); network is opt-in.\n"
            "- Anti-lookahead: fundamental snapshots keyed by capture "
            "date; backfilled annuals carry `as_of` = FY-end + 120-day "
            "filing buffer.\n"
            "- The decision journal (`journal.py`) closes the loop on "
            "every logged decision; `--hypothetical` lets WATCHLISTs be "
            "evaluated too (missed gems vs dodged bullets).\n"
            "- Honesty rules: OPEN stays OPEN until forward bars exist; "
            "EXPIRED is a non-win; alpha is measured against NIFTY for "
            "the same window."
        ),
    }
    return {
        "generated_at": _utc_now(),
        "config_file": "config.py",
        "max_hold_bars": config.STYLE_MAX_HOLD_BARS,
        "atr_mults": config.ATR_MULT,
        "sections": sections,
    }


def render_markdown(playbook: dict) -> str:
    lines = [
        "# StockAnalysis - Rules of Engagement (the Playbook)",
        "",
        f"_Auto-generated from `config.py` at "
        f"{playbook['generated_at']}. Never edit by hand - edit the code, "
        f"regenerate._",
        "",
        "> This is the app's contract with you: what it believes, why, and "
        "> how it measures whether it is right. Review it whenever you are "
        "> about to override a recommendation.",
        "",
    ]
    for key, section in playbook["sections"].items():
        lines.append(f"## {key}: {section['title']}")
        lines.append("")
        lines.append(section["body"].rstrip())
        lines.append("")
    return "\n".join(lines)


def write_playbook(md_path: str = os.path.join("docs", "playbook.md"),
                   json_path: str = os.path.join("docs", "playbook.json")) -> dict:
    playbook = build_playbook()
    os.makedirs(os.path.dirname(md_path) or ".", exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(render_markdown(playbook))
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(playbook, handle, indent=2, default=str)
    return playbook


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join("docs", "playbook.md"))
    ap.add_argument("--json", default=os.path.join("docs", "playbook.json"))
    args = ap.parse_args()
    playbook = write_playbook(args.out, args.json)
    print(f"Playbook written: {args.out}")
    print(f"Structured data : {args.json}")
    print(f"Sections        : {', '.join(playbook['sections'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())