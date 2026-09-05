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


def build_buy_order(symbol, analysis_price, atr, cash, tp=None, stop_rc=None,
                    style="swing"):
    """Construct a buyer-safe order for Add-to-Portfolio.

    Guards against the classic mistakes:
      - uses the LIVE quote for the fill when it is within 10% of the analysis
        price (avoids recording a stale basis);
      - caps the quantity so the position notional never exceeds available cash;
      - never returns a zero or negative stop.

    Reward/risk floor and the sector/position caps are deliberately NOT
    enforced here (relaxed policy) so a valid order is never blocked on them.

    Returns a dict with {ok, reason, price, qty, target, stop, rr, live_price}.
    Callers use `ok` to gate the Add button.
    """
    from config import ATR_MULT
    cash = float(cash or st.session_state.get("cash_per_trade", 100_000) or 0)

    live = get_live_price(symbol)
    price = float(analysis_price) if analysis_price else live
    drift = None
    if live and analysis_price:
        try:
            drift = abs(float(live) - float(analysis_price)) / float(analysis_price)
        except Exception:
            drift = None
        if drift is not None and drift < 0.10:   # fresh quote within 10% => use it
            price = float(live)
    elif not price:
        price = live
    price = float(price) if price else 0.0

    if price <= 0:
        return {"ok": False, "reason": "No usable market price", "price": 0,
                "qty": 0, "target": 0, "stop": stop_rc, "rr": 0, "live_price": live}

    # Stop from ATR distance (style-appropriate multiplier — matches the
    # analysis engine so the R:R re-check is consistent with the paper targets)
    stop = stop_rc
    if atr and atr > 0:
        try:
            mult = ATR_MULT.get(style, 2.5)
            stop = round(price - float(atr) * float(mult), 2)
        except Exception:
            stop = stop_rc
    if not stop or stop >= price:
        return {"ok": False, "reason": "invalid stop-loss (not below entry)",
                "price": price, "qty": 0, "target": 0, "stop": stop, "rr": 0,
                "live_price": live}

    # Target: use T2 (the 1:2 level the alert quotes) when present, else T1.
    tp = tp or {}
    target = tp.get("T2") or tp.get("T1") or (price * 1.05)

    # Reward/risk ratio — informational only, no longer a hard gate.
    rr = 0.0
    denom = price - stop
    if denom > 0:
        rr = (float(target) - price) / denom
    reasons = []

    # Quantity: starts from the ATR-based risk amount (1% of budget), then is
    # hard-capped only by available cash (notional <= cash).
    qty = 0
    try:
        from portfolio import compute_position_and_stop
        qty = int(compute_position_and_stop(cash, price, atr)["qty"]) if atr else 0
    except Exception:
        qty = 0
    if price > 0:
        cash_cap = int(cash // price)
        qty = max(0, min(qty, cash_cap))
    if qty <= 0:
        reasons.append("position quantity would be zero after the cash cap")
    notional = qty * price
    if notional > cash:
        reasons.append(f"notional ₹{notional:,.0f} exceeds available cash ₹{cash:,.0f}")

    ok = (not reasons) and qty > 0
    return {
        "ok": ok, "reason": "; ".join(reasons) or "",
        "price": round(price, 2), "qty": qty,
        "target": round(float(target), 2), "stop": round(float(stop), 2),
        "rr": round(rr, 2), "live_price": live,
    }


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


def dead_cat_warning(obj):
    """Return a human-readable warning (or '') when a pick is a bounce-following
    a high-volume breakdown that was NOT reclaimed — the classic bull trap."""
    if not obj.get("recent_breakdown_day"):
        return ""
    bd_date = obj.get("breakdown_date") or "recent"
    bd_pct = obj.get("breakdown_change_pct")
    bd_vol = obj.get("breakdown_volume_ratio")
    lvl = obj.get("breakdown_reclaim_level")
    if not obj.get("reclaims_breakdown_level", False):
        return ("🚨 Dead-cat bounce risk: stock crashed "
                f"{bd_pct}% on {bd_vol}x volume on {bd_date} and the bounce "
                f"has NOT reclaimed the broken swing high"
                + (f" (₹{lvl})" if lvl else "") + ". WATCHLIST only — wait for reclaim.")
    if not obj.get("fresh_bullish_trigger", False):
        return ("⚠️ Bounce after breakdown without a fresh MACD/EMA bullish "
                "cross — WATCHLIST, not a confirmed BUY. Entry needs a fresh trigger.")
    return ""


def explain_pick(obj):
    """Return list of (component, human-friendly reason) for a pick or analysis result."""
    out = []
    # Confidence / ensemble
    conf = obj.get('confidence_score') or obj.get('confidence')
    if conf is not None:
        out.append(("AI Confidence", f"{conf}/100 — model score for overall pattern and momentum."))
    ens = obj.get('ensemble_score')
    if ens is not None:
        out.append(("Ensemble Score", f"{ens}/100 — aggregated across multiple signals and scorers."))

    # Style-specific signals
    bscore = obj.get('buffett_score')
    if bscore is not None:
        text = obj.get('buffett_reasons') or "Value & quality factors considered"
        out.append(("Buffett-style", f"{bscore}/100 — {text}"))
    rscore = obj.get('rakesh_score')
    if rscore is not None:
        text = obj.get('rakesh_reasons') or "Momentum & growth factors considered"
        out.append(("Jhunjhunwala-style", f"{rscore}/100 — {text}"))

    # Indicators
    inds = obj.get('indicators') or {}
    rsi = obj.get('rsi') or inds.get('rsi')
    if rsi is not None:
        tag = "neutral"
        try:
            rsi_v = float(rsi)
            tag = "bullish" if rsi_v > 55 else "bearish" if rsi_v < 40 else "neutral"
        except Exception:
            pass
        out.append(("RSI", f"{rsi} — {tag} momentum"))
    atr = obj.get('atr') or inds.get('atr')
    if atr is not None:
        out.append(("ATR (volatility)", f"{atr} — recent price volatility used for stop sizing."))
    vol = obj.get('volume_ratio') or inds.get('volume_ratio')
    if vol is not None:
        out.append(("Volume", f"{vol}x average — shows trading participation."))

    # ── Conditions / gate review (mirrors the deterministic BUY gate) ──
    # Surfaces exactly why a candidate is (or is not) a valid BUY.
    bb = inds.get('bb_pct') or obj.get('bb_pct')
    if bb is not None:
        try:
            bb_f = float(bb)
            if bb_f > 1.0:
                out.append(("Breakout position",
                            f"BB% {bb_f:.2f} — price ABOVE the upper band; "
                            "mean-reversion / fade risk unless EMA crossover confirmed"))
            elif bb_f > 0.8:
                out.append(("Band position", f"BB% {bb_f:.2f} — near upper band; limited upside headroom"))
        except Exception:
            pass
    win = inds.get('sig_win_pct') or obj.get('sig_win_pct')
    ns = inds.get('sig_samples') or obj.get('sig_samples') or 0
    if win is not None:
        out.append(("Signal win-history", f"{win}% next-session win over {ns} sessions"))
    cross = obj.get('buy_rule_passed')
    if cross is not None:
        out.append(("EMA crossover confirm", "Yes" if cross else "No — currently treated as unconfirmed breakout"))

    # Technical signals
    signals = obj.get('key_signals') or obj.get('signals') or []
    if signals:
        out.append(("Top Signals", ", ".join(signals[:5])))

    # Price context
    price = (inds.get('current_price') if inds else None) or obj.get('current_price') or obj.get('price')
    if price is not None:
        out.append(("Price", f"₹{price}"))

    # Fallback: risk/reward (honest near-term ratio first)
    rr = obj.get('risk_reward_ratio')
    rr_t1 = obj.get('risk_reward_t1')
    if rr is not None:
        out.append(("Risk/Reward to T2", str(rr) + (f"  (to T1: {rr_t1})" if rr_t1 else "")))

    return out


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sidebar-title">📈 AI Stock Analyst</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sidebar-sub">NSE/BSE • {datetime.now().strftime("%d %b %Y, %H:%M")}</div>', unsafe_allow_html=True)
    st.divider()

    # build page list and include dynamic pages if report files exist
    page_items = [
        "🏠  Dashboard",
        "📊  Today's Picks",
        "💼  My Portfolio",
        "🔍  Analyze Stock",
        "📋  Hold / Sell Review",
    ]
    # dynamic report pages
    reports = {
        "portfolio_backtest_report.json": "📈  Backtests",
        "tuning_walkforward.json": "⚙️  Tuning Results",
        "buy_suggestions.json": "🛒  Buy Suggestions",
        "screener_results.json": "🔎  Screener Results",
    }
    for f, label in reports.items():
        if os.path.exists(f) and label not in page_items:
            page_items.append(label)

    page = st.radio("Navigation", page_items, label_visibility="collapsed")
    # cash per trade used for suggested position sizing
    cash_per_trade = st.number_input("Cash per trade (₹)", min_value=1000, value=100000, step=1000, key="cash_per_trade")

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

    if st.button("🗃️  Capture Fundamental Snapshots"):
        with st.status("Capturing current fundamentals for the NSE universe...", expanded=True) as status:
            try:
                from fundamental_snapshots import capture_symbol_snapshot
                from screener import NSE_STOCKS

                progress = st.progress(0)
                captured = 0
                failed = []
                total = len(NSE_STOCKS)
                for index, symbol in enumerate(NSE_STOCKS, 1):
                    ok, reason = capture_symbol_snapshot(symbol)
                    if ok:
                        captured += 1
                    else:
                        failed.append(f"{symbol}: {reason}")
                    progress.progress(index / total)
                status.update(
                    label=f"Captured {captured}/{total} fundamental snapshots",
                    state="complete" if captured else "error",
                    expanded=bool(failed),
                )
                if failed:
                    st.warning(f"{len(failed)} symbols were not captured. Review the details below.")
                    st.code("\n".join(failed[:20]))
                else:
                    st.success("All universe symbols were captured successfully.")
            except Exception as e:
                status.update(label="Snapshot capture failed", state="error")
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
            st.dataframe(df, width="stretch", hide_index=True,
                         column_config={"Conf %": st.column_config.ProgressColumn(
                             "Confidence", min_value=0, max_value=100, format="%d%%")})
        else:
            screener_data = load_json("screener_results.json")
            screener_results = screener_data.get("results", {})
            watchlist_count = sum(
                len([p for p in screener_results.get(style, [])
                     if p.get("selection_decision") == "WATCHLIST"])
                for style in ["intraday", "swing", "positional"]
            )
            regimes = {
                p.get("market_regime")
                for style in ["intraday", "swing", "positional"]
                for p in screener_results.get(style, [])
                if p.get("market_regime")
            }
            if screener_results:
                regime_text = ", ".join(sorted(regimes)) if regimes else "not recorded"
                st.info(
                    f"No BUY signals in the completed scan. "
                    f"{watchlist_count} candidate(s) remain on WATCHLIST; "
                    f"market regime: {regime_text}."
                )
            else:
                st.info("No completed scan found. Run the morning scan.")

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
            st.plotly_chart(fig, width="stretch", key="home_pie")


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
                st.info(f"No qualified BUY candidates for {style} today.")
                watchlist = [p for p in analysis.get(style, []) if p.get("recommendation") == "WATCHLIST"]
                if watchlist:
                    with st.expander("View watchlist and failed qualification checks"):
                        rows = []
                        for item in watchlist:
                            rows.append({
                                "Symbol": item.get("symbol", ""),
                                "Score": item.get("ensemble_score", ""),
                                "Decision": item.get("selection_decision", item.get("recommendation", "")),
                                "AI view": item.get("ai_recommendation", "Not available"),
                                "Why not qualified": "; ".join(item.get("eligibility_failures", [])) or "See analysis",
                            })
                        st.dataframe(pd.DataFrame(rows), hide_index=True)
                continue

            st.markdown(f"**{len(picks)} BUY signals found**", unsafe_allow_html=True)

            # ── Dashboard-side gate conditions (re-validate the pick live) ──
            # These mirror the deterministic gate so the analyst can SEE how
            # the BUY list survives stricter conditions and why a KOTAK-style
            # fade candidate no longer qualifies.
            def _fade_state(it):
                _i = it.get("indicators") or {}
                _w = _i.get("sig_win_pct")
                _n = _i.get("sig_samples") or 0
                try:
                    return _w is not None and int(_n) >= 20 and float(_w) < 45
                except Exception:
                    return False

            def _stretched_state(it):
                _i = it.get("indicators") or {}
                try:
                    return float(_i.get("bb_pct") or 0) > 1.0 and not it.get("buy_rule_passed")
                except Exception:
                    return False

            def _rsi_hot_state(it):
                _i = it.get("indicators") or {}
                try:
                    return float(_i.get("rsi") or 0) >= 70
                except Exception:
                    return False

            filter_desc = {
                "Stretched above UBB":  "BB% > 1 without EMA crossover (breakout-fade)",
                "RSI >= 70":            "Overbought / exhaustion",
                "Historical fade setup": "Setup won next session <45% historically",
            }
            active_filters = st.multiselect(
                "Exclude weak BUY candidates by condition",
                list(filter_desc.keys()),
                default=["Stretched above UBB", "Historical fade setup"],
                key=f"gatefilter_{style}",
            )
            picks = [p for p in picks
                     if not ("Stretched above UBB" in active_filters and _stretched_state(p))
                     and not ("RSI >= 70" in active_filters and _rsi_hot_state(p))
                     and not ("Historical fade setup" in active_filters and _fade_state(p))]

            if not picks:
                st.warning("All BUY candidates were excluded by the dashboard conditions. Untick a filter above to reveal the running list, or view the watchlist below.")
                continue

            # ── Sorting controls for picks ──────────────────────────────────
            sort_opt = st.selectbox("Sort picks by",
                                    ["Confidence", "R:R to T1", "R:R to T2",
                                     "Win%", "ATR", "Volume Ratio", "Price"],
                                    key=f"sort_{style}")
            sort_dir = st.radio("Direction", ["Descending", "Ascending"], index=0,
                                horizontal=True, key=f"dir_{style}")

            def _rr_num(item, key):
                raw = item.get(key) or item.get("risk_reward_ratio") or ""
                try:
                    return float(str(raw).split(":")[1])
                except Exception:
                    return 0.0

            def _sort_val(item):
                try:
                    if sort_opt == "Confidence":
                        return float(item.get('confidence_score', 0) or 0)
                    if sort_opt == "R:R to T1":
                        return _rr_num(item, 'risk_reward_t1')
                    if sort_opt == "R:R to T2":
                        return _rr_num(item, 'risk_reward_ratio')
                    if sort_opt == "Win%":
                        _i = item.get("indicators") or {}
                        return float(_i.get("sig_win_pct") or 0)
                    if sort_opt == "ATR":
                        return float((item.get("indicators") or {}).get("atr", 0) or 0)
                    if sort_opt == "Volume Ratio":
                        return float(item.get("volume_ratio", 0) or 0)
                    if sort_opt == "Price":
                        return float((item.get("indicators") or {}).get("current_price", 0) or 0)
                except Exception:
                    return 0.0
                return 0.0
            picks = sorted(picks, key=_sort_val, reverse=(sort_dir == "Descending"))

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
                    f"•  Confidence {conf}/100  •  R:R→T1 {p.get('risk_reward_t1','?')} / T2 {p.get('risk_reward_ratio','?')}",
                    expanded=(i == 1 and len(picks) <= 5)
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

                    # ── Conditions / gate review (live, re-validated) ────────
                    bb = float(ind.get("bb_pct") or 0)
                    rsi_v = float(ind.get("rsi") or 0)
                    win = ind.get("sig_win_pct")
                    samples = ind.get("sig_samples") or 0
                    stretched = bb > 1.0 and not p.get("buy_rule_passed")
                    hot = rsi_v >= 70
                    fade = win is not None and int(samples) >= 20 and float(win) < 45
                    issues = []
                    if stretched:
                        issues.append(f"Stretched above upper Bollinger (BB% {bb:.2f}) with no EMA-cross confirm — breakout-fade risk")
                    if hot:
                        issues.append(f"RSI {rsi_v:.0f} is overbought (≥70)")
                    if fade:
                        issues.append(f"Historical fade: setup won next session only {float(win):.0f}% ({samples} samples)")
                    if p.get("eligibility_failures"):
                        issues.extend(p.get("eligibility_failures") or [])
                    if issues:
                        for _g in issues:
                            st.warning(f"⚠️ {_g}")
                    else:
                        st.success("✅ BUY conditions validated — gate passed, no stretched/fade/exhaustion flags")
                    st.markdown(
                        f'<div style="font-size:12px; color:#8b949e">'
                        f'Signal data as of <b>{ind.get("data_as_of","n/a")}</b> • '
                        f'setup win-rate <b>{win if win is not None else "n/a"}%</b> over {samples} sessions • '
                        f'crossover-confirm <b>{"Yes" if p.get("buy_rule_passed") else "No"}</b></div>',
                        unsafe_allow_html=True
                    )

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
                        buy_alert  = ap.get("buy_alert_at")
                        sell_alert = ap.get("sell_alert_at")
                        stop_alert = ap.get("stop_alert_at")
                        st.markdown(
                            f'<div class="price-row">'
                            f'<span class="price-label">🔔 Buy Alert</span>'
                            f'<span class="price-val-blue">₹{buy_alert if buy_alert is not None else "—"}</span>'
                            f'</div>'
                            f'<div class="price-row">'
                            f'<span class="price-label">📤 Sell Alert</span>'
                            f'<span class="price-val-green">₹{sell_alert if sell_alert is not None else "—"}</span>'
                            f'</div>'
                            f'<div class="price-row">'
                            f'<span class="price-label">🛑 Stop Alert</span>'
                            f'<span class="price-val-red">₹{stop_alert if stop_alert is not None else "—"}</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                    with col_chart:
                        fig = candlestick_chart(sym)
                        if fig:
                            st.plotly_chart(fig, width="stretch",
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

                    # Explainability: show breakdown of scores and signals
                    with st.expander("Why this pick? (explainability)"):
                        expl = explain_pick(p)
                        rows = ""
                        for k, v in expl:
                            rows += f"- **{k}:** {v}  \n"
                        st.markdown(rows)

                    # Action buttons
                    st.markdown("<br>", unsafe_allow_html=True)
                    b1, b2, b3 = st.columns(3)
                    with b1:
                        if st.button(f"📨 Send Telegram Alert", key=f"picks_tel_{style}_{i}"):
                            from alerts import send_buy_alert
                            send_buy_alert(p)
                            st.success("Alert sent!")
                    with b2:
                        # Buyer-safe order: live-stamp price, cash/notional cap,
                        # reward/risk floor, style-appropriate target.
                        try:
                            from portfolio import add_holding
                        except Exception:
                            add_holding = None
                        ind_for_pos = p.get('indicators', {}) or {}
                        price_for_pos = ep.get('ideal', 0) or ind_for_pos.get('current_price', 0)
                        atr_for_pos = ind_for_pos.get('atr')
                        cash = st.session_state.get('cash_per_trade', 100000)
                        order = build_buy_order(sym, price_for_pos, atr_for_pos, cash,
                                                tp=tp, stop_rc=p.get('stop_loss'), style=style)
                        qty_suggest = int(order.get('qty', 0))
                        price_use = order.get('price') or price_for_pos
                        stop_suggest = order.get('stop') or p.get('stop_loss', 0)
                        target_use = order.get('target') or tp.get('T1', 0)
                        add_disabled = not order.get('ok')
                        # log the displayed suggestion
                        try:
                            from signal_logger import log_signal
                            log_signal(sym, price_use, atr=atr_for_pos, qty=qty_suggest,
                                       stop_loss=stop_suggest, source='today_display')
                        except Exception:
                            pass
                        live_txt = f" • live ₹{order.get('live_price')}" if order.get('live_price') else ''
                        st.markdown(
                            f"<div style='font-size:12px;color:#8b949e'>"
                            f"Suggested: qty {qty_suggest} • stop ₹{stop_suggest} • "
                            f"target ₹{order.get('target','?')} • R:R {order.get('rr','?')}{live_txt}"
                            f"</div>", unsafe_allow_html=True)
                        if add_disabled:
                            st.warning(f"⚠️ Add blocked: {order.get('reason')}")
                        if st.button(f"➕ Add to Portfolio ({qty_suggest})",
                                     key=f"picks_add_{style}_{i}",
                                     disabled=add_disabled):
                            from datetime import date
                            if not (add_holding and order.get('ok')):
                                st.error(f"❌ Cannot add {sym}: {order.get('reason') or 'invalid order'}")
                            else:
                                from portfolio import last_add_failures
                                ok = add_holding(sym, price_use, qty_suggest,
                                                 str(date.today()), target_use,
                                                 stop_suggest, style, cash=cash)
                                if ok:
                                    try:
                                        from signal_logger import log_signal
                                        log_signal(sym, price_use, atr=atr_for_pos, qty=qty_suggest, stop_loss=stop_suggest, source='today_picks')
                                    except Exception:
                                        pass
                                    st.success(f"Added {sym} to portfolio!")
                                else:
                                    reasons = "  \n".join(f"- {r}" for r in last_add_failures) or "Unknown validation error"
                                    st.error(f"❌ Could not add {sym}:\n{reasons}")


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
        bp   = st.number_input("Buy Price (₹) — 0 = live/auto", min_value=0.0, value=0.0, step=0.5)
        qty  = st.number_input("Quantity", min_value=1, step=1)
        bd   = st.date_input("Buy Date")
        tgt  = st.number_input("Target (₹) — 0 = auto-suggest", min_value=0.0, value=0.0, step=0.5)
        sl   = st.number_input("Stop Loss (₹) — 0 = auto-suggest", min_value=0.0, value=0.0, step=0.5)
        sty  = st.selectbox("Style", ["swing","intraday","positional"])
        if st.button("Suggest qty & stop", key='suggest_add'):
            if not sym:
                st.warning("Enter a symbol first to suggest quantity and stop.")
            else:
                try:
                    from indicators import IndicatorEngine
                    price_val = bp if bp and bp > 0 else get_live_price(sym) or 0
                    eng = IndicatorEngine(sym + ".NS")
                    ok = eng.fetch()
                    ind_vals = eng.compute_all() if ok else {}
                    atr_val = ind_vals.get('atr') if ind_vals else None
                    cash = st.session_state.get('cash_per_trade', 100000)
                    order = build_buy_order(sym.upper(), price_val, atr_val, cash,
                                            tp={'T1': tgt, 'T2': tgt}, stop_rc=sl, style=sty)
                    live_txt = f" • live ₹{order.get('live_price')}" if order.get('live_price') else ''
                    st.info(f"Suggested: qty {order.get('qty',1)} • stop ₹{order.get('stop', sl)} • R:R {order.get('rr','?')}{live_txt}")
                    if not order.get('ok'):
                        st.warning(f"⚠️ {order.get('reason')}")
                except Exception as e:
                    st.error(f"Suggest failed: {e}")
        if st.button("➕  Add to Portfolio"):
            if sym:
                from portfolio import add_holding, last_add_failures
                cash = st.session_state.get('cash_per_trade', 100000)
                # Never record junk levels: auto-fill target/stop from the live
                # ATR when the caller left them at 0 (HINDCOPPER holding was
                # stored with target/stop = 1.0, making the stop meaningless).
                price_use = bp if bp and bp > 0 else get_live_price(sym) or 0
                if price_use <= 0:
                    st.error("❌ No usable price — enter a Buy Price or a live quote is required.")
                else:
                    use_qty = int(qty)
                    use_tgt = tgt
                    use_sl = sl
                    if use_tgt <= 0 or use_sl <= 0:
                        try:
                            from indicators import IndicatorEngine
                            _eng = IndicatorEngine(sym + ".NS")
                            _atr = None
                            if _eng.fetch():
                                _atr = _eng.compute_all().get('atr')
                            _order = build_buy_order(sym.upper(), price_use, _atr, cash,
                                                     tp={}, stop_rc=None, style=sty)
                            if not use_tgt:
                                use_tgt = _order.get('target') or round(price_use * 1.05, 2)
                            if not use_sl:
                                use_sl = _order.get('stop') or round(price_use * 0.95, 2)
                        except Exception:
                            if not use_tgt:
                                use_tgt = round(price_use * 1.05, 2)
                            if not use_sl:
                                use_sl = round(price_use * 0.95, 2)
                    ok = add_holding(sym.upper(), price_use, use_qty, str(bd), use_tgt, use_sl, sty, cash=cash)
                    if ok:
                        st.success(f"✅ Added {sym.upper()} (target ₹{use_tgt}, stop ₹{use_sl})")
                        st.rerun()
                    else:
                        reasons = "  \n".join(f"- {r}" for r in last_add_failures) or "Unknown validation error"
                        st.error(f"❌ Could not add {sym.upper()}:\n{reasons}")
            else:
                st.warning("Enter a symbol.")

        st.markdown('<div class="section-header" style="margin-top:20px">Edit Position</div>', unsafe_allow_html=True)
        if portfolio.get('holdings'):
            edit_sym = st.selectbox("Which position to edit", [h['symbol'] for h in portfolio.get('holdings')], key="edit_select")
            if edit_sym:
                # load values
                hobj = next((h for h in portfolio.get('holdings') if h['symbol']==edit_sym), None)
                if hobj:
                    new_price = st.number_input("Buy Price (₹)", value=hobj.get('buy_price', 0.0), key="edit_bp")
                    new_qty   = st.number_input("Quantity", value=hobj.get('quantity', 1), step=1, key="edit_qty")
                    new_date  = st.text_input("Buy Date (YYYY-MM-DD)", value=hobj.get('buy_date',''), key="edit_bd")
                    new_tgt   = st.number_input("Target (₹)", value=hobj.get('target', 0.0), key="edit_tgt")
                    new_sl    = st.number_input("Stop Loss (₹)", value=hobj.get('stop_loss', 0.0), key="edit_sl")
                    new_style = st.selectbox("Style", ["swing","intraday","positional"], index=["swing","intraday","positional"].index(hobj.get('style','swing')), key="edit_style")
                    if st.button("💾 Save Changes", key="save_edit"):
                        import importlib
                        try:
                            import portfolio as _portfolio
                        except Exception:
                            _portfolio = None

                        # Ensure the function exists; try reload or direct import fallback
                        update_func = None
                        if _portfolio is not None:
                            if not hasattr(_portfolio, 'update_holding'):
                                try:
                                    importlib.reload(_portfolio)
                                except Exception:
                                    pass
                            update_func = getattr(_portfolio, 'update_holding', None)

                        if update_func is None:
                            try:
                                from portfolio import update_holding as update_func
                            except Exception:
                                update_func = None

                        if update_func:
                            ok = update_func(
                                edit_sym, buy_price=new_price, quantity=new_qty,
                                buy_date=new_date, target=new_tgt, stop_loss=new_sl,
                                style=new_style
                            )
                        else:
                            ok = False
                        if ok:
                            st.success(f"Updated {edit_sym}")
                            st.rerun()
                        else:
                            st.error("Failed to update")
                    # Partial / Full close controls
                    st.markdown('<div style="margin-top:12px">', unsafe_allow_html=True)
                    max_q = int(hobj.get('quantity', 0))
                    sell_qty = st.number_input("Partial Close Quantity", min_value=0, max_value=max_q, value=0, step=1, key="partial_qty")
                    sell_price = st.number_input("Sell Price (₹)", min_value=0.0, value=round(get_live_price(hobj['symbol']) or hobj.get('buy_price',0.0),2), step=0.5, key="partial_price")
                    if st.button("Sell (Partial / Full)", key="partial_sell"):
                        import importlib
                        try:
                            import portfolio as _portfolio
                        except Exception:
                            _portfolio = None

                        remove_func = None
                        if _portfolio is not None:
                            if not hasattr(_portfolio, 'remove_holding'):
                                try:
                                    importlib.reload(_portfolio)
                                except Exception:
                                    pass
                            remove_func = getattr(_portfolio, 'remove_holding', None)

                        if remove_func is None:
                            try:
                                from portfolio import remove_holding as remove_func
                            except Exception:
                                remove_func = None

                        if remove_func:
                            if sell_qty <= 0:
                                remove_func(edit_sym, sell_price)
                                st.success(f"Closed {edit_sym}")
                                st.rerun()
                            else:
                                remove_func(edit_sym, sell_price, quantity=int(sell_qty))
                                st.success(f"Sold {sell_qty} of {edit_sym}")
                                st.rerun()
                        else:
                            st.error("Portfolio remove function unavailable")
                    st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="font-size:12px;color:#6e7681">No positions to edit.</div>', unsafe_allow_html=True)
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
                width="stretch",
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
                st.plotly_chart(fig, width="stretch", key="portfolio_pnl_bar")

            # Closed trades
            closed = portfolio.get("closed_trades", [])
            if closed:
                st.markdown('<div class="section-header">Closed Trades</div>', unsafe_allow_html=True)
                closed_rows = [{"Symbol": t["symbol"], "Buy ₹": t["buy_price"],
                                "Sell ₹": t["sell_price"], "P&L ₹": t.get("pnl",0),
                                "P&L %": t.get("pnl_pct",0), "Date": t.get("sell_date","")}
                               for t in closed]
                st.dataframe(pd.DataFrame(closed_rows), width="stretch", hide_index=True)


# ─────────────────────────────────────────────
# PAGE: ANALYZE STOCK
# ─────────────────────────────────────────────
elif "Analyze" in page:
    st.markdown('<div class="page-title">Analyze Any Stock</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Enter any NSE symbol for instant AI-powered analysis</div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns([2,1,1])
    symbol = c1.text_input("Symbol", placeholder="e.g. RELIANCE, TCS, INFY, ZOMATO", key="analyze_symbol", label_visibility="collapsed")
    style  = c2.selectbox("Trading Style", ["swing","intraday","positional"], label_visibility="collapsed", key="analyze_style")
    run    = c3.button("🔍  Analyze Now", key="analyze_run", width='stretch')

    if run and symbol:
        # Normalize the input: accept "RELIANCE", "RELIANCE.NS", "reliance" alike.
        sym_clean = symbol.strip().upper().replace(".NS", "").replace(".NSE", "").strip()
        sym_yf    = sym_clean + ".NS"
        with st.spinner(f"Analyzing {sym_clean} with AI..."):
            try:
                from ai_analyst import AIAnalyst
                analyst = AIAnalyst()
                result  = analyst.analyze_stock(sym_yf, style)
                if result:
                    ind  = result.get("indicators", {})
                    ep   = result.get("entry_price", {})
                    tp   = result.get("target_prices", {})
                    ap   = result.get("alert_on_price", {})
                    rec  = result.get("recommendation", "")
                    conf = result.get("confidence_score", 0)
                    risk = result.get("risk_level", "Medium")

                    # Header
                    st.markdown(
                        f'<div style="margin:16px 0">'
                        f'<span style="font-size:28px;font-weight:700;color:#e6edf3">{sym_clean}</span>'
                        f'&nbsp;&nbsp;{rec_badge(rec)}&nbsp;&nbsp;{risk_badge(risk)}'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    st.markdown(
                        f'<div style="font-size:14px;color:#8b949e;margin-bottom:20px">'
                        f'{result.get("analysis_summary","")}</div>',
                        unsafe_allow_html=True
                    )

                    # Dead-cat bounce / bull-trap guard (same logic as Picks & Screener pages)
                    dcw = dead_cat_warning(ind)
                    if dcw:
                        st.error(dcw)

                    # Data-integrity anomaly (split/corporate action) and AI veto reasons
                    if result.get("data_anomaly"):
                        st.error(f"🚨 {result['data_anomaly']}")
                    for veto_reason in (result.get("ai_veto") or []):
                        st.warning(f"⚠️ {veto_reason}")
                    if result.get("ai_upside_note"):
                        st.info(result["ai_upside_note"])

                    # Metrics row
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Current Price", f"₹{ind.get('current_price','?')}")
                    m2.metric("Ideal Entry",   f"₹{ep.get('ideal','?')}")
                    m3.metric("Stop Loss",     f"₹{result.get('stop_loss','?')}")
                    m4.metric("R:R Ratio",     f"{result.get('risk_reward_ratio','?')}")
                    m5.metric("Confidence",    f"{conf}/100")

                    st.markdown(confidence_bar(conf), unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)

                    col_left, col_right = st.columns([1, 2])
                    with col_left:
                        st.markdown('<div class="section-header">Price Levels</div>', unsafe_allow_html=True)
                        for label, val, cls in [
                            ("Entry (Ideal)", f"₹{ep.get('ideal','?')}", "price-val-blue"),
                            ("Entry Zone",    f"₹{ep.get('range_low','?')} – ₹{ep.get('range_high','?')}", "price-val-white"),
                            ("Target 1",      f"₹{tp.get('T1','?')}", "price-val-green"),
                            ("Target 2",      f"₹{tp.get('T2','?')}", "price-val-green"),
                            ("Target 3",      f"₹{tp.get('T3','?')}", "price-val-green"),
                            ("Stop Loss",     f"₹{result.get('stop_loss','?')}", "price-val-red"),
                        ]:
                            st.markdown(
                                f'<div class="price-row">'
                                f'<span class="price-label">{label}</span>'
                                f'<span class="{cls}">{val}</span></div>',
                                unsafe_allow_html=True
                            )
                        st.markdown('<div class="section-header" style="margin-top:16px">Alert Triggers</div>', unsafe_allow_html=True)
                        buy_alert  = ap.get("buy_alert_at")
                        sell_alert = ap.get("sell_alert_at")
                        stop_alert = ap.get("stop_alert_at")
                        st.markdown(
                            f'<div class="price-row">'
                            f'<span class="price-label">🔔 Buy Alert</span>'
                            f'<span class="price-val-blue">₹{buy_alert if buy_alert is not None else "—"}</span>'
                            f'</div>'
                            f'<div class="price-row">'
                            f'<span class="price-label">📤 Sell Alert</span>'
                            f'<span class="price-val-green">₹{sell_alert if sell_alert is not None else "—"}</span>'
                            f'</div>'
                            f'<div class="price-row">'
                            f'<span class="price-label">🛑 Stop Alert</span>'
                            f'<span class="price-val-red">₹{stop_alert if stop_alert is not None else "—"}</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                        st.markdown('<div class="section-header" style="margin-top:16px">Indicators</div>', unsafe_allow_html=True)
                        for label, val in [
                            ("RSI",     ind.get("rsi", "?")),
                            ("MACD",    ind.get("macd_crossover", "?")),
                            ("Volume",  f"{ind.get('volume_ratio','?')}x avg"),
                            ("ADX",     f"{ind.get('adx','?')} ({ind.get('trend_strength','?')})"),
                            ("Pattern", ind.get("candle_pattern", "none")),
                        ]:
                            st.markdown(
                                f'<div class="price-row">'
                                f'<span class="price-label">{label}</span>'
                                f'<span class="price-val-white">{val}</span></div>',
                                unsafe_allow_html=True
                            )

                    with col_right:
                        fig = candlestick_chart(sym_clean)
                        if fig:
                            st.plotly_chart(fig, width="stretch",
                                            key=f"analyze_chart_{sym_clean}_{style}")

                    # Key signals
                    st.markdown('<div class="section-header">Key Signals</div>', unsafe_allow_html=True)
                    signals_html = "".join([f'<span class="signal-pill">✦ {s}</span>' for s in result.get("key_signals", [])])
                    st.markdown(signals_html, unsafe_allow_html=True)
                    st.markdown(
                        f'<div style="font-size:12px;color:#6e7681;margin-top:10px">'
                        f'<b style="color:#8b949e">Exit if:</b> {result.get("exit_trigger","?")}</div>',
                        unsafe_allow_html=True
                    )
                    st.markdown("<br>", unsafe_allow_html=True)

                    # Explainability
                    with st.expander("Why this pick? (explainability)"):
                        expl = explain_pick(result)
                        rows = ""
                        for k, v in expl:
                            rows += f"- **{k}:** {v}  \n"
                        st.markdown(rows)
                    # Action buttons
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("📨 Send Telegram Alert", key="analyze_tel"):
                            from alerts import send_buy_alert
                            send_buy_alert(result)
                            st.success("Alert sent!")
                    with b2:
                        # Buyer-safe order: live-stamp price, cash/notional cap,
                        # reward/risk floor, style-appropriate target.
                        try:
                            from portfolio import add_holding
                        except Exception:
                            add_holding = None
                        price_for_pos = ep.get('ideal', 0) or ind.get('current_price', 0)
                        atr_for_pos = ind.get('atr')
                        cash = st.session_state.get('cash_per_trade', 100000)
                        order = build_buy_order(sym_clean, price_for_pos, atr_for_pos, cash,
                                                tp=tp, stop_rc=result.get('stop_loss'), style=style)
                        qty_suggest = int(order.get('qty', 0))
                        price_use = order.get('price') or price_for_pos
                        stop_suggest = order.get('stop') or result.get('stop_loss', 0)
                        target_use = order.get('target') or tp.get('T1', 0)
                        live_txt = f" • live ₹{order.get('live_price')}" if order.get('live_price') else ''
                        st.markdown(
                            f"<div style='font-size:12px;color:#8b949e'>"
                            f"Suggested: qty {qty_suggest} • stop ₹{stop_suggest} • "
                            f"target ₹{order.get('target','?')} • R:R {order.get('rr','?')}{live_txt}"
                            f"</div>", unsafe_allow_html=True)
                        try:
                            from signal_logger import log_signal
                            log_signal(sym_clean, price_use, atr=atr_for_pos, qty=qty_suggest,
                                       stop_loss=stop_suggest, source='analyze_display')
                        except Exception:
                            pass
                        if not order.get('ok'):
                            st.warning(f"⚠️ Add blocked: {order.get('reason')}")
                        if st.button("➕ Add to Portfolio", key='analyze_add', disabled=not order.get('ok')):
                            from datetime import date
                            if add_holding and order.get('ok'):
                                from portfolio import last_add_failures
                                ok = add_holding(sym_clean, price_use, qty_suggest,
                                                 str(date.today()), target_use, stop_suggest,
                                                 style, cash=cash)
                                if ok:
                                    try:
                                        from signal_logger import log_signal
                                        log_signal(sym_clean, price_use, atr=atr_for_pos, qty=qty_suggest,
                                                   stop_loss=stop_suggest, source='analyze')
                                    except Exception:
                                        pass
                                    st.success(f"Added {sym_clean}!")
                                else:
                                    reasons = "  \n".join(f"- {r}" for r in last_add_failures) or "Unknown validation error"
                                    st.error(f"❌ Could not add {sym_clean}:\n{reasons}")
                            else:
                                st.error(f"❌ Cannot add {sym_clean}: {order.get('reason') or 'invalid order'}")
                else:
                    st.error("Analysis failed. Check your API key in .env")
            except Exception as e:
                st.error(f"Error: {e}")
    elif run:
        st.warning("Enter a stock symbol first.")

# ─────────────────────────────────────────────
# Dynamic report pages (show JSON reports if present)
# ─────────────────────────────────────────────
elif "Backtests" in page:
    st.markdown('<div class="page-title">Backtest Report</div>', unsafe_allow_html=True)
    if os.path.exists('portfolio_backtest_report.json'):
        with open('portfolio_backtest_report.json') as f:
            rep = json.load(f)
        st.json(rep)
    else:
        st.info('No backtest report found. Run the backtest to generate portfolio_backtest_report.json')

elif "Tuning Results" in page:
    st.markdown('<div class="page-title">Tuning Walk‑Forward Results</div>', unsafe_allow_html=True)
    if os.path.exists('tuning_walkforward.json'):
        with open('tuning_walkforward.json') as f:
            rep = json.load(f)
        st.json(rep)
    else:
        st.info('No tuning results found. Run the tuner to generate tuning_walkforward.json')

elif "Buy Suggestions" in page:
    st.markdown('<div class="page-title">Buy Suggestions</div>', unsafe_allow_html=True)
    if os.path.exists('buy_suggestions.json'):
        with open('buy_suggestions.json') as f:
            rep = json.load(f)
        st.dataframe(rep)
    else:
        st.info('No buy suggestions found. Use portfolio.py --suggest-buys to generate buy_suggestions.json')

elif "Screener Results" in page:
    st.markdown('<div class="page-title">Screener Results</div>', unsafe_allow_html=True)
    if not os.path.exists('screener_results.json'):
        st.info('No screener results found. Run the screener to generate screener_results.json')
    else:
        with open('screener_results.json') as f:
            rep = json.load(f)
        scan_time = rep.get('scan_time', '')
        results = rep.get('results', {})
        st.markdown(f'<div class="page-sub">Scan time: {scan_time}</div>', unsafe_allow_html=True)

        styles = list(results.keys())
        if not styles:
            st.info('No results in screener_results.json')
        else:
            tab_items = []
            for s in styles:
                tab_items.append(s.capitalize())
            tabs = st.tabs(tab_items)
            for tab_idx, (tab_obj, style) in enumerate(zip(tabs, styles)):
                with tab_obj:
                    stocks = results.get(style, [])
                    if not stocks:
                        st.info(f'No picks for {style}')
                        continue
                    # Option: require weekly/multi-timeframe confirmation
                    require_weekly = st.checkbox("Require weekly confirmation", value=True, key=f"require_weekly_{style}_{tab_idx}")
                    if require_weekly:
                        display_stocks = [s for s in stocks if s.get('multi_tf_confirm')]
                    else:
                        display_stocks = stocks
                    # Sorting controls for screener
                    sort_opt = st.selectbox("Sort by", ["Score","RSI","Vol Ratio","Price","ATR"], key=f"scr_sort_{style}_{tab_idx}")
                    sort_dir = st.radio("Direction", ["Descending","Ascending"], index=0, horizontal=True, key=f"scr_dir_{style}_{tab_idx}")
                    def _scr_sort_val(item):
                        try:
                            if sort_opt == "Score":
                                return item.get('ensemble_score', item.get('score', 0)) or 0
                            if sort_opt == "RSI":
                                return item.get('rsi', 0) or 0
                            if sort_opt == "Vol Ratio":
                                return item.get('volume_ratio', 0) or 0
                            if sort_opt == "Price":
                                return item.get('current_price', 0) or 0
                            if sort_opt == "ATR":
                                return item.get('atr', 0) or 0
                        except Exception:
                            return 0
                    display_stocks = sorted(display_stocks, key=_scr_sort_val, reverse=(sort_dir=="Descending"))
                    if not display_stocks:
                        st.info('No picks match the weekly-confirmation filter')
                        continue
                    # Summary metrics
                    avg_score = int(sum(s.get('ensemble_score',0) for s in display_stocks)/len(display_stocks))
                    avg_rsi = int(sum(s.get('rsi',0) for s in display_stocks)/len(display_stocks))
                    col1, col2, col3 = st.columns(3)
                    col1.metric('Picks', len(stocks))
                    col2.metric('Avg Score', f"{avg_score}/100")
                    col3.metric('Avg RSI', f"{avg_rsi}")
                    n_buy = sum(1 for s in stocks if s.get('recommendation') == 'BUY')
                    n_wl = len(stocks) - n_buy
                    st.caption(
                        f"🧭 {n_buy} BUY · {n_wl} WATCHLIST — WATCHLIST rows are REJECTED candidates "
                        f"(shown with failure reasons for review). Only BUY is actionable."
                    )

                    # table view
                    rows = []
                    for s in display_stocks:
                        rows.append({
                            'Symbol': s.get('symbol',''),
                            'Decision': s.get('recommendation',''),
                            'Price': s.get('current_price',''),
                            'RSI': s.get('rsi',''),
                            'Vol Ratio': s.get('volume_ratio',''),
                            'Score': s.get('ensemble_score', s.get('score','')),
                            'Why not qualified': "; ".join(s.get('eligibility_failures', [])) or "",
                        })
                    import pandas as _pd
                    df = _pd.DataFrame(rows)
                    st.dataframe(df, width="stretch", hide_index=True)

                    # detailed cards
                    for i, s in enumerate(display_stocks, 1):
                        rec_txt = s.get('recommendation', 'WATCHLIST')
                        with st.expander(f"{i}. {s.get('symbol')} — Score {s.get('ensemble_score')} [{rec_txt}]"):
                            left, right = st.columns([2,1])
                            with left:
                                st.markdown(f"**Price:** ₹{s.get('current_price')}   •   **RSI:** {s.get('rsi')}", unsafe_allow_html=True)
                                st.markdown(rec_badge(rec_txt), unsafe_allow_html=True)
                                _fails = s.get('eligibility_failures', [])
                                if _fails:
                                    st.warning("⚠️ Rejected: " + "; ".join(_fails))
                                st.markdown(f"**Signals:** {', '.join(s.get('signals',[]))}")
                                # multi-timeframe confirmation badge
                                mt = s.get('multi_tf_confirm', False)
                                mt_text = 'Yes' if mt else 'No'
                                st.markdown(f"**Weekly Confirmed:** {mt_text}")
                                # dead-cat bounce / bull-trap warning
                                dcw = dead_cat_warning(s)
                                if dcw:
                                    st.error(dcw)
                                st.markdown("---")
                                st.markdown("**Buffett score & reasons**")
                                st.write(s.get('buffett_score'), s.get('buffett_reasons'))
                                st.markdown("**Jhunjhunwala score & reasons**")
                                st.write(s.get('rakesh_score'), s.get('rakesh_reasons'))
                                # Explainability: show breakdown and top signals
                                with st.expander("Why this pick? (explainability)"):
                                    expl = explain_pick(s)
                                    rows = ""
                                    for k, v in expl:
                                        rows += f"- **{k}:** {v}  \n"
                                    st.markdown(rows)
                            with right:
                                st.metric('Ensemble', f"{s.get('ensemble_score')}/100")
                                st.metric('Volume ratio', s.get('volume_ratio'))
                                add_key = f"screener_add_{style}_{i}"
                                # buyer-safe suggestion
                                try:
                                    from portfolio import add_holding
                                except Exception:
                                    add_holding = None
                                price_for_pos = s.get('current_price')
                                atr_for_pos = s.get('atr')
                                cash = st.session_state.get('cash_per_trade', 100000)
                                order = build_buy_order(s.get('symbol'), price_for_pos, atr_for_pos, cash,
                                        tp={'T1': s.get('target'), 'T2': s.get('target')}, stop_rc=s.get('stop_loss'), style=style)
                                qty_suggest = int(order.get('qty', 0))
                                price_use = order.get('price') or price_for_pos
                                stop_suggest = order.get('stop') or s.get('stop_loss') or 0
                                target_use = order.get('target') or s.get('target', 0)
                                st.markdown(
                                    f"<div style='font-size:12px;color:#8b949e'>"
                                    f"Suggested: qty {qty_suggest} • stop ₹{stop_suggest} • target ₹{order.get('target','?')} • R:R {order.get('rr','?')}"
                                    f"</div>", unsafe_allow_html=True)
                                try:
                                    from signal_logger import log_signal
                                    log_signal(s.get('symbol'), price_use, atr=atr_for_pos, qty=qty_suggest, stop_loss=stop_suggest, source='screener_display')
                                except Exception:
                                    pass
                                if not order.get('ok'):
                                    st.warning(f"⚠️ Add blocked: {order.get('reason')}")
                                not_buy = s.get('recommendation') != 'BUY'
                                if require_weekly and not s.get('multi_tf_confirm'):
                                    st.button('Add to Portfolio (weekly not confirmed)', disabled=True, key=add_key)
                                elif not_buy:
                                    _rf = "; ".join(s.get('eligibility_failures', [])) or 'no failed checks listed'
                                    st.button('Add to Portfolio (WATCHLIST — not a confirmed BUY)', disabled=True,
                                              key=add_key)
                                    st.caption(f"Rejected: {_rf}")
                                elif st.button('Add to Portfolio', key=add_key, disabled=not order.get('ok')):
                                    from datetime import date
                                    if add_holding and order.get('ok'):
                                        from portfolio import last_add_failures
                                        ok = add_holding(s.get('symbol'), price_use, qty_suggest,
                                                         str(date.today()), target_use, stop_suggest, style, cash=cash)
                                        if ok:
                                            try:
                                                from signal_logger import log_signal
                                                log_signal(s.get('symbol'), price_use, atr=atr_for_pos, qty=qty_suggest, stop_loss=stop_suggest, source='screener')
                                            except Exception:
                                                pass
                                            st.success(f"Added {s.get('symbol')} to portfolio")
                                        else:
                                            reasons = "  \n".join(f"- {r}" for r in last_add_failures) or "Unknown validation error"
                                            st.error(f"❌ Could not add {s.get('symbol')}:\n{reasons}")


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
        source  = r.get("decision_source", "AI")

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
            f"Urgency: {urgency}  •  P&L: {pnl:+.2f}%  •  {source}",
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
                f'<div style="font-size:11px;color:#6e7681;margin-bottom:6px">{source.upper()} REASONING</div>'
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
