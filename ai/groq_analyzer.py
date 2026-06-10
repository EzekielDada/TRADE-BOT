"""Groq-backed first-pass headline sentiment analysis."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from config import Settings
from models import AIAnalysis, SentimentSnapshot
from utils import clamp, minutes_from_now, safe_json_loads, with_retry

try:
    from groq import AsyncGroq
except ImportError:  # pragma: no cover - optional dependency.
    AsyncGroq = None  # type: ignore[assignment]


SYSTEM_PROMPT = (
    "You are a professional financial analyst specializing in crypto and equity markets. "
    "You analyze news sentiment with precision. Always respond with valid JSON only. "
    "No preamble, no explanation, no markdown."
)

USER_PROMPT = """Analyze these headlines about {asset}. Return ONLY
a JSON object with these exact fields:
{{
  "sentiment_score": <float 0.0 to 1.0, where 0.0 is extremely bearish and 1.0 is extremely bullish>,
  "confidence": <float 0.0 to 1.0>,
  "key_themes": <list of 3 most important themes as strings>,
  "risk_flags": <list of strings describing any red flags>,
  "summary": <one sentence explanation>
}}
Headlines: {headlines}"""


@dataclass(slots=True)
class CacheEntry:
    """Cached Groq result."""

    analysis: AIAnalysis
    expires_at: datetime


class GroqAnalyzer:
    """Analyze headline sentiment with Groq's hosted Llama model."""

    def __init__(self, settings: Settings) -> None:
        """Create a Groq analyzer."""

        self.settings = settings
        self._client = AsyncGroq(api_key=settings.groq_api_key) if settings.groq_api_key and AsyncGroq else None
        self._cache: dict[str, CacheEntry] = {}
        self._request_times: deque[datetime] = deque()
        self._rate_lock = asyncio.Lock()

    async def analyze(self, asset: str, snapshot: SentimentSnapshot) -> AIAnalysis | None:
        """Analyze headline sentiment for an asset, or return None if unavailable."""

        cache_key = f"{asset}:{'|'.join(snapshot.headlines[:12])}"
        cached = self._cache.get(cache_key)
        if cached and cached.expires_at > datetime.now(UTC):
            return cached.analysis
        if not self._client:
            return None

        prompt = USER_PROMPT.format(asset=asset, headlines=snapshot.headlines[:20] or ["No recent headlines"])

        async def _send(clean_prompt: bool = False) -> AIAnalysis:
            await self._respect_rate_limit(max_requests=30)
            user_content = prompt if not clean_prompt else f"{prompt}\nRespond with a compact JSON object only."
            response = await self._client.chat.completions.create(
                model=self.settings.groq_model,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            logger.bind(ai_log=True).info(f"Groq raw response for {asset}: {content}")
            try:
                payload = safe_json_loads(content)
            except ValueError:
                if clean_prompt:
                    raise
                return await _send(clean_prompt=True)
            return self._coerce_payload(payload)

        try:
            analysis = await with_retry(lambda: _send(False), attempts=3, base_delay=1.5)
        except Exception as error:  # pragma: no cover - network dependent.
            logger.warning(f"Groq unavailable for {asset}: {error}")
            return None

        self._cache[cache_key] = CacheEntry(analysis=analysis, expires_at=minutes_from_now(self.settings.sentiment_cache_minutes))
        return analysis

    def _coerce_payload(self, payload: dict[str, Any]) -> AIAnalysis:
        """Normalize Groq response into AIAnalysis."""

        return AIAnalysis(
            source="groq",
            sentiment_score=clamp(float(payload.get("sentiment_score", 0.5)), 0.0, 1.0),
            confidence=clamp(float(payload.get("confidence", 0.0)), 0.0, 1.0),
            key_themes=[str(item) for item in payload.get("key_themes", [])][:3],
            risk_flags=[str(item) for item in payload.get("risk_flags", [])],
            summary=str(payload.get("summary", "")),
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
