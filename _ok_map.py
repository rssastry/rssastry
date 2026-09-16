lines = open("dashboard.py", encoding="utf-8").read().split("\r\n")

loop = [i for i, l in enumerate(lines) if "for i, p in enumerate(picks, 1):" in l]
print("loop line (0-based):", loop, "| text:", lines[loop[0]].strip())

start = loop[0]
markers = []
for i in range(start + 1, len(lines)):
    s = lines[i].strip()
    if not s:
        continue
    indent = len(lines[i]) - len(lines[i].lstrip(" "))
    if lines[i].startswith("# ") or lines[i].startswith("#\u2500"):
        markers.append((i, "comment", lines[i][:50]))
    elif indent <= 12 and (lines[i].startswith("elif ") or lines[i].startswith("if ") or lines[i].startswith("# PAGE")):
        markers.append((i, "dedent", lines[i][:60]))
        break
print("first significant dedent/marker after loop:", markers[-1])

# expander open line indent
exp = [i for i, l in enumerate(lines) if l.strip().startswith("with st.expander(") and i > start]
print("expander opens after loop:", exp[:3], [(i, lines[i][:40]) for i in exp[:3]])