raw = open("dashboard.py", encoding="utf-8", newline="").read()
lines = raw.split("\n")
print("n lines:", len(lines), "| has CRLF:", "\r\n" in raw)
targets = ['Market Overview', 'Top BUY Picks Today', 'c1, c2, c3, c4 = st.columns(4)',
           'Style Distribution', 'def risk_badge', 'for i, p in enumerate(picks, 1):',
           "# PAGE: TODAY'S PICKS", "# PAGE: MY PORTFOLIO", 'elif "My Portfolio"', 'elif "Picks"']
for t in targets:
    hits = [i for i, l in enumerate(lines) if t in l]
    print(repr(t), "->", hits[:4])