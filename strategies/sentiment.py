"""Sentiment data aggregation."""

from __future__ import annotations

import asyncio

from data.news_data import NewsDataService
from models import SentimentSnapshot
from utils import clamp


class SentimentAggregator:
    """Aggregate external sentiment and social context into one snapshot."""

    def __init__(self, news_service: NewsDataService) -> None:
        """Create the sentiment aggregator."""

        self.news_service = news_service

    async def build_snapshot(self, asset: str, volume_anomaly: float | None = None) -> SentimentSnapshot:
        """Fetch and normalize sentiment inputs for one asset."""

        headlines, fear_greed, bybit_sentiment, google_trends, btc_dominance, upcoming_events = await asyncio.gather(
            self.news_service.fetch_asset_headlines(asset),
            self.news_service.fetch_fear_and_greed(),
            self.news_service.fetch_bybit_sentiment(asset),
            self.news_service.fetch_google_trends(asset),
            self.news_service.fetch_btc_dominance(),
            self.news_service.fetch_upcoming_events(),
        )

        news_scores = [float(item["score"]) for item in headlines if item.get("score") is not None]
        news_score = self._normalize_average(news_scores, default=0.5)
        fear_greed_score = float(fear_greed.get("score", 0.5))
        long_short_ratio = bybit_sentiment.get("long_short_ratio")
        funding_rate = bybit_sentiment.get("funding_rate")
        ls_contrarian = 0.5
        if long_short_ratio is not None:
            if long_short_ratio > 0.65:
                ls_contrarian = 0.30
            elif long_short_ratio < 0.35:
                ls_contrarian = 0.70
        funding_score = 0.5
        if funding_rate is not None:
            if funding_rate > 0.0001:
                funding_score = 0.35
            elif funding_rate < 0:
                funding_score = 0.60
        aggregated_score = round(
            clamp(
                (news_score * 0.50) + (fear_greed_score * 0.20) + (ls_contrarian * 0.15) + (funding_score * 0.15),
                0.0,
                1.0,
            ),
            4,
        )
        sources_available = sum(
            1
            for item in [
                headlines,
                fear_greed.get("value"),
                long_short_ratio,
                funding_rate,
                google_trends.get("score"),
                btc_dominance,
            ]
            if item not in (None, [], {})
        )
        data_freshness = "fresh" if headlines else "partial" if fear_greed.get("value") is not None else "stale"
        pattern_matches = self.news_service.pattern_matcher.match_headlines([item["headline"] for item in headlines])

        return SentimentSnapshot(
            asset=asset,
            headlines=[item["headline"] for item in headlines],
            fear_greed_value=fear_greed.get("value"),
            fear_greed_label=fear_greed.get("classification"),
            long_short_ratio=long_short_ratio,
            funding_rate=funding_rate,
            google_trends_score=google_trends.get("score"),
            google_trends_direction=str(google_trends.get("direction", "flat")),
            google_trends_spike=bool(google_trends.get("spike", False)),
            volume_anomaly=volume_anomaly,
            aggregated_score=aggregated_score,
            news_score=news_score,
            sources_available=sources_available,
            data_freshness=data_freshness,
            btc_dominance=btc_dominance,
            upcoming_events=upcoming_events,
            pattern_matches=pattern_matches,
            market_context={
                "headlines": headlines,
                "fear_greed_value": fear_greed.get("value"),
                "fear_greed_label": fear_greed.get("classification"),
                "fear_greed_score": fear_greed_score,
                "long_short_ratio": long_short_ratio,
                "funding_rate": funding_rate,
                "google_trends_score": google_trends.get("score"),
                "google_trends_direction": google_trends.get("direction"),
                "google_trends_spike": google_trends.get("spike"),
                "btc_dominance": btc_dominance,
                "upcoming_events": upcoming_events,
                "pattern_matches": pattern_matches,
            },
        )

    def _normalize_average(self, scores: list[float], default: float) -> float:
        """Normalize arbitrary external scores into 0.0-1.0."""

        if not scores:
            return default
        average = sum(scores) / len(scores)
        return round(clamp((average + 10) / 20, 0.0, 1.0), 4)
