import json, os

# what does market_snapshot.json carry?
for fn in ("market_snapshot.json", "ai_analysis.json"):
    if os.path.exists(fn):
        try:
            d = json.load(open(fn, encoding="utf-8"))
            print(fn, "… top keys:", list(d.keys())[:15])
            reg = d.get("regime") or d.get("market_regime")
            print(fn, "regime-like field:", reg)
        except Exception as e:
            print(fn, "ERR", e)

lines = open("dashboard.py", encoding="utf-8").read().split("\r\n")
for i, l in enumerate(lines):
    if "page-title\">Market Overview" in l:
        print("market overview page-title at", i)
    if "Top BUY Picks Today" in l:
        print("section-header Top BUY at", i)
    if "c1, c2, c3, c4 = st.columns(4)" in l:
        print("metrics row at", i)
    if "Style Distribution" in l:
        print("Style Distribution at", i)
    if "def risk_badge" in l:
        print("risk_badge fn at", i)