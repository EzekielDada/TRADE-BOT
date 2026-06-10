"""Gemini-backed contextual trading analysis."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from config import Settings
from models import AIAnalysis, SentimentSnapshot, TechnicalSignal
from utils import clamp, minutes_from_now, safe_json_loads, with_retry

try:
    from google import genai
    from google.genai import types as genai_types
    _GENAI_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency.
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]
    _GENAI_AVAILABLE = False


PROMPT_TEMPLATE = """You are a senior quantitative analyst at a top hedge fund.
Analyze the following complete market context and provide
a trading recommendation.

Asset: {asset}
Current Price: {price}
24h Change: {change_24h}%
7d Change: {change_7d}%
RSI (14): {rsi}
MACD Signal: {macd_signal}
EMA Trend: {ema_trend}
Market Regime: {regime}
Bollinger Band Position: {bb_position}
Volume vs Average: {volume_ratio}x
ATR: {atr}

Fear & Greed Index: {fng_score} ({fng_label})
Long/Short Ratio: {ls_ratio} (above 0.65 long = overleveraged)
Funding Rate: {funding_rate}
BTC Dominance: {btc_dominance}%

Recent Headlines (last 24h):
{headlines}

Google Trends Score: {trends_score}/100

HISTORICAL EVENT CONTEXT (from pattern database):
{pattern_context}

UPCOMING KNOWN EVENTS:
{upcoming_events}

Analyze everything and return ONLY a JSON object:
{{
  "sentiment_score": <float 0.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "trade_recommendation": <"strong_buy"|"buy"|"hold"|"sell"|"strong_sell">,
  "reasoning": <2-3 sentence explanation>,
  "macro_risks": <list of macro factors that could invalidate signal>,
  "time_horizon": <"short"|"medium"|"long">,
  "key_levels": {{
    "support": <float>,
    "resistance": <float>,
    "breakout": <float>
  }},
  "pattern_influence": <explanation of how historical patterns affected this recommendation>,
  "upcoming_event_risk": <"low"|"medium"|"high"|"extreme">
}}"""


@dataclass(slots=True)
class CacheEntry:
    """Cached Gemini result."""

    analysis: AIAnalysis
    expires_at: datetime


class GeminiAnalyzer:
    """Analyze broader market context with Gemini."""

    def __init__(self, settings: Settings) -> None:
        """Create a Gemini analyzer."""

        self.settings = settings
        if settings.gemini_api_key and _GENAI_AVAILABLE:
            self._client = genai.Client(api_key=settings.gemini_api_key)
        else:
            self._client = None
        self._cache: dict[str, CacheEntry] = {}
        self._request_times: deque[datetime] = deque()
        self._rate_lock = asyncio.Lock()

    async def analyze(
        self,
        asset: str,
        snapshot: SentimentSnapshot,
        technical_signal: TechnicalSignal,
        price_context: dict[str, Any] | None = None,
    ) -> AIAnalysis | None:
        """Analyze contextual trading sentiment, or return None if unavailable."""

        price_context = price_context or {}
        cache_key = f"{asset}:{price_context.get('price')}:{'|'.join(snapshot.headlines[:10])}:{snapshot.aggregated_score}"
        cached = self._cache.get(cache_key)
        if cached and cached.expires_at > datetime.now(UTC):
            return cached.analysis
        if self._client is None:
            return None

        pattern_context = "\n".join(
            f"- {match['pattern_name']}: {match['headline']} (severity={match['severity']}, impact={match['typical_impact']})"
            for match in snapshot.pattern_matches[:10]
        ) or "No matched historical patterns."
        upcoming_events = "\n".join(
            f"- {event.get('title')} at {event.get('date')} ({event.get('country')}, impact={event.get('impact')})"
            for event in snapshot.upcoming_events[:10]
        ) or "No high-impact events scheduled."
        prompt = PROMPT_TEMPLATE.format(
            asset=asset,
            price=price_context.get("price", 0.0),
            change_24h=price_context.get("change_24h", 0.0),
            change_7d=price_context.get("change_7d", 0.0),
            rsi=technical_signal.rsi,
            macd_signal=technical_signal.macd_signal,
            ema_trend=technical_signal.trend,
            regime=price_context.get("regime", "UNKNOWN"),
            bb_position=technical_signal.bb_position,
            volume_ratio=technical_signal.metadata.get("volume_ratio", 1.0),
            atr=technical_signal.atr,
            fng_score=snapshot.fear_greed_value,
            fng_label=snapshot.fear_greed_label,
            ls_ratio=snapshot.long_short_ratio,
            funding_rate=snapshot.funding_rate,
            btc_dominance=snapshot.btc_dominance,
            headlines=snapshot.headlines[:20] or ["No recent headlines"],
            trends_score=snapshot.google_trends_score,
            pattern_context=pattern_context,
            upcoming_events=upcoming_events,
        )

        async def _send() -> AIAnalysis:
            await self._respect_rate_limit(max_requests=15)
            response = await self._client.aio.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            text = response.text or "{}"
            logger.bind(ai_log=True).info(f"Gemini raw response for {asset}: {text}")
            payload = safe_json_loads(text)
            return self._coerce_payload(payload)

        try:
            analysis = await with_retry(_send, attempts=3, base_delay=2.0)
        except Exception as error:  # pragma: no cover - network dependent.
            logger.warning(f"Gemini unavailable for {asset}: {error}")
            return None

        self._cache[cache_key] = CacheEntry(analysis=analysis, expires_at=minutes_from_now(15))
        return analysis

    def _coerce_payload(self, payload: dict[str, Any]) -> AIAnalysis:
        """Normalize Gemini response into AIAnalysis."""

        key_levels = payload.get("key_levels", {}) or {}
        return AIAnalysis(
            source="gemini",
            sentiment_score=clamp(float(payload.get("sentiment_score", 0.5)), 0.0, 1.0),
            confidence=clamp(float(payload.get("confidence", 0.0)), 0.0, 1.0),
            trade_recommendation=str(payload.get("trade_recommendation", "hold")),
            reasoning=str(payload.get("reasoning", "")),
            macro_risks=[str(item) for item in payload.get("macro_risks", [])],
            time_horizon=str(payload.get("time_horizon", "medium")),
            key_levels={
                "support": float(key_levels.get("support", 0.0)),
                "resistance": float(key_levels.get("resistance", 0.0)),
                "breakout": float(key_levels.get("breakout", 0.0)),
            },
            pattern_influence=str(payload.get("pattern_influence", "")),
            upcoming_event_risk=str(payload.get("upcoming_event_risk", "low")),
            raw_payload=payload,
        )

    async def _respect_rate_limit(self, max_requests: int) -> None:
        """Throttle requests to remain under the free-tier limit."""

        async with self._rate_lock:
            now = datetime.now(UTC)
            while self._request_times and (now - self._request_times[0]).total_seconds() >= 60:
                self._request_times.popleft()
            if len(self._request_times) >= max_requests:
                wait_seconds = 60 - (now - self._request_times[0]).total_seconds()
                await asyncio.sleep(max(wait_seconds, 0.1))
            self._request_times.append(datetime.now(UTC))
