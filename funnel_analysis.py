"""funnel_analysis.py — isolate what each BUY-gate stage actually contributes.

Runs (or reuses) the validate_buy_logic harness twice on the SAME 5y window:

  A) technical-only   (--technical-only): the raw technical signal pool
  B) fundamentals-required:               the same pool filtered by the
                                           point-in-time fundamental gate

The technical score floor, regime filter and prices are identical in both legs,
so the ONLY difference is require_fundamentals. The funnel shows, per style:

  technical_candidates  bars that cleared passes_filter + technical floor
  fundamental_blocked   candidates rejected by the PIT fundamental gate
  signals               trades actually entered after all gates
  gate_squeeze_pct      % of technical candidates removed by fundamentals

Use::

    .venv\\Scripts\\python.exe funnel_analysis.py                     # compare existing JSONs
    .venv\\Scripts\\python.exe funnel_analysis.py --run-tech           # (re)run tech leg first
    .venv\\Scripts\\python.exe funnel_analysis.py --styles swing       # one style only
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def load_report(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _by_style(report):
    return report.get("by_style", {})


def style_row(style, tech, funds):
    """One funnel/comparison row from the two report legs."""
    t = _by_style(tech).get(style, {})
    f = _by_style(funds).get(style, {})
    tech_candidates = (f.get("signals", 0)
                       + f.get("suppressed_by_missing_or_weak_fundamentals", 0))
    blocked = f.get("suppressed_by_missing_or_weak_fundamentals", 0)
    squeeze = round(100.0 * blocked / tech_candidates, 1) if tech_candidates else 0.0
    return {
        "style": style,
        "technical_candidates": tech_candidates,
        "fundamental_blocked": blocked,
        "regime_blocked_tech": t.get("suppressed_by_regime", 0),
        "regime_blocked_funds": f.get("suppressed_by_regime", 0),
        "gate_squeeze_pct": squeeze,
        "tech_only": {
            "signals": t.get("signals", 0),
            "trades": t.get("trades", 0),
            "symbols_tested": t.get("symbols_tested", 0),
            "fundamentals_required": t.get("fundamentals_required", False),
        },
        "funds_required": {
            "signals": f.get("signals", 0),
            "trades": f.get("trades", 0),
            "symbols_tested": f.get("symbols_tested", 0),
            "fundamentals_required": f.get("fundamentals_required", True),
        },
        "performance": {
            "tech_win_rate": t.get("win_rate"),
            "fund_win_rate": f.get("win_rate"),
            "tech_avg_ret_pct": t.get("avg_return_pct"),
            "fund_avg_ret_pct": f.get("avg_return_pct"),
            "tech_median_ret_pct": t.get("median_return_pct"),
            "fund_median_ret_pct": f.get("median_return_pct"),
            "tech_profit_factor": t.get("profit_factor"),
            "fund_profit_factor": f.get("profit_factor"),
            "tech_total_return_pct": t.get("total_return_pct"),
            "fund_total_return_pct": f.get("total_return_pct"),
        },
        "sample": {
            "tech_confident": t.get("confidence") == "sufficient_sample",
            "fund_confident": f.get("confidence") == "sufficient_sample",
        },
    }
def run_leg(path, styles, tech_only):
    """Invoke the validation harness; returns (json_path, log_path)."""
    args = [sys.executable, "-u", "validate_buy_logic.py",
            "--symbols", "140", "--period", "5y",
            "--styles", ",".join(styles),
            "--json", path]
    if tech_only:
        args.append("--technical-only")
    log_path = "tech_only.log" if tech_only else "funds_only.log"
    print(f"  running leg: {os.path.basename(path)} "
          f"({'technical-only' if tech_only else 'fundamentals-required'}) ...")
    with open(log_path, "w", encoding="utf-8") as handle:
        proc = subprocess.run(args, cwd=HERE, stdout=handle, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        print(f"  ! leg exited with code {proc.returncode}; see {log_path}")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tech-json", default="validation_tech_only.json")
    ap.add_argument("--funds-json",
                    default="validation_pit_full.json,validation_pit_positional.json",
                    help="comma-separated fundamentals-required report JSONs")
    ap.add_argument("--styles", default="intraday,swing,positional")
    ap.add_argument("--run-tech", action="store_true",
                    help="(re)run the technical-only leg before comparing")
    ap.add_argument("--out", default="funnel_report.json")
    args = ap.parse_args()

    styles = [s.strip() for s in args.styles.split(",") if s.strip()]

    if args.run_tech or not os.path.exists(args.tech_json):
        run_leg(args.tech_json, styles, tech_only=True)
    if not os.path.exists(args.funds_json):
        run_leg(args.funds_json, styles, tech_only=False)

    if not os.path.exists(args.tech_json) or not os.path.exists(args.funds_json):
        print("Missing one of the report files:")
        print(f"  {args.tech_json}  exists: {os.path.exists(args.tech_json)}")
        print(f"  {args.funds_json} exists: {os.path.exists(args.funds_json)}")
        return 2

    tech = load_report(args.tech_json)

    funds_files = [p.strip() for p in args.funds_json.split(",") if p.strip()]
    funds = {}
    for index, path in enumerate(funds_files):
        loaded = load_report(path)
        if index == 0:
            funds = loaded
        else:
            funds.setdefault("by_style", {}).update(loaded.get("by_style", {}))
    if not funds.get("by_style"):
        print(f"No by_style data found in: {', '.join(funds_files)}")
        return 2

    rows = [style_row(style, tech, funds) for style in styles]
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "universe_size": funds.get("universe_size", tech.get("universe_size")),
        "history_period": funds.get("history_period", tech.get("history_period")),
        "regime_filter": funds.get("regime_filter", tech.get("regime_filter")),
        "tech_quality_proxy": tech.get("quality_proxy"),
        "funds_quality_proxy": funds.get("quality_proxy"),
        "tech_file": args.tech_json,
        "funds_file": args.funds_json,
        "snapshot_coverage": funds.get("fundamental_snapshot_coverage"),
        "nifty_benchmark": funds.get("nifty_benchmark"),
        "by_style": rows,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    print(f"\nFunnel report saved: {args.out}\n")

    hdr = (f"{'style':<10}{'tech_cand':>10}{'fund_blocked':>13}{'squeeze%':>9}"
           f"{'tech_sig':>9}{'fund_sig':>9}"
           f"{'tech_win':>9}{'fund_win':>9}"
           f"{'tech_med%':>10}{'fund_med%':>10}")
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        p = row["performance"]
        fmt = lambda v: f"{v:.3f}" if isinstance(v, (int, float)) else "-"
        print(f"{row['style']:<10}"
              f"{row['technical_candidates']:>10}"
              f"{row['fundamental_blocked']:>13}"
              f"{row['gate_squeeze_pct']:>9}"
              f"{fmt(p['tech_win_rate']):>9}"
              f"{fmt(p['fund_win_rate']):>9}"
              f"{fmt(p['tech_median_ret_pct']):>10}"
              f"{fmt(p['fund_median_ret_pct']):>10}")
    print("-" * len(hdr))
    print(" win = win_rate (fraction), med = median return %, "
          "cand = technical candidates reaching the fundamental stage")
    return 0


if __name__ == "__main__":
    sys.exit(main())