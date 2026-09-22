"""
run.py — Quick launcher for all modules
Usage:
  python run.py screen       — run screener only
  python run.py analyze      — run AI analysis on screener output
  python run.py portfolio    — show portfolio
  python run.py holdsell     — run hold/sell analysis
  python run.py full         — screen + analyze + alerts (full morning run)
  python run.py pricefiles   — refresh raw_data/prices CSVs from provider
  python run.py snapshot     — capture point-in-time fundamental snapshots
  python run.py dashboard    — launch Streamlit dashboard
  python run.py scheduler    — start the daily auto-scheduler
  python run.py bible        — close the loop: journal import+resolve+report,
                               market context snapshot, portfolio discipline,
                               and the living playbook
  python run.py journal      — decision journal CLI passthrough
  python run.py market       — market context snapshot only
  python run.py discipline   — portfolio discipline report only
  python run.py playbook     — regenerate the Rules of Engagement document
"""

import sys
import os
import subprocess

import paths


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
        if not os.path.exists(paths.path("screener_results.json")):
            print("Run 'python run.py screen' first.")
            return
        try:
            with open(paths.path("screener_results.json")) as f:
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

    elif cmd == "pricefiles":
        from update_price_files import update_all
        res = update_all()
        print(f"Price files: updated={res['updated']} backfilled={res['backfilled']} "
              f"merged={res['merged']} unchanged={res['unchanged']} "
              f"failed={res['failed']}")

    elif cmd == "snapshot":
        from screener import NSE_STOCKS
        from fundamental_snapshots import capture_snapshots, snapshot_coverage
        res = capture_snapshots(NSE_STOCKS)
        coverage = snapshot_coverage(NSE_STOCKS)
        print(f"Fundamental snapshots: requested={res['requested']} "
              f"captured={res['captured']} failed={res['failed']}")
        print(f"Coverage: {coverage['symbols_with_snapshots']}/"
              f"{coverage['symbols_requested']} ({coverage['coverage_pct']}%) | "
              f"oldest={coverage['oldest_snapshot']} "
              f"newest={coverage['newest_snapshot']} "
              f"stale={len(coverage['stale_symbols'])}")
        if coverage["missing_symbols"]:
            print("Missing:", ", ".join(coverage["missing_symbols"]))

    elif cmd == "test_telegram":
        from alerts import send_telegram
        ok = send_telegram("✅ AI Stock Analyst is connected and working!")
        print("Telegram:", "✅ OK" if ok else "❌ Failed")

    elif cmd in ("journal", "market", "discipline", "playbook", "bible"):
        _run_bible_command(cmd)

    else:
        print(__doc__)


def _run_bible_command(cmd: str):
    """Bible pipeline: journal -> market -> discipline -> playbook."""
    if cmd == "journal":
        _bible_journal_default()
    elif cmd == "market":
        from market_breadth import build_market_snapshot, _print_snapshot
        _print_snapshot(build_market_snapshot())
        print("\nSaved: market_snapshot.json")
    elif cmd == "discipline":
        from discipline import build_discipline_report, _print_report
        _print_report(build_discipline_report())
        print("\nSaved: portfolio_discipline_report.json")
    elif cmd == "playbook":
        from playbook import write_playbook
        write_playbook()
        print("Saved: docs/playbook.md + docs/playbook.json")
    elif cmd == "bible":
        print("[1/4] Closing the loop: decision journal...")
        _bible_journal_default()
        print("\n[2/4] Market context...")
        from market_breadth import build_market_snapshot, _print_snapshot
        _print_snapshot(build_market_snapshot())
        print("\n[3/4] Portfolio discipline...")
        from discipline import build_discipline_report, _print_report
        _print_report(build_discipline_report())
        print("\n[4/4] Living playbook...")
        from playbook import write_playbook
        write_playbook()
        print("\nBible refresh complete.")


def _bible_journal_default():
    """Import today's decisions into the journal, resolve what we can
    (including hypothetical plans for plan-less candidates), and write the
    win-rate report consumed by the dashboard."""
    import json
    from journal import DecisionJournal

    journal = DecisionJournal()
    try:
        for rel in ("screener_results.json", "ai_analysis.json"):
            path = paths.path(rel)
            if not os.path.exists(path):
                continue
            res = journal.import_from_file(
                path, source="ai" if "ai_" in rel else "screener")
            print(f"Journal <- {rel}: inserted={res['inserted']} "
                  f"duplicates={res['duplicates']}")
        stats = journal.resolve_open(hypothetical=True)
        resolved = sum(v for k, v in stats.items()
                       if k not in ("OPEN", "NO_PLAN"))
        print(f"Resolved {resolved} decision(s): {stats}")
        report = journal.report(by="style")
        with open(paths.path("journal_report.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, default=str)
        print("Saved: journal_report.json")
    finally:
        journal.close()

if __name__ == "__main__":
    main()