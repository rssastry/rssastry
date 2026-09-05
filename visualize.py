"""
visualize.py — Generate visualizations and a short PDF report

Reads `portfolio_backtest_report.json` and `backtest_report.json` and
produces PNG plots (equity curve, P/L histogram) plus a combined PDF.
"""
import json
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np


def load_json(path):
    with open(path) as f:
        return json.load(f)


def plot_equity_curve(report):
    eq = report.get('equity_curve', [])
    dates = [e['date'] for e in eq]
    vals = [e['portfolio_value'] for e in eq]
    plt.figure(figsize=(10,4))
    plt.plot(dates, vals, linewidth=1)
    plt.xticks(rotation=45)
    plt.title('Portfolio Equity Curve')
    plt.tight_layout()
    plt.savefig('equity_curve.png')
    plt.close()


def plot_trade_pnl(backtest_report):
    per = backtest_report.get('per_symbol', [])
    all_returns = []
    for p in per:
        for t in p.get('trades', []):
            all_returns.append(t.get('return', 0))
    if not all_returns:
        return
    plt.figure(figsize=(8,4))
    plt.hist(all_returns, bins=40)
    plt.title('Per-trade Return Distribution')
    plt.tight_layout()
    plt.savefig('trade_return_hist.png')
    plt.close()


def make_pdf(report, backtest_report):
    with PdfPages('backtest_report.pdf') as pdf:
        # equity
        eq = report.get('equity_curve', [])
        dates = [e['date'] for e in eq]
        vals = [e['portfolio_value'] for e in eq]
        plt.figure(figsize=(10,4))
        plt.plot(dates, vals)
        plt.title('Portfolio Equity Curve')
        plt.xticks(rotation=45)
        plt.tight_layout()
        pdf.savefig()
        plt.close()

        # histogram
        per = backtest_report.get('per_symbol', [])
        all_returns = []
        for p in per:
            for t in p.get('trades', []):
                all_returns.append(t.get('return', 0))
        plt.figure(figsize=(8,4))
        plt.hist(all_returns, bins=40)
        plt.title('Per-trade Return Distribution')
        plt.tight_layout()
        pdf.savefig()
        plt.close()


if __name__ == '__main__':
    try:
        report = load_json('portfolio_backtest_report.json')
        back = load_json('backtest_report.json')
    except Exception as e:
        print('Missing reports:', e)
        raise
    plot_equity_curve(report)
    plot_trade_pnl(back)
    make_pdf(report, back)
    print('Visualizations saved: equity_curve.png, trade_return_hist.png, backtest_report.pdf')
