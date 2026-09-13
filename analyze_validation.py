"""Summarize a validation JSON report (trade-level view for review)."""
import json
import sys
from collections import Counter


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "validation_pit_positional.json"
    report = json.load(open(path, encoding="utf-8"))
    print(f"report: {path}")
    print(f"  generated: {report.get('generated_at')}")
    print(f"  universe: {report.get('universe_size')} | period: "
          f"{report.get('history_period')} | funds_required: "
          f"{report.get('fundamentals_required')}")
    cov = report.get("fundamental_snapshot_coverage", {})
    print(f"  snapshot coverage: {cov.get('coverage_pct')}% "
          f"({cov.get('symbols_with_snapshots')}/{cov.get('symbols_requested')})")
    print(f"  backfill since: {cov.get('backfill_period_end_min')} -> "
          f"{cov.get('backfill_period_end_max')}")
    print()
    for style, st in report.get("by_style", {}).items():
        print(f"== {style.upper()} ==")
        print(f"  signals={st['signals']} trades={st['trades']} "
              f"regime_suppressed={st['suppressed_by_regime']} "
              f"fund_suppressed={st['suppressed_by_missing_or_weak_fundamentals']}")
        print(f"  win_rate={st.get('win_rate')} "
              f"avg={st.get('avg_return_pct')}% "
              f"median={st.get('median_return_pct')}% "
              f"best={st.get('best_pct')}% worst={st.get('worst_pct')}% "
              f"hold={st.get('avg_hold_bars')}b pf={st.get('profit_factor')}")
        print(f"  total={st.get('total_return_pct')}% "
              f"cagr={st.get('cagr')} maxDD={st.get('max_drawdown_pct')}%")
        syms = Counter()
        for trade in st.get("trade_detail", []) or []:
            print(f"    {trade['symbol']:>12} in {trade['entry_date']} "
                  f"out {trade['exit_date']} {trade['ret']*100:+.2f}% "
                  f"{trade['bars']}b")
            syms[trade["symbol"]] += 1
        if syms:
            print(f"  distinct symbols: {len(syms)} "
                  f"-> {', '.join(f'{s} x{c}' for s, c in syms.most_common())}")
        print()
    print("== NIFTY BENCHMARK ==")
    bench = report.get("nifty_benchmark", {})
    print(f"  {bench}")


if __name__ == "__main__":
    main()