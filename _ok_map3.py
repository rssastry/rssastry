raw = open("dashboard.py", encoding="utf-8").read()
print("len chars:", len(raw))
lines = raw.split("\r\n")
print("n lines:", len(lines))
targets = ['Market Overview', 'Top BUY Picks Today', 'c1, c2, c3, c4 = st.columns(4)', 'Style Distribution', 'def risk_badge']
for t in targets:
    hits = [i for i, l in enumerate(lines) if t in l]
    print(repr(t), "->", hits[:3])