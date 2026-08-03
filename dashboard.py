"""
dashboard.py — Beautiful AI Stock Analyst Dashboard
Run with: streamlit run dashboard.py
"""

import streamlit as st
import json
import os
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

st.set_page_config(
    page_title="AI Stock Analyst",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
# THEME & CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* Global */
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.main { background: #0d1117; }
[data-testid="stAppViewContainer"] { background: #0d1117; }
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #161b22 0%, #0d1117 100%);
    border-right: 1px solid #21262d;
}

/* Sidebar title */
.sidebar-title {
    font-size: 22px;
    font-weight: 700;
    background: linear-gradient(135deg, #00d4aa, #0099ff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 4px;
}
.sidebar-sub {
    font-size: 11px;
    color: #6e7681;
    margin-bottom: 16px;
}

/* Metric cards */
.metric-card {
    background: linear-gradient(135deg, #161b22, #1c2128);
    border: 1px solid #21262d;
    border-radius: 12px;
    padding: 16px 20px;
    margin: 6px 0;
    transition: all 0.2s ease;
}
.metric-card:hover { border-color: #00d4aa44; transform: translateY(-1px); }
.metric-label { font-size: 11px; color: #6e7681; text-transform: uppercase; letter-spacing: 0.8px; }
.metric-value { font-size: 24px; font-weight: 700; color: #e6edf3; margin: 4px 0; }
.metric-sub   { font-size: 12px; color: #6e7681; }

/* Stock cards */
.stock-card {
    background: linear-gradient(135deg, #161b22, #1c2128);
    border: 1px solid #21262d;
    border-radius: 16px;
    padding: 20px 24px;
    margin: 12px 0;
    transition: all 0.2s ease;
}
.stock-card:hover { border-color: #00d4aa55; box-shadow: 0 4px 24px #00d4aa11; }

/* Badges */
.badge-buy  { background: #00d4aa22; color: #00d4aa; border: 1px solid #00d4aa44;
              padding: 4px 14px; border-radius: 20px; font-size: 13px; font-weight: 600; }
.badge-sell { background: #ff4b4b22; color: #ff4b4b; border: 1px solid #ff4b4b44;
              padding: 4px 14px; border-radius: 20px; font-size: 13px; font-weight: 600; }
.badge-hold { background: #ffa50022; color: #ffa500; border: 1px solid #ffa50044;
              padding: 4px 14px; border-radius: 20px; font-size: 13px; font-weight: 600; }
.badge-high   { background: #ff4b4b22; color: #ff4b4b; border: 1px solid #ff4b4b44;
                padding: 2px 10px; border-radius: 12px; font-size: 11px; }
.badge-medium { background: #ffa50022; color: #ffa500; border: 1px solid #ffa50044;
                padding: 2px 10px; border-radius: 12px; font-size: 11px; }
.badge-low    { background: #00d4aa22; color: #00d4aa; border: 1px solid #00d4aa44;
                padding: 2px 10px; border-radius: 12px; font-size: 11px; }

/* Signal pills */
.signal-pill {
    display: inline-block;
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 11px;
    color: #8b949e;
    margin: 2px 3px;
}

/* Price levels */
.price-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid #21262d;
}
.price-label { font-size: 12px; color: #6e7681; }
.price-val-green { font-size: 16px; font-weight: 600; color: #00d4aa; }
.price-val-red   { font-size: 16px; font-weight: 600; color: #ff4b4b; }
.price-val-blue  { font-size: 16px; font-weight: 600; color: #58a6ff; }
.price-val-white { font-size: 16px; font-weight: 600; color: #e6edf3; }

/* Confidence bar */
.conf-bar-bg {
    background: #21262d;
    border-radius: 6px;
    height: 8px;
    margin: 8px 0;
    overflow: hidden;
}
.conf-bar-fill {
    height: 8px;
    border-radius: 6px;
    background: linear-gradient(90deg, #00d4aa, #0099ff);
}

/* Section headers */
.section-header {
    font-size: 13px;
    font-weight: 600;
    color: #6e7681;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 16px 0 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid #21262d;
}

/* Portfolio table */
.port-row-green { color: #00d4aa; font-weight: 600; }
.port-row-red   { color: #ff4b4b; font-weight: 600; }

/* Page title */
.page-title {
    font-size: 28px;
    font-weight: 700;
    color: #e6edf3;
    margin-bottom: 4px;
}
.page-sub {
    font-size: 13px;
    color: #6e7681;
    margin-bottom: 24px;
}

/* Action buttons */
.stButton > button {
    background: linear-gradient(135deg, #00d4aa22, #0099ff22);
    border: 1px solid #00d4aa44;
    color: #00d4aa;
    border-radius: 8px;
    font-weight: 500;
    transition: all 0.2s;
    width: 100%;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #00d4aa44, #0099ff44);
    border-color: #00d4aa;
    color: #fff;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] { background: #161b22; border-radius: 10px; padding: 4px; }
.stTabs [data-baseweb="tab"] { border-radius: 8px; color: #6e7681; }
.stTabs [aria-selected="true"] { background: #21262d; color: #e6edf3; }

/* Sidebar radio buttons */
[data-testid="stRadio"] label {
    color: #6e7681 !important;
    font-size: 14px;
    padding: 6px 10px;
    border-radius: 8px;
    transition: all 0.2s;
}
[data-testid="stRadio"] label:hover {
    color: #e6edf3 !important;
    background: #21262d;
}
[data-testid="stRadio"] [aria-checked="true"] + div,
[data-testid="stRadio"] [aria-checked="true"] ~ div label,
[data-testid="stRadio"] div[data-testid="stMarkdownContainer"] {
    color: #e6edf3 !important;
}
[data-testid="stRadio"] [data-baseweb="radio"] [aria-checked="true"] ~ div {
    color: #00d4aa !important;
    font-weight: 600;
}
div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child {
    border-color: #00d4aa !important;
    background: #00d4aa !important;
}
            
            
/* Expander */
[data-testid="stExpander"] {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 12px;
    margin: 8px 0;
}

/* Metrics */
[data-testid="stMetric"] {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 10px;
    padding: 12px 16px;
}
[data-testid="stMetricLabel"] { color: #6e7681; font-size: 11px; }
[data-testid="stMetricValue"] { color: #e6edf3; font-size: 20px; font-weight: 700; }

/* Divider */
hr { border-color: #21262d; }

/* Input fields */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stSelectbox"] {
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 8px;
    color: #e6edf3;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #0d1117; }
::-webkit-scrollbar-thumb { background: #21262d; border-radius: 3px; }
  /* Active nav item */
[data-testid="stRadio"] > div > div > label > div:last-child {
    color: #8b949e;
}
[data-testid="stRadio"] > div > div:has(input:checked) > label > div:last-child {
    color: #00d4aa !important;
    font-weight: 600;
}
/* Radio dot color */
input[type="radio"]:checked + div {
    background-color: #00d4aa !important;
    border-color: #00d4aa !important;
}          

</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def load_json(path):
    if not os.path.exists(path) and path == "ai_analysis.json":
        path = "ai_analysis_progress.json"
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            content = f.read().strip()
        if not content:
            return {}
        return json.loads(content)
    except json.JSONDecodeError:
        st.warning(f"{path} is corrupted. Re-run the analysis.")
        return {}


def get_live_price(symbol):
    try:
        sym = symbol if ".NS" in symbol else symbol + ".NS"
        df  = yf.Ticker(sym).history(period="1d", interval="1m")
        return round(df["Close"].iloc[-1], 2) if not df.empty else None
    except Exception:
        return None


def candlestick_chart(symbol, period="30d"):
    try:
        sym = symbol if ".NS" in symbol else symbol + ".NS"
        df  = yf.Ticker(sym).history(period=period, interval="1d")
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"],
            low=df["Low"],  close=df["Close"],
            increasing_line_color="#00d4aa",
            increasing_fillcolor="#00d4aa33",
            decreasing_line_color="#ff4b4b",
            decreasing_fillcolor="#ff4b4b33",
            name=symbol
        ))
        # Add volume bars
        colors = ["#00d4aa44" if c >= o else "#ff4b4b44"
                  for c, o in zip(df["Close"], df["Open"])]
        fig.add_trace(go.Bar(
            x=df.index, y=df["Volume"],
            marker_color=colors,
            name="Volume",
            yaxis="y2",
            opacity=0.5
        ))
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#161b22",
            plot_bgcolor="#161b22",
            height=380,
            margin=dict(l=10, r=10, t=30, b=10),
            xaxis_rangeslider_visible=False,
            showlegend=False,
            xaxis=dict(gridcolor="#21262d", showgrid=True),
            yaxis=dict(gridcolor="#21262d", showgrid=True, side="right"),
            yaxis2=dict(overlaying="y", side="left",
                        showgrid=False, showticklabels=False,
                        range=[0, df["Volume"].max() * 5]),
            font=dict(family="Inter", color="#8b949e"),
        )
        return fig
    except Exception:
        return None


def confidence_bar(score):
    color = "#00d4aa" if score >= 70 else "#ffa500" if score >= 50 else "#ff4b4b"
    return f"""
    <div class="conf-bar-bg">
        <div class="conf-bar-fill" style="width:{score}%; background: linear-gradient(90deg, {color}, {color}99);"></div>
    </div>
    """


def risk_badge(risk):
    cls = {"Low": "badge-low", "Medium": "badge-medium", "High": "badge-high"}.get(risk, "badge-medium")
    return f'<span class="{cls}">{risk} Risk</span>'


def rec_badge(rec):
    cls = {"BUY": "badge-buy", "SELL": "badge-sell", "HOLD": "badge-hold"}.get(rec, "badge-hold")
    return f'<span class="{cls}">{rec}</span>'


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sidebar-title">📈 AI Stock Analyst</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sidebar-sub">NSE/BSE • {datetime.now().strftime("%d %b %Y, %H:%M")}</div>', unsafe_allow_html=True)
    st.divider()

    page = st.radio("", [
        "🏠  Dashboard",
        "📊  Today's Picks",
        "💼  My Portfolio",
        "🔍  Analyze Stock",
        "📋  Hold / Sell Review",
    ], label_visibility="collapsed")

    st.divider()
    st.markdown('<div class="section-header">Quick Actions</div>', unsafe_allow_html=True)

    if st.button("▶  Run Morning Scan"):
        with st.spinner("Scanning + AI analysis (5-10 mins)..."):
            try:
                from screener import StockScreener
                from ai_analyst import AIAnalyst
                s = StockScreener()
                r = s.screen(styles=["intraday","swing","positional"], top_n=10)
                a = AIAnalyst()
                a.analyze_top_picks(r, delay_seconds=12)
                st.success("✅ Scan complete!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    if st.button("🔔  Test Telegram"):
        try:
            from alerts import send_telegram
            ok = send_telegram(
                f"<b>✅ Dashboard Connected</b>\n"
                f"{datetime.now().strftime('%d-%b-%Y %H:%M')}"
            )
            st.success("Sent!" if ok else "Failed — check .env")
        except Exception as e:
            st.error(str(e))

    if st.button("🔄  Refresh"):
        st.rerun()

    st.divider()
    st.markdown('<div class="section-header">System Status</div>', unsafe_allow_html=True)
    files = {
        "screener_results.json": "Screener",
        "ai_analysis.json":      "AI Analysis",
        "portfolio.json":        "Portfolio",
    }
    for f, label in files.items():
        exists = os.path.exists(f)
        dot    = "🟢" if exists else "🔴"
        ts     = ""
        if exists:
            mt = os.path.getmtime(f)
            ts = datetime.fromtimestamp(mt).strftime("%H:%M")
        st.markdown(
            f'<div style="font-size:12px; color:#6e7681; padding:2px 0;">'
            f'{dot} {label} {"• " + ts if ts else "• missing"}</div>',
            unsafe_allow_html=True
        )


# ─────────────────────────────────────────────
# PAGE: DASHBOARD HOME
# ─────────────────────────────────────────────
if "Dashboard" in page:
    st.markdown('<div class="page-title">Market Overview</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-sub">{datetime.now().strftime("%A, %d %B %Y")}</div>', unsafe_allow_html=True)

    # Top stats row
    data     = load_json("ai_analysis.json")
    analysis = data.get("analysis", {})
    portfolio= load_json("portfolio.json")
    holdings = portfolio.get("holdings", [])

    total_buys = sum(
        len([p for p in analysis.get(s,[]) if p.get("recommendation")=="BUY"])
        for s in ["intraday","swing","positional"]
    )
    avg_conf = 0
    all_picks = []
    for s in ["intraday","swing","positional"]:
        all_picks += [p for p in analysis.get(s,[]) if p.get("recommendation")=="BUY"]
    if all_picks:
        avg_conf = round(sum(p.get("confidence_score",0) for p in all_picks) / len(all_picks))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">BUY Signals Today</div>
            <div class="metric-value" style="color:#00d4aa">{total_buys}</div>
            <div class="metric-sub">Across all styles</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Avg Confidence</div>
            <div class="metric-value" style="color:#58a6ff">{avg_conf}%</div>
            <div class="metric-sub">AI score</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Holdings</div>
            <div class="metric-value" style="color:#ffa500">{len(holdings)}</div>
            <div class="metric-sub">Active positions</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        last_scan = data.get("date", "Never")
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Last Scan</div>
            <div class="metric-value" style="font-size:18px; color:#e6edf3">{last_scan}</div>
            <div class="metric-sub">Analysis date</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Top picks summary table
    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.markdown('<div class="section-header">Top BUY Picks Today</div>', unsafe_allow_html=True)
        if all_picks:
            rows = []
            for p in sorted(all_picks, key=lambda x: x.get("confidence_score",0), reverse=True)[:8]:
                ind = p.get("indicators", {})
                ep  = p.get("entry_price", {})
                tp  = p.get("target_prices", {})
                rows.append({
                    "Symbol":    p.get("symbol",""),
                    "Style":     p.get("trading_style","").capitalize(),
                    "CMP":       f"₹{ind.get('current_price','?')}",
                    "Entry":     f"₹{ep.get('ideal','?')}",
                    "Target 1":  f"₹{tp.get('T1','?')}",
                    "Stop Loss": f"₹{p.get('stop_loss','?')}",
                    "R:R":       p.get("risk_reward_ratio","?"),
                    "Conf %":    p.get("confidence_score",0),
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True,
                         column_config={"Conf %": st.column_config.ProgressColumn(
                             "Confidence", min_value=0, max_value=100, format="%d%%")})
        else:
            st.info("No picks yet. Run morning scan.")

    with col_right:
        st.markdown('<div class="section-header">Style Distribution</div>', unsafe_allow_html=True)
        if analysis:
            style_counts = {
                "Intraday":   len([p for p in analysis.get("intraday",[])   if p.get("recommendation")=="BUY"]),
                "Swing":      len([p for p in analysis.get("swing",[])      if p.get("recommendation")=="BUY"]),
                "Positional": len([p for p in analysis.get("positional",[]) if p.get("recommendation")=="BUY"]),
            }
            fig = go.Figure(go.Pie(
                labels=list(style_counts.keys()),
                values=list(style_counts.values()),
                hole=0.6,
                marker_colors=["#00d4aa","#0099ff","#ffa500"],
            ))
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#161b22",
                plot_bgcolor="#161b22",
                height=220,
                margin=dict(l=10,r=10,t=10,b=10),
                showlegend=True,
                legend=dict(font=dict(color="#8b949e", size=11)),
                font=dict(family="Inter"),
            )
            st.plotly_chart(fig, use_container_width=True, key="home_pie")


# ─────────────────────────────────────────────
# PAGE: TODAY'S PICKS
# ─────────────────────────────────────────────
elif "Picks" in page:
    st.markdown('<div class="page-title">Today\'s AI Stock Picks</div>', unsafe_allow_html=True)

    data = load_json("ai_analysis.json")
    if not data:
        st.info("No picks yet. Click **Run Morning Scan** in the sidebar.")
        st.stop()

    st.markdown(f'<div class="page-sub">Analysis date: {data.get("date","N/A")} • Powered by AI</div>', unsafe_allow_html=True)
    analysis = data.get("analysis", {})

    tab1, tab2, tab3 = st.tabs(["🔄  Intraday", "📈  Swing (2-5 days)", "📅  Positional (1-4 weeks)"])

    for tab, style in zip([tab1, tab2, tab3], ["intraday","swing","positional"]):
        with tab:
            picks = [p for p in analysis.get(style,[]) if p.get("recommendation")=="BUY"]
            if not picks:
                st.info(f"No BUY picks for {style} today.")
                continue

            st.markdown(f"**{len(picks)} BUY signals found**", unsafe_allow_html=True)

            for i, p in enumerate(picks, 1):
                ind  = p.get("indicators", {})
                ep   = p.get("entry_price", {})
                tp   = p.get("target_prices", {})
                ap   = p.get("alert_on_price", {})
                conf = p.get("confidence_score", 0)
                sym  = p.get("symbol","")
                rec  = p.get("recommendation","")
                risk = p.get("risk_level","Medium")

                with st.expander(
                    f"#{i}  {sym}  •  ₹{ind.get('current_price','?')}  "
                    f"•  Confidence {conf}/100  •  R:R {p.get('risk_reward_ratio','?')}",
                    expanded=(i==1)
                ):
                    # Header row
                    h1, h2, h3 = st.columns([3,1,1])
                    with h1:
                        st.markdown(
                            f'<span style="font-size:22px; font-weight:700; color:#e6edf3">{sym}</span>'
                            f'&nbsp;&nbsp;{rec_badge(rec)}&nbsp;&nbsp;{risk_badge(risk)}',
                            unsafe_allow_html=True
                        )
                        st.markdown(
                            f'<div style="font-size:13px; color:#8b949e; margin-top:6px;">'
                            f'{p.get("analysis_summary","")}</div>',
                            unsafe_allow_html=True
                        )
                    with h2:
                        st.markdown(f'<div class="metric-label">Confidence</div>', unsafe_allow_html=True)
                        st.markdown(confidence_bar(conf), unsafe_allow_html=True)
                        st.markdown(f'<div style="font-size:20px; font-weight:700; color:#00d4aa">{conf}/100</div>', unsafe_allow_html=True)
                    with h3:
                        st.markdown(f'<div class="metric-label">Hold Duration</div>', unsafe_allow_html=True)
                        st.markdown(f'<div style="font-size:14px; font-weight:600; color:#e6edf3; margin-top:8px">{p.get("hold_duration","?")}</div>', unsafe_allow_html=True)

                    st.markdown("<br>", unsafe_allow_html=True)

                    # Price levels
                    col_prices, col_chart = st.columns([1, 2])
                    with col_prices:
                        st.markdown('<div class="section-header">Price Levels</div>', unsafe_allow_html=True)
                        levels = [
                            ("Entry (Ideal)",  f"₹{ep.get('ideal','?')}",       "price-val-blue"),
                            ("Entry Zone",     f"₹{ep.get('range_low','?')} – ₹{ep.get('range_high','?')}", "price-val-white"),
                            ("Target 1",       f"₹{tp.get('T1','?')}",          "price-val-green"),
                            ("Target 2",       f"₹{tp.get('T2','?')}",          "price-val-green"),
                            ("Target 3",       f"₹{tp.get('T3','?')}",          "price-val-green"),
                            ("Stop Loss",      f"₹{p.get('stop_loss','?')}",    "price-val-red"),
                        ]
                        for label, val, cls in levels:
                            st.markdown(
                                f'<div class="price-row">'
                                f'<span class="price-label">{label}</span>'
                                f'<span class="{cls}">{val}</span>'
                                f'</div>',
                                unsafe_allow_html=True
                            )

                        st.markdown('<div class="section-header" style="margin-top:16px">Alert Triggers</div>', unsafe_allow_html=True)
                        st.markdown(
                            f'<div class="price-row">'
                            f'<span class="price-label">🔔 Buy Alert</span>'
                            f'<span class="price-val-blue">₹{ap.get("buy_alert_at","?")}</span>'
                            f'</div>'
                            f'<div class="price-row">'
                            f'<span class="price-label">📤 Sell Alert</span>'
                            f'<span class="price-val-green">₹{ap.get("sell_alert_at","?")}</span>'
                            f'</div>'
                            f'<div class="price-row">'
                            f'<span class="price-label">🛑 Stop Alert</span>'
                            f'<span class="price-val-red">₹{ap.get("stop_alert_at","?")}</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                    with col_chart:
                        fig = candlestick_chart(sym)
                        if fig:
                            st.plotly_chart(fig, use_container_width=True,
                                            key=f"chart_{style}_{i}_{sym}")

                    # Signals
                    st.markdown('<div class="section-header">Key Signals</div>', unsafe_allow_html=True)
                    signals_html = "".join([f'<span class="signal-pill">✦ {s}</span>' for s in p.get("key_signals",[])])
                    st.markdown(signals_html, unsafe_allow_html=True)
                    st.markdown(
                        f'<div style="font-size:12px; color:#6e7681; margin-top:10px;">'
                        f'<b style="color:#8b949e">Exit if:</b> {p.get("exit_trigger","?")}</div>',
                        unsafe_allow_html=True
                    )

                    # Action buttons
                    st.markdown("<br>", unsafe_allow_html=True)
                    b1, b2, b3 = st.columns(3)
                    with b1:
                        if st.button(f"📨 Send Telegram Alert", key=f"tel_{style}_{i}"):
                            from alerts import send_buy_alert
                            send_buy_alert(p)
                            st.success("Alert sent!")
                    with b2:
                        if st.button(f"➕ Add to Portfolio", key=f"add_{style}_{i}"):
                            from portfolio import add_holding
                            from datetime import date
                            add_holding(sym, ep.get("ideal", 0), 1,
                                        str(date.today()),
                                        tp.get("T1", 0),
                                        p.get("stop_loss", 0), style)
                            st.success(f"Added {sym} to portfolio!")


# ─────────────────────────────────────────────
# PAGE: MY PORTFOLIO
# ─────────────────────────────────────────────
elif "Portfolio" in page:
    st.markdown('<div class="page-title">My Portfolio</div>', unsafe_allow_html=True)

    portfolio = load_json("portfolio.json")
    holdings  = portfolio.get("holdings", [])

    col_table, col_form = st.columns([3, 1])

    with col_form:
        st.markdown('<div class="section-header">Add Position</div>', unsafe_allow_html=True)
        sym  = st.text_input("Symbol", placeholder="e.g. RELIANCE")
        bp   = st.number_input("Buy Price (₹)", min_value=1.0, step=0.5)
        qty  = st.number_input("Quantity", min_value=1, step=1)
        bd   = st.date_input("Buy Date")
        tgt  = st.number_input("Target (₹)", min_value=1.0, step=0.5)
        sl   = st.number_input("Stop Loss (₹)", min_value=1.0, step=0.5)
        sty  = st.selectbox("Style", ["swing","intraday","positional"])
        if st.button("➕  Add to Portfolio"):
            if sym:
                from portfolio import add_holding
                add_holding(sym.upper(), bp, int(qty), str(bd), tgt, sl, sty)
                st.success(f"✅ Added {sym.upper()}")
                st.rerun()
            else:
                st.warning("Enter a symbol.")

        if holdings:
            st.markdown('<div class="section-header" style="margin-top:20px">Close Position</div>', unsafe_allow_html=True)
            close_sym   = st.selectbox("Stock", [h["symbol"] for h in holdings])
            close_price = st.number_input("Sell Price (₹)", min_value=1.0, step=0.5)
            if st.button("🔴  Close Position"):
                from portfolio import remove_holding
                remove_holding(close_sym, close_price)
                st.success(f"Closed {close_sym}")
                st.rerun()

    with col_table:
        if not holdings:
            st.info("No holdings yet. Add your first position.")
        else:
            rows        = []
            total_inv   = 0
            total_cur   = 0
            total_pnl_v = 0

            for h in holdings:
                cmp     = get_live_price(h["symbol"]) or h["buy_price"]
                pnl     = (cmp - h["buy_price"]) * h["quantity"]
                pnl_pct = ((cmp - h["buy_price"]) / h["buy_price"]) * 100
                inv     = h["buy_price"] * h["quantity"]
                total_inv   += inv
                total_cur   += cmp * h["quantity"]
                total_pnl_v += pnl
                pnl_arrow    = "▲" if pnl >= 0 else "▼"
                rows.append({
                    "Symbol":     h["symbol"],
                    "Qty":        h["quantity"],
                    "Buy ₹":     h["buy_price"],
                    "CMP ₹":     cmp,
                    "Target ₹":  h["target"],
                    "SL ₹":      h["stop_loss"],
                    "P&L ₹":    round(pnl, 2),
                    "P&L %":    round(pnl_pct, 2),
                    "Style":      h["style"].capitalize(),
                })

            total_pnl_pct = (total_pnl_v / total_inv * 100) if total_inv else 0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Invested",     f"₹{total_inv:,.0f}")
            m2.metric("Current Value",f"₹{total_cur:,.0f}")
            m3.metric("Total P&L",    f"₹{total_pnl_v:+,.0f}", f"{total_pnl_pct:+.2f}%")
            m4.metric("Positions",    len(holdings))

            st.markdown("<br>", unsafe_allow_html=True)
            df = pd.DataFrame(rows)
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "P&L %": st.column_config.NumberColumn("P&L %", format="%.2f%%"),
                    "P&L ₹": st.column_config.NumberColumn("P&L ₹", format="₹%.2f"),
                }
            )

            # P&L bar chart
            if rows:
                fig = go.Figure(go.Bar(
                    x=[r["Symbol"] for r in rows],
                    y=[r["P&L ₹"] for r in rows],
                    marker_color=["#00d4aa" if r["P&L ₹"] >= 0 else "#ff4b4b" for r in rows],
                    text=[f"₹{r['P&L ₹']:+,.0f}" for r in rows],
                    textposition="outside",
                ))
                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#161b22",
                    plot_bgcolor="#161b22",
                    height=220,
                    margin=dict(l=10,r=10,t=20,b=10),
                    font=dict(family="Inter", color="#8b949e"),
                    yaxis=dict(gridcolor="#21262d"),
                    xaxis=dict(gridcolor="#21262d"),
                    title=dict(text="P&L by Position", font=dict(color="#6e7681", size=12)),
                )
                st.plotly_chart(fig, use_container_width=True, key="portfolio_pnl_bar")

            # Closed trades
            closed = portfolio.get("closed_trades", [])
            if closed:
                st.markdown('<div class="section-header">Closed Trades</div>', unsafe_allow_html=True)
                closed_rows = [{"Symbol": t["symbol"], "Buy ₹": t["buy_price"],
                                "Sell ₹": t["sell_price"], "P&L ₹": t.get("pnl",0),
                                "P&L %": t.get("pnl_pct",0), "Date": t.get("sell_date","")}
                               for t in closed]
                st.dataframe(pd.DataFrame(closed_rows), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────
# PAGE: ANALYZE STOCK
# ─────────────────────────────────────────────
elif "Analyze" in page:
    st.markdown('<div class="page-title">Analyze Any Stock</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Enter any NSE symbol for instant AI-powered analysis</div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns([2,1,1])
    symbol = c1.text_input("", placeholder="e.g. RELIANCE, TCS, INFY, ZOMATO")
    style  = c2.selectbox("", ["swing","intraday","positional"], label_visibility="collapsed")
    run    = c3.button("🔍  Analyze Now", use_container_width=True)

    if run and symbol:
        with st.spinner(f"Analyzing {symbol.upper()} with AI..."):
            try:
                from ai_analyst import AIAnalyst
                analyst = AIAnalyst()
                result  = analyst.analyze_stock(symbol.upper()+".NS", style)
                if result:
                    ind  = result.get("indicators",{})
                    ep   = result.get("entry_price",{})
                    tp   = result.get("target_prices",{})
                    ap   = result.get("alert_on_price",{})
                    rec  = result.get("recommendation","")
                    conf = result.get("confidence_score",0)
                    risk = result.get("risk_level","Medium")

                    # Header
                    st.markdown(
                        f'<div style="margin:16px 0">'
                        f'<span style="font-size:28px;font-weight:700;color:#e6edf3">{symbol.upper()}</span>'
                        f'&nbsp;&nbsp;{rec_badge(rec)}&nbsp;&nbsp;{risk_badge(risk)}'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    st.markdown(
                        f'<div style="font-size:14px;color:#8b949e;margin-bottom:20px">'
                        f'{result.get("analysis_summary","")}</div>',
                        unsafe_allow_html=True
                    )

                    # Metrics row
                    m1,m2,m3,m4,m5 = st.columns(5)
                    m1.metric("Current Price", f"₹{ind.get('current_price','?')}")
                    m2.metric("Ideal Entry",   f"₹{ep.get('ideal','?')}")
                    m3.metric("Stop Loss",     f"₹{result.get('stop_loss','?')}")
                    m4.metric("R:R Ratio",     result.get("risk_reward_ratio","?"))
                    m5.metric("Confidence",    f"{conf}/100")

                    st.markdown(confidence_bar(conf), unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)

                    col_left, col_right = st.columns([1,2])
                    with col_left:
                        st.markdown('<div class="section-header">Price Targets</div>', unsafe_allow_html=True)
                        for label, val, cls in [
                            ("Target 1", f"₹{tp.get('T1','?')}", "price-val-green"),
                            ("Target 2", f"₹{tp.get('T2','?')}", "price-val-green"),
                            ("Target 3", f"₹{tp.get('T3','?')}", "price-val-green"),
                            ("Stop Loss",f"₹{result.get('stop_loss','?')}", "price-val-red"),
                        ]:
                            st.markdown(
                                f'<div class="price-row">'
                                f'<span class="price-label">{label}</span>'
                                f'<span class="{cls}">{val}</span></div>',
                                unsafe_allow_html=True
                            )

                        st.markdown('<div class="section-header" style="margin-top:16px">Indicators</div>', unsafe_allow_html=True)
                        for label, val in [
                            ("RSI",     ind.get("rsi","?")),
                            ("MACD",    ind.get("macd_crossover","?")),
                            ("Volume",  f"{ind.get('volume_ratio','?')}x avg"),
                            ("ADX",     f"{ind.get('adx','?')} ({ind.get('trend_strength','?')})"),
                            ("Pattern", ind.get("candle_pattern","none")),
                        ]:
                            st.markdown(
                                f'<div class="price-row">'
                                f'<span class="price-label">{label}</span>'
                                f'<span class="price-val-white">{val}</span></div>',
                                unsafe_allow_html=True
                            )

                    with col_right:
                        fig = candlestick_chart(symbol.upper())
                        if fig:
                            st.plotly_chart(fig, use_container_width=True,
                                            key=f"analyze_{symbol}_{style}")

                    st.markdown('<div class="section-header">Key Signals</div>', unsafe_allow_html=True)
                    signals_html = "".join([f'<span class="signal-pill">✦ {s}</span>' for s in result.get("key_signals",[])])
                    st.markdown(signals_html, unsafe_allow_html=True)
                    st.markdown(f'<div style="font-size:12px;color:#6e7681;margin-top:10px"><b style="color:#8b949e">Exit if:</b> {result.get("exit_trigger","?")}</div>', unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)

                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("📨 Send Telegram Alert", key="analyze_tel"):
                            from alerts import send_buy_alert
                            send_buy_alert(result)
                            st.success("Alert sent!")
                    with b2:
                        if st.button("➕ Add to Portfolio", key="analyze_add"):
                            from portfolio import add_holding
                            from datetime import date
                            add_holding(symbol.upper(), ep.get("ideal",0), 1,
                                        str(date.today()), tp.get("T1",0),
                                        result.get("stop_loss",0), style)
                            st.success(f"Added {symbol.upper()}!")
                else:
                    st.error("Analysis failed. Check your API key in .env")
            except Exception as e:
                st.error(f"Error: {e}")
    elif run:
        st.warning("Enter a stock symbol first.")


# ─────────────────────────────────────────────
# PAGE: HOLD / SELL REVIEW
# ─────────────────────────────────────────────
elif "Hold" in page:
    st.markdown('<div class="page-title">Hold / Sell AI Review</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">AI reviews all holdings and recommends action</div>', unsafe_allow_html=True)

    if st.button("▶  Run AI Analysis Now"):
        with st.spinner("Analyzing all holdings..."):
            try:
                from portfolio import run_hold_sell_analysis
                run_hold_sell_analysis()
                st.success("Done!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    data = load_json("hold_sell_analysis.json")
    if not data:
        st.info("No analysis yet. Add holdings in Portfolio, then run analysis above.")
        st.stop()

    for r in data:
        action  = r.get("action","HOLD")
        urgency = r.get("urgency","")
        pnl     = r.get("pnl_percent",0)
        symbol  = r.get("symbol","")

        colors = {
            "HOLD":         ("#ffa500","🔵"),
            "FULL_SELL":    ("#ff4b4b","🔴"),
            "PARTIAL_SELL": ("#ff8c00","🟡"),
            "ADD_MORE":     ("#00d4aa","🟢"),
        }
        color, emoji = colors.get(action, ("#6e7681","⚪"))
        label = action.replace("_"," ")
        pnl_color = "#00d4aa" if pnl >= 0 else "#ff4b4b"

        with st.expander(
            f"{emoji}  {symbol}  •  {label}  •  "
            f"Urgency: {urgency}  •  P&L: {pnl:+.2f}%",
            expanded=True
        ):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Action",          label)
            c2.metric("P&L",             f"{pnl:+.2f}%")
            c3.metric("Revised Target",  f"₹{r.get('revised_target','?')}")
            c4.metric("Revised SL",      f"₹{r.get('revised_stop_loss','?')}")

            st.markdown(
                f'<div style="background:#161b22;border:1px solid #21262d;'
                f'border-radius:10px;padding:14px;margin:10px 0;">'
                f'<div style="font-size:11px;color:#6e7681;margin-bottom:6px">AI REASONING</div>'
                f'<div style="font-size:14px;color:#e6edf3">{r.get("reasoning","")}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
            st.markdown(
                f'<div style="font-size:12px;color:#6e7681">'
                f'⚠️ Risk Flag: <span style="color:#ffa500">{r.get("risk_flag","None")}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button(f"📨 Send Alert for {symbol}", key=f"hs_{symbol}"):
                from alerts import send_portfolio_alert
                send_portfolio_alert(r)
                st.success("Alert sent!")