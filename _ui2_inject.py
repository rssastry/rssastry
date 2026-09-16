# -*- coding: utf-8 -*-
"""UI upgrade #2 for dashboard.py — Aurora hero band + 2-column pick grid.

1. Adds .hero* styles to the embedded design system.
2. Adds a nifty_sparkline_svg() helper (local data, SVG, graceful fallback).
3. Replaces the Market Overview stat row with a hero panel + NIFTY sparkline.
4. Converts Today's Picks list into a two-column card grid.

Preserves CRLF line endings.
"""
PATH = "dashboard.py"
raw = open(PATH, encoding="utf-8", newline="").read()
lines = raw.split("\n")
assert "\r\n" in raw, "expected CRLF source"

# ── A. Hero styles ────────────────────────────────────────────────
HERO_CSS = """
/* ── Hero band ─────────────────────────────────────────────── */
.hero {
    position: relative; overflow: hidden; border-radius: 18px;
    padding: 22px 26px; margin-bottom: 24px;
    background: linear-gradient(135deg, rgba(34,211,238,.10), rgba(129,140,248,.10) 55%, rgba(13,19,28,.5));
    border: 1px solid var(--border-strong);
}
.hero::before {
    content: ""; position: absolute; inset: 0; pointer-events: none;
    background:
        radial-gradient(620px 200px at 88% -30%, rgba(129,140,248,.18), transparent 60%),
        radial-gradient(520px 190px at 4% 120%, rgba(34,211,238,.12), transparent 55%);
}
.hero-grid {
    position: relative; display: grid; grid-template-columns: 1.35fr 1fr;
    gap: 24px; align-items: center;
}
@media (max-width: 900px) { .hero-grid { grid-template-columns: 1fr; } }
.hero-label {
    font-size: 10.5px; font-weight: 600; letter-spacing: .12em;
    text-transform: uppercase; color: var(--text-3);
}
.hero-value {
    font-size: 30px; font-weight: 800; color: var(--text);
    font-family: var(--mono); margin: 2px 0;
}
.hero-sub { font-size: 12px; color: var(--text-3); }
.hero-chart-head {
    font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase;
    color: var(--text-3); margin-bottom: 8px;
}
.spark-wrap {
    border-radius: 13px; padding: 12px 14px 10px;
    background: rgba(7,11,17,.5); border: 1px solid var(--border);
}
.hero-foot {
    position: relative; display: flex; gap: 22px; flex-wrap: wrap;
    margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border);
    font-size: 12px; color: var(--text-3);
}
.hero-foot .hf { display: inline-flex; align-items: center; gap: 7px; }
.hero-foot .live-dot { flex: 0 0 auto; }
.hero-foot b { color: var(--text-2); font-weight: 600; }
"""

style_idx = raw.index("</style>")
raw = raw[:style_idx] + HERO_CSS + "\n" + raw[style_idx:]
# ── B. nifty_sparkline_svg helper (before get_live_price) ─────────
SPARK_FN = '''
def nifty_sparkline_svg(width=260, height=60):
    """Inline-SVG NIFTY sparkline from local price data (no network)."""
    try:
        from price_store import load_adjusted
        df = load_adjusted("^NSEI", period="6mo", interval="1d")
        if df is None or len(df) < 10:
            raise ValueError("insufficient NIFTY history")
        close = df["Close"].astype(float).dropna().values[-120:]
        n = len(close)
        lo, hi = float(close.min()), float(close.max())
        span = (hi - lo) or 1e-9
        pts = []
        for k, v in enumerate(close):
            x = (k / (n - 1)) * width
            y = height - ((float(v) - lo) / span) * (height - 6) - 3
            pts.append(f"{x:.1f},{y:.1f}")
        d = "M " + " L ".join(pts)
        color = "#2dd4bf" if close[-1] >= close[0] else "#fb7185"
        return (
            f'<div class="spark-wrap">'
            f'<div class="hero-chart-head">NIFTY 50 \\u00b7 {n} sessions</div>'
            f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
            f'style="width:100%;height:72px;display:block">'
            f'<defs><linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{color}" stop-opacity=".30"/>'
            f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
            f'</linearGradient></defs>'
            f'<path d="{d} L {width},{height} L 0,{height} Z" fill="url(#sparkFill)" stroke="none"/>'
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
            f'</svg>'
            f'<div style="display:flex;justify-content:space-between;'
            f'font-family:var(--mono);font-size:11px;color:var(--text-3);padding-top:6px">'
            f'<span>{close[0]:,.0f}</span><span>{close[-1]:,.0f}</span></div>'
            f'</div>'
        )
    except Exception:
        return (
            '<div class="spark-wrap"><div class="hero-chart-head">NIFTY 50</div>'
            '<div style="font-size:12px;color:var(--text-3);padding:18px 2px">'
            'Index sparkline unavailable - refresh price files</div></div>'
        )


'''
anchor = raw.index("def get_live_price")
raw = raw[:anchor] + SPARK_FN + raw[anchor:]

# ── C. Market Overview hero panel (replace the c1..c4 stat row) ───
HERO = '''    # \u2500\u2500 Hero band: market pulse + NIFTY sparkline \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    last_scan = data.get("date", "Never")
    hero_spark = nifty_sparkline_svg()
    _snap = load_json("market_snapshot.json")
    _breadth = _snap.get("breadth") or {}
    _vreg = _snap.get("volatility_regime") or {}
    _b50 = _breadth.get("breadth_pct_above_ema50")
    breadth_txt = f"{float(_b50):.0f}% above EMA50" if _b50 is not None else "n/a"
    vol_txt = _vreg.get("regime", "n/a")

    st.markdown(f"""
    <div class="hero">
      <div class="hero-grid">
        <div>
          <div class="hero-label" style="margin-bottom:12px">Market Pulse</div>
          <div style="display:flex;gap:30px;flex-wrap:wrap">
            <div class="hero-cell">
              <div class="hero-label">BUY Signals</div>
              <div class="hero-value" style="color:#2dd4bf">{total_buys}</div>
              <div class="hero-sub">across all styles</div>
            </div>
            <div class="hero-cell">
              <div class="hero-label">Avg Confidence</div>
              <div class="hero-value" style="color:#60a5fa">{avg_conf}%</div>
              <div class="hero-sub">AI ensemble score</div>
            </div>
            <div class="hero-cell">
              <div class="hero-label">Active Holdings</div>
              <div class="hero-value" style="color:#fbbf24">{len(holdings)}</div>
              <div class="hero-sub">positions in portfolio</div>
            </div>
          </div>
        </div>
        <div>{hero_spark}</div>
      </div>
      <div class="hero-foot">
        <span class="hf"><span class="live-dot"></span>Last scan: <b>{last_scan}</b></span>
        <span class="hf">Volatility: <b>{vol_txt}</b></span>
        <span class="hf">Breadth: <b>{breadth_txt}</b></span>
      </div>
    </div>
    """, unsafe_allow_html=True)

'''
c1_marker = "    c1, c2, c3, c4 = st.columns(4)\r"
c1_idx = raw.index(c1_marker)
br_marker = '    st.markdown("<br>", unsafe_allow_html=True)\r'
br_idx = raw.index(br_marker, c1_idx)
raw = raw[:c1_idx] + HERO + raw[br_idx:]
# ── D. Today's Picks → two-column card grid ───────────────────────
lines = raw.split("\n")  # re-split after prior edits

loop_hits = [i for i, l in enumerate(lines) if "for i, p in enumerate(picks, 1):" in l]
assert len(loop_hits) == 1, f"expected one picks loop, got {len(loop_hits)}"
loop_idx = loop_hits[0]

end_idx = loop_idx + 1
while end_idx < len(lines):
    s = lines[end_idx].strip()
    if s:
        indent = len(lines[end_idx]) - len(lines[end_idx].lstrip(" "))
        if indent <= 12:
            break
    end_idx += 1

body = lines[loop_idx + 1:end_idx]

new_block = [
    "            for _r in range(0, len(picks), 2):",
    "                _cols = st.columns(2)",
    "                for _off, p in enumerate(picks[_r:_r + 2], 1):",
    "                    i = _r + _off",
    "                    with _cols[_off - 1]:",
]
for line in body:
    new_block.append(("        " + line) if line.strip() else line)

lines = lines[:loop_idx] + new_block + lines[end_idx:]
raw = "\n".join(lines)

# ── E. Normalise line endings & write ─────────────────────────────
raw = raw.replace("\r\n", "\n").replace("\n", "\r\n")
with open(PATH, "w", encoding="utf-8", newline="") as fh:
    fh.write(raw)

print("hero css added:", ".hero {" in raw)
print("sparkline fn added:", "def nifty_sparkline_svg" in raw)
print("hero body added:", "Market Pulse" in raw)
print("picks grid added:", "for _r in range(0, len(picks), 2):" in raw)
print("old metric row removed:", "c1, c2, c3, c4 = st.columns(4)\r" in raw or "    c1, c2, c3, c4 = st.columns(4)" in raw.replace("\r\n", "\n"))