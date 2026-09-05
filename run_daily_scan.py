"""
run_daily_scan.py — Runs the screener and auto-analyzes top picks with AIAnalyst.
Outputs `screener_results.json` and `ai_analysis.json`.
"""
from screener import StockScreener
from ai_analyst import AIAnalyst


def main():
    s = StockScreener()
    results = s.screen(styles=["intraday","swing","positional"], top_n=8)
    analyst = AIAnalyst()
    analysis = analyst.analyze_top_picks(results, delay_seconds=6)
    print("Daily scan complete.")


if __name__ == '__main__':
    main()
