"""
ai_analyst.py — AI Analysis Engine
Uses Groq (primary, free) + Gemini (fallback) with rate limit handling
"""

import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from indicators import IndicatorEngine
import warnings
warnings.filterwarnings("ignore")

load_dotenv()


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
                print("  AI Engine: Groq (llama-3.3-70b)")
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
            "Add GROQ_API_KEY or OPENROUTER_API_KEY or GEMINI_API_KEY to .env"
        )

    def _call_ai(self, prompt: str, retries: int = 3):
        """Call AI with automatic retry on rate limit."""
        for attempt in range(retries):
            try:
                if self.engine_name == "groq":
                    response = self.client.chat.completions.create(
                        model       = "llama-3.3-70b-versatile",
                        messages    = [{"role": "user", "content": prompt}],
                        temperature = 0.3,
                        max_tokens  = 1000,
                    )
                    return response.choices[0].message.content.strip()
                    
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

LEVELS:
- Resistance: Rs.{ind['resistance_1']} / Rs.{ind['resistance_2']}
- Support: Rs.{ind['support_1']} / Rs.{ind['support_2']}
- 52W High: Rs.{ind['high_52w']} | Low: Rs.{ind['low_52w']}
- Overall: {ind['bull_signal_count']}/7 bullish — {ind['overall_signal'].upper()}

Style: {style.upper()}
{"Intraday: tight SL, same-day exit, focus ATR and volume." if style=="intraday" else ""}
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

    def analyze_stock(self, symbol: str, style: str):
        engine = IndicatorEngine(
            symbol if ".NS" in symbol else symbol + ".NS"
        )
        if not engine.fetch():
            return None
        ind = engine.compute_all()
        if not ind:
            return None

        prompt   = self.build_prompt(ind, style)
        raw_text = self._call_ai(prompt)
        if not raw_text:
            return None

        try:
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()
            start    = raw_text.find("{")
            end      = raw_text.rfind("}") + 1
            if start == -1 or end == 0:
                print(f"  No JSON found in response for {symbol}")
                return None
            raw_text          = raw_text[start:end]
            result            = json.loads(raw_text)
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
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()
            start    = raw_text.find("{")
            end      = raw_text.rfind("}") + 1
            if start == -1 or end == 0:
                return None
            raw_text          = raw_text[start:end]
            result            = json.loads(raw_text)
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
            print(f"\n  Analyzing {len(stocks)} {style} picks with AI "
                  f"({self.engine_name})...")
            style_results = []

            for i, stock in enumerate(stocks, 1):
                symbol = stock["yf_symbol"]
                print(f"    [{i}/{len(stocks)}] {stock['symbol']}...",
                      end=" ", flush=True)
                try:
                    result = self.analyze_stock(symbol, style)
                    if result:
                        if result.get("recommendation") == "BUY":
                            style_results.append(result)
                            print(f"BUY (confidence: "
                                  f"{result.get('confidence_score')})")
                        else:
                            print(f"{result.get('recommendation', '?')} — skipped")
                    else:
                        print("failed")
                except Exception as e:
                    print(f"error — {str(e)[:60]}")

                # Save progress after every stock
                try:
                    progress = {
                        "date":     self.analysis_date,
                        "analysis": {**all_analysis, style: style_results}
                    }
                    with open("ai_analysis_progress.json", "w") as f:
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
        temp_file = "ai_analysis_temp.json"
        final_file= "ai_analysis.json"
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