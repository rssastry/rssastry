"""
ai_analyst.py — AI Analysis Engine
Uses Groq (primary, free) + Gemini (fallback) with rate limit handling
"""

import json
import os
import re
import time
from datetime import datetime
from dotenv import load_dotenv
from config import AI_BUY_MIN_CONFIDENCE
from indicators import IndicatorEngine
import paths
import warnings
warnings.filterwarnings("ignore")

load_dotenv()

import console
console.force_utf8_stdio()


class AIAnalyst:

    def __init__(self):
        self.analysis_date = datetime.now().strftime("%Y-%m-%d")
        self.client        = None
        self.engine_name   = None
        self._init_engine()

    def _init_engine(self):
        """Try Groq → OpenRouter → Gemini in order."""

        # Try Groq
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            try:
                from groq import Groq
                self.client      = Groq(api_key=groq_key)
                self.engine_name = "groq"
                # Groq retired llama-3.3-70b-versatile for free/developer
                # tiers on 16 Aug 2026. openai/gpt-oss-120b is available on
                # this project's key and does NOT emit reasoning blocks that
                # consume the token budget and truncate JSON output.
                # GROQ_MODEL permits an account-specific override later.
                self.groq_model  = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
                print(f"  AI Engine: Groq ({self.groq_model})")
                return
            except Exception as e:
                print(f"  Groq init failed: {e}")

        # Try OpenRouter
        or_key = os.getenv("OPENROUTER_API_KEY")
        if or_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(
                    api_key  = or_key,
                    base_url = "https://openrouter.ai/api/v1"
                )
                self.engine_name = "openrouter"
                print("  AI Engine: OpenRouter (mistral-7b free)")
                return
            except Exception as e:
                print(f"  OpenRouter init failed: {e}")

        # Try Gemini
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                self.client      = genai.GenerativeModel("gemini-1.5-flash")
                self.engine_name = "gemini"
                print("  AI Engine: Gemini 1.5 Flash")
                return
            except Exception as e:
                print(f"  Gemini init failed: {e}")

        raise ValueError(
            "No AI engine available. "
            "Set GROQ_API_KEY or OPENROUTER_API_KEY or GEMINI_API_KEY in .env "
            "(or as environment variables on Render / your deployment host)"
        )

    def _extract_json(self, text: str):
        """Robustly extract the first complete JSON object from a string.

        Handles model responses that:
          - wrap output in <thinking>...</thinking> blocks
          - prepend prose before the JSON
          - append commentary after the JSON (which may contain braces)
          - put the JSON entirely inside a <thinking> block
        Returns the parsed dict or None if no valid JSON found.
        """
        import re as _re

        if not text:
            return None

        decoder = json.JSONDecoder()

        def _scan(t: str):
            """Scan for the first valid JSON dict in a string."""
            idx = 0
            length = len(t)
            while idx < length:
                # Skip non-JSON characters
                while idx < length and t[idx] not in '{[':
                    idx += 1
                if idx >= length:
                    break
                try:
                    obj, end_idx = decoder.raw_decode(t, idx=idx)
                    if isinstance(obj, dict):
                        return obj
                    idx = end_idx
                except json.JSONDecodeError:
                    idx += 1
            return None

        # 1) Scan raw text first — this finds JSON even when embedded
        #    inside <thinking> blocks or between prose.
        result = _scan(text)
        if result is not None:
            return result

        # 2) Fallback: extract <thinking> content and scan that (some
        #    models put the JSON only inside the thinking block).
        m = _re.search(r'<(?:think|thinking|reasoning)>(.*?)</(?:think|thinking|reasoning)>',
                       text, flags=_re.DOTALL)
        if m:
            result = _scan(m.group(1))
            if result is not None:
                return result

        # 3) Fallback: strip ```json fences and scan again
        cleaned = _re.sub(r'```json\s*', '', text)
        cleaned = _re.sub(r'```\s*', '', cleaned)
        return _scan(cleaned)

    def _call_ai(self, prompt: str, retries: int = 3):
        """Call AI with automatic retry on rate limit."""
        for attempt in range(retries):
            try:
                if self.engine_name == "groq":
                    response = self.client.chat.completions.create(
                        model       = self.groq_model,
                        messages    = [{"role": "user", "content": prompt}],
                        temperature = 0.1,
                        max_tokens  = 4096,
                    )
                    content = response.choices[0].message.content.strip()
                    # The qwen3.6-27b model emits reasoning prose that can
                    # surround the JSON payload with braces in that prose.
                    # _extract_json() (used by callers) scans for the first
                    # complete, valid JSON object.
                    return content

                elif self.engine_name == "openrouter":
                    response = self.client.chat.completions.create(
                        model       = "mistralai/mistral-7b-instruct:free",
                        messages    = [{"role": "user", "content": prompt}],
                        temperature = 0.3,
                        max_tokens  = 1000,
                    )
                    return response.choices[0].message.content.strip()

                elif self.engine_name == "gemini":
                    response = self.client.generate_content(prompt)
                    return response.text.strip()

            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                    wait = 65 if attempt == 0 else 120
                    print(f"\n    Rate limit hit. Waiting {wait}s "
                          f"(attempt {attempt+1}/{retries})...")
                    time.sleep(wait)
                else:
                    print(f"\n    AI error: {err[:120]}")
                    return None
        return None

    def build_prompt(self, ind: dict, style: str) -> str:
        return f"""You are a Senior SEBI-registered Stock Market Analyst with 20 years
of experience in technical analysis and trading on NSE/BSE markets.
You follow strict Risk:Reward discipline (minimum 1:2).
Do NOT recommend BUY if the stock is still weak on recent price action, has a bearish MACD crossover, or a weak ADX trend setup unless price action and volume clearly confirm a reversal.
If the stock had a recent high-volume breakdown day and the current price has NOT reclaimed the broken swing high (or lacks a fresh MACD/EMA bullish crossover), treat it as a DEAD-CAT BOUNCE and reply \"WATCHLIST\" (not BUY) with a reduced confidence score.

Analyze this stock for {style.upper()} trading as of {self.analysis_date}:

STOCK: {ind['symbol']}
Current Price: Rs.{ind['current_price']}
Today Change: {ind['change_pct']}%

TECHNICAL INDICATORS:
- RSI(14): {ind['rsi']} (prev: {ind['rsi_prev']})
- MACD Hist: {ind['macd_hist']} | Crossover: {ind['macd_crossover']}
- EMA9: Rs.{ind['ema9']} | EMA21: Rs.{ind['ema21']} | EMA50: Rs.{ind['ema50']}
- EMA21/50 bullish rule: {'ACTIVE' if ind.get('buy_rule_passed', False) else 'NOT ACTIVE'}
- Bull rule details: {ind.get('buy_rule_reason', 'No bullish crossover confirmation yet')}
- EMA21/50 bearish rule: {'ACTIVE' if ind.get('sell_rule_passed', False) else 'NOT ACTIVE'}
- Bear rule details: {ind.get('sell_rule_reason', 'No bearish crossover confirmation yet')}
- Bollinger %B: {ind['bb_pct']} | Upper: Rs.{ind['bb_upper']} | Lower: Rs.{ind['bb_lower']}
- ATR: Rs.{ind['atr']} ({ind['atr_pct']}%)
- ADX: {ind['adx']} ({ind['trend_strength']})
- Volume: {ind['volume_ratio']}x avg | OBV: {ind['obv_trend']}
- Candle: {ind['candle_pattern']}
- Signal data as of: {ind.get('data_as_of', 'n/a')}
- Historical next-session fade check for this stretched setup: {ind.get('sig_win_pct', 'n/a')}% win over {ind.get('sig_samples', 0)} samples
- BREAKDOWN CONTEXT: recent high-volume breakdown day = {ind.get('recent_breakdown_day', False)}; crash date {ind.get('breakdown_date', 'n/a')} ({ind.get('breakdown_change_pct', 'n/a')}% on {ind.get('breakdown_volume_ratio', 'n/a')}x volume); broken swing high = Rs.{ind.get('breakdown_reclaim_level', 'n/a')}
- Reclaims broken level: {'YES' if ind.get('reclaims_breakdown_level', False) else 'NO'} | Fresh bullish trigger (MACD/EMA cross): {'YES' if ind.get('fresh_bullish_trigger', False) else 'NO'}
- Gap: {ind.get('gap_pct', 0)}% | Close-location (0=low,1=high): {ind.get('close_location', 'n/a')}
- Bounce continuation history: {ind.get('bounce_win_pct', 'n/a')}% over {ind.get('bounce_samples', 0)} samples

LEVELS:
- Resistance: Rs.{ind['resistance_1']} / Rs.{ind['resistance_2']}
- Support: Rs.{ind['support_1']} / Rs.{ind['support_2']}
- 52W High: Rs.{ind['high_52w']} | Low: Rs.{ind['low_52w']}
- Overall: {ind['bull_signal_count']}/7 bullish — {ind['overall_signal'].upper()}

Style: {style.upper()}
{"Intraday: tight SL, same-day exit, focus ATR and volume. The signal is based on the LAST COMPLETED bar (see data_as_of). If you are entering on a LATER session, the prior session's momentum may already be spent — require fresh pre-open/first-hour confirmation and never chase a gap." if style=="intraday" else ""}
{"Swing: 2-5 day hold, EMA crossovers, wider stops." if style=="swing" else ""}
{"Positional: 1-4 week hold, trend alignment, EMA50/200." if style=="positional" else ""}

Reply ONLY with valid JSON, no text outside it:
{{
  "symbol": "{ind['symbol']}",
  "trading_style": "{style}",
  "recommendation": "BUY or HOLD or SELL",
  "confidence_score": <0-100>,
  "analysis_summary": "<2-3 sentences>",
  "entry_price": {{
    "ideal": <float>,
    "range_low": <float>,
    "range_high": <float>
  }},
  "target_prices": {{
    "T1": <float>,
    "T2": <float>,
    "T3": <float>
  }},
  "stop_loss": <float>,
  "risk_reward_ratio": "<e.g. 1:2.5>",
  "hold_duration": "<e.g. Same day / 2-3 days / 1-2 weeks>",
  "risk_level": "Low or Medium or High",
  "key_signals": ["<signal1>", "<signal2>", "<signal3>"],
  "exit_trigger": "<condition to exit>",
  "alert_on_price": {{
    "buy_alert_at": <float>,
    "sell_alert_at": <float>,
    "stop_alert_at": <float>
  }}
}}"""

    def build_portfolio_prompt(self, symbol, ind, buy_price,
                                buy_date, days_held,
                                original_target, original_sl) -> str:
        current = ind["current_price"]
        pnl_pct = ((current - buy_price) / buy_price) * 100
        return f"""You are a Senior Portfolio Risk Manager.

HOLDING: {symbol}
Bought: Rs.{buy_price} on {buy_date} | Days held: {days_held}
Current: Rs.{current} | P&L: {pnl_pct:+.2f}%
Original Target: Rs.{original_target} | Original SL: Rs.{original_sl}

TECHNICALS:
- RSI: {ind['rsi']} | MACD: {ind['macd_hist']} ({ind['macd_crossover']})
- EMA9/21/50: {ind['ema9']}/{ind['ema21']}/{ind['ema50']}
- Volume: {ind['volume_ratio']}x | OBV: {ind['obv_trend']}
- ADX: {ind['adx']} | Signal: {ind['overall_signal']} ({ind['bull_signal_count']}/7)
- Support: Rs.{ind['support_1']} | Resistance: Rs.{ind['resistance_1']}

Reply ONLY with valid JSON:
{{
  "symbol": "{symbol}",
  "action": "HOLD or PARTIAL_SELL or FULL_SELL or ADD_MORE",
  "urgency": "Immediate or This week or No rush",
  "reasoning": "<2-3 sentences>",
  "revised_target": <float>,
  "revised_stop_loss": <float>,
  "pnl_percent": {round(pnl_pct, 2)},
  "risk_flag": "None or Trailing SL hit or Sector weakness or Broader market risk",
  "action_price": <float>
}}"""

    def _compute_deterministic_levels(self, ind: dict, style: str) -> dict:
        """Compute entry, target, and stop-loss deterministically from ATR.

        AI explains a setup; code calculates execution levels.
        """
        from config import ATR_MULT, TARGET_ATR_MULT

        price = ind.get("current_price") or ind.get("open_price") or 0
        atr = ind.get("atr") or 0

        if price <= 0 or atr <= 0:
            return {
                "entry_price": {"ideal": price, "range_low": price, "range_high": price},
                "target_prices": {"T1": price, "T2": price, "T3": price},
                "stop_loss": price,
                "risk_reward_ratio": "N/A",
            }

        atr_mult = ATR_MULT.get(style, 3.0)
        target_mult = TARGET_ATR_MULT.get(style, 5.0)

        stop_distance = atr * atr_mult
        target_distance = atr * target_mult

        entry = price
        stop = round(max(0.0, entry - stop_distance), 2)
        t1 = round(entry + target_distance * 0.5, 2)
        t2 = round(entry + target_distance, 2)
        t3 = round(entry + target_distance * 1.5, 2)

        risk = entry - stop
        reward = t2 - entry
        rr = f"1:{reward / risk:.1f}" if risk > 0 else "N/A"
        # The first target (T1) is the most realistic same-day goal. Report its
        # true ratio separately, because the headline ratio is T2-based and can
        # overstate near-term reward (e.g. 1:2.0 at T2 but only 1:1.0 at T1).
        reward_t1 = t1 - entry
        rr_t1 = f"1:{reward_t1 / risk:.1f}" if risk > 0 else "N/A"

        return {
            "entry_price": {
                "ideal": round(entry, 2),
                "range_low": round(entry * 0.99, 2),
                "range_high": round(entry * 1.01, 2),
            },
            "target_prices": {"T1": t1, "T2": t2, "T3": t3},
            "stop_loss": stop,
            "risk_reward_ratio": rr,
            "risk_reward_t1": rr_t1,
        }

    def analyze_stock(self, symbol: str, style: str, indicator_snapshot: dict = None):
        # Use the exact snapshot that earned the candidate its ranking. A fresh
        # fetch here can create a stale-data mismatch with the screener.
        if indicator_snapshot is not None:
            ind = dict(indicator_snapshot)
        else:
            engine = IndicatorEngine(
                symbol if ".NS" in symbol else symbol + ".NS"
            )
            if not engine.fetch():
                return None
            ind = engine.compute_all()
        if not ind:
            return None

        # Corporate-action data anomaly (split/bonus discontinuity): refuse to
        # produce levels or an AI verdict on a price series that is internally
        # inconsistent (HINDCOPPER 2026-08-31: 1037.4 vs 525.3 on the same day).
        anomaly = ind.get("data_anomaly", "") or ""
        if anomaly:
            print(f"  ⚠ {symbol}: {anomaly}")
            return {
                "symbol":           symbol,
                "trading_style":    style,
                "recommendation":   "WATCHLIST",
                "confidence_score": 0,
                "analysis_summary": f"Analysis blocked — {anomaly}",
                "key_signals":      ["Data integrity issue — no signal generated"],
                "exit_trigger":     "N/A",
                "data_anomaly":     anomaly,
                "indicators":       ind,
                "analyzed_at":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        prompt   = self.build_prompt(ind, style)
        raw_text = self._call_ai(prompt)
        if not raw_text:
            return None

        try:
            result = self._extract_json(raw_text)
            if result is None:
                print(f"  No JSON found in response for {symbol}")
                return None

            # Override AI-generated execution levels with deterministic ATR-based levels.
            # AI explains a setup; code calculates execution levels.
            deterministic = self._compute_deterministic_levels(ind, style)
            result["entry_price"] = deterministic["entry_price"]
            result["target_prices"] = deterministic["target_prices"]
            result["stop_loss"] = deterministic["stop_loss"]
            result["risk_reward_ratio"] = deterministic["risk_reward_ratio"]
            result["levels_source"] = "deterministic_atr"

            result["indicators"]  = ind
            result["analyzed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return result
        except Exception as e:
            print(f"  JSON parse error for {symbol}: {e}")
            return None

    def analyze_portfolio_holding(self, symbol, buy_price,
                                   buy_date, original_target,
                                   original_sl):
        engine = IndicatorEngine(
            symbol if ".NS" in symbol else symbol + ".NS"
        )
        if not engine.fetch():
            return None
        ind = engine.compute_all()
        if not ind:
            return None

        from datetime import date
        try:
            bd   = datetime.strptime(buy_date, "%Y-%m-%d").date()
            days = (date.today() - bd).days
        except Exception:
            days = 0

        prompt   = self.build_portfolio_prompt(
            symbol, ind, buy_price, buy_date,
            days, original_target, original_sl
        )
        raw_text = self._call_ai(prompt)
        if not raw_text:
            return None

        try:
            result = self._extract_json(raw_text)
            if result is None:
                return None
            result["indicators"]  = ind
            result["analyzed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return result
        except Exception as e:
            print(f"  JSON parse error for {symbol}: {e}")
            return None

    def _clean_for_json(self, obj):
        """Remove ohlcv_30d from indicators to avoid Timestamp serialization errors."""
        if isinstance(obj, dict):
            return {
                k: self._clean_for_json(v)
                for k, v in obj.items()
                if k != "ohlcv_30d"
            }
        elif isinstance(obj, list):
            return [self._clean_for_json(i) for i in obj]
        else:
            return obj

    def analyze_top_picks(self, screener_results: dict,
                           delay_seconds: float = 12.0) -> dict:
        all_analysis = {}

        for style, stocks in screener_results.items():
            # A style that can never BUY on daily bars (intraday) needs no LLM
            # second opinion — the deterministic screener output is the whole
            # story and every LLM call there is pure token spend. Skip it.
            from config import (AI_SKIP_POLICY_DISABLED_STYLES,
                                ALLOW_DAILY_BAR_INTRADAY_BUY)
            if (AI_SKIP_POLICY_DISABLED_STYLES and style == "intraday"
                    and not ALLOW_DAILY_BAR_INTRADAY_BUY):
                print(f"\n  Skipping {style} AI analysis (policy-disabled for "
                      f"BUY on daily bars — deterministic WATCHLIST only).")
                all_analysis[style] = []
                continue

            print(f"\n  Analyzing {len(stocks)} {style} picks with AI "
                  f"({self.engine_name})...")
            style_results = []

            for i, stock in enumerate(stocks, 1):
                symbol = stock["yf_symbol"]
                print(f"    [{i}/{len(stocks)}] {stock['symbol']}...",
                      end=" ", flush=True)
                try:
                    result = self.analyze_stock(symbol, style, indicator_snapshot=stock)
                    if result:
                        result["ai_recommendation"] = result.get("recommendation", "UNKNOWN")
                        decision = stock.get("selection_decision", "WATCHLIST")
                        ai_rec   = result.get("ai_recommendation", "UNKNOWN")
                        ai_conf  = float(result.get("confidence_score", 0) or 0)
                        base_fails = list(stock.get("eligibility_failures", []))

                        # ── AI as a real second opinion (veto) ──────────────
                        # For a STRONG recommendation engine the AI can only
                        # downgrade, never upgrade: a deterministic BUY is only
                        # actionable if the AI agrees AND has enough conviction.
                        veto = []
                        if result.get("data_anomaly"):
                            decision = "WATCHLIST"
                            veto.append(result["data_anomaly"])
                        elif decision == "BUY":
                            if ai_rec in ("SELL", "HOLD"):
                                decision = "WATCHLIST"
                                veto.append(f"AI veto: AI says {ai_rec}, not a buy")
                            elif ai_rec == "UNKNOWN":
                                decision = "WATCHLIST"
                                veto.append("AI veto: no clear AI read (UNKNOWN)")
                            elif ai_conf < AI_BUY_MIN_CONFIDENCE:
                                decision = "WATCHLIST"
                                veto.append(
                                    f"AI conviction too low for a BUY "
                                    f"({ai_conf:.0f}/100 < {AI_BUY_MIN_CONFIDENCE})"
                                )
                        if ai_rec == "BUY" and ai_conf >= AI_BUY_MIN_CONFIDENCE and decision != "BUY":
                            result["ai_upside_note"] = (
                                f"AI sees a BUY ({ai_conf:.0f}/100) but the deterministic "
                                f"gate has NOT passed — WATCHLIST only."
                            )

                        result["recommendation"] = decision
                        result["selection_decision"] = decision
                        result["ai_veto"] = veto
                        result["eligibility_failures"] = base_fails + veto
                        result["analysis_status"] = "complete"
                        if result.get("recommendation") in {"BUY", "WATCHLIST"}:
                            style_results.append(result)
                            print(f"{result['recommendation']} (AI: "
                                  f"{result.get('ai_recommendation')}, confidence: "
                                  f"{result.get('confidence_score')})")
                        else:
                            print(f"{result.get('recommendation', '?')} — skipped")
                    else:
                        style_results.append({
                            **stock,
                            "recommendation": stock.get("selection_decision", "WATCHLIST"),
                            "analysis_status": "failed",
                            "analysis_error": "AI analysis returned no usable response",
                        })
                        print("failed")
                except Exception as e:
                    style_results.append({
                        **stock,
                        "recommendation": stock.get("selection_decision", "WATCHLIST"),
                        "analysis_status": "failed",
                        "analysis_error": str(e)[:200],
                    })
                    print(f"error — {str(e)[:60]}")

                # Save progress after every stock
                try:
                    progress = {
                        "date":     self.analysis_date,
                        "analysis": {**all_analysis, style: style_results}
                    }
                    with open(paths.path("ai_analysis_progress.json"), "w") as f:
                        json.dump(self._clean_for_json(progress), f, indent=2, default=str)
                except Exception:
                    pass

                if i < len(stocks):
                    time.sleep(delay_seconds)

            style_results.sort(
                key=lambda x: x.get("confidence_score", 0),
                reverse=True
            )
            all_analysis[style] = style_results[:10]

        # Write to temp file first, rename only when fully complete
        output    = {"date": self.analysis_date, "analysis": all_analysis}
        temp_file = paths.path("ai_analysis_temp.json")
        final_file= paths.path("ai_analysis.json")
        try:
            clean_output = self._clean_for_json(output)
            with open(temp_file, "w") as f:
                json.dump(clean_output, f, indent=2, default=lambda o: str(o))
            if os.path.exists(final_file):
                os.remove(final_file)
            os.rename(temp_file, final_file)
            print("\n  AI analysis saved to ai_analysis.json")
        except Exception as e:
            print(f"\n  Failed to save: {e}")

        return all_analysis


if __name__ == "__main__":
    analyst = AIAnalyst()
    print("Testing on RELIANCE (swing)...")
    result = analyst.analyze_stock("RELIANCE.NS", "swing")
    if result:
        print(json.dumps(
            {k: v for k, v in result.items() if k != "indicators"},
            indent=2
        ))
    else:
        print("Test failed — check API keys in .env")