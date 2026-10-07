import json

d = json.load(open("screener_results.json", encoding="utf-8"))
print("top-level keys:", list(d.keys()))
r = d.get("results", {})
print("styles:", list(r.keys()))
for style in list(r.keys()):
    lst = r.get(style, [])
    if lst:
        p = lst[0]
        print(f"--- style={style} n={len(lst)}")
        print("  keys:", sorted(p.keys()))
        print("  recommendation:", p.get("recommendation"))
        print("  selection_decision:", p.get("selection_decision"))
        print("  entry_price:", p.get("entry_price"))
        print("  target_prices:", p.get("target_prices"))
        print("  stop_loss:", p.get("stop_loss"))
        print("  current_price:", p.get("current_price"))
        break