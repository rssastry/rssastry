"""
run.py — Quick launcher for all modules
Usage:
  python run.py screen       — run screener only
  python run.py analyze      — run AI analysis on screener output
  python run.py portfolio    — show portfolio
  python run.py holdsell     — run hold/sell analysis
  python run.py full         — screen + analyze + alerts (full morning run)
  python run.py dashboard    — launch Streamlit dashboard
  python run.py scheduler    — start the daily auto-scheduler
"""

import sys
import os
import subprocess


def get_python_executable():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "venv", "Scripts", "python.exe"),
        os.path.join(base_dir, "venv", "bin", "python"),
        os.path.join(base_dir, ".venv", "Scripts", "python.exe"),
        os.path.join(base_dir, ".venv", "bin", "python"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return sys.executable


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "screen":
        from screener import StockScreener
        s = StockScreener()
        s.screen(styles=["intraday","swing","positional"], top_n=10)

    elif cmd == "analyze":
        import json
        if not os.path.exists("screener_results.json"):
            print("Run 'python run.py screen' first.")
            return
        try:
            with open("screener_results.json") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            print("screener_results.json is corrupted. Re-running screener...")
            from screener import StockScreener
            s    = StockScreener()
            data = {"results": s.screen(
                styles=["intraday","swing","positional"], top_n=10
            )}
        from ai_analyst import AIAnalyst
        analyst = AIAnalyst()
        analyst.analyze_top_picks(data["results"], delay_seconds=5)

    elif cmd == "portfolio":
        from portfolio import show_portfolio
        show_portfolio()

    elif cmd == "holdsell":
        from portfolio import run_hold_sell_analysis
        run_hold_sell_analysis()

    elif cmd == "full":
        from screener import StockScreener
        from ai_analyst import AIAnalyst
        from alerts import send_morning_summary
        print("Step 1/3: Screening stocks...")
        s = StockScreener()
        r = s.screen(styles=["intraday","swing","positional"], top_n=10)
        print("\nStep 2/3: AI analysis...")
        a = AIAnalyst()
        analysis = a.analyze_top_picks(r, delay_seconds=3)
        print("\nStep 3/3: Sending alerts...")
        send_morning_summary(analysis)
        print("\nDone! Check Telegram and dashboard.")

    elif cmd == "dashboard":
        python_exe = get_python_executable()
        subprocess.run(
            [python_exe, "-m", "streamlit", "run", "dashboard.py", "--server.headless", "true"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            check=False,
        )

    elif cmd == "scheduler":
        from schedular import run_scheduler
        run_scheduler()

    elif cmd == "test_telegram":
        from alerts import send_telegram
        ok = send_telegram("✅ AI Stock Analyst is connected and working!")
        print("Telegram:", "✅ OK" if ok else "❌ Failed")

    else:
        print(__doc__)

if __name__ == "__main__":
    main()