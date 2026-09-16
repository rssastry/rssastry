import ast
src = open("dashboard.py", encoding="utf-8").read()
ast.parse(src)
print("AST parse OK; chars:", len(src), "CRLF:", "\r\n" in src)

lines = src.split("\r\n")

# show hero region
for i, l in enumerate(lines):
    if "Hero band: market pulse" in l:
        print("\n--- HERO REGION ---")
        for x in range(i, i + 4):
            print(x, repr(lines[x][:80]))
        break

# show picks grid region
for i, l in enumerate(lines):
    if "for _r in range(0, len(picks), 2):" in l:
        print("\n--- PICKS GRID REGION ---")
        for x in range(i, min(i + 12, len(lines))):
            print(x, repr(lines[x][:80]))
        break