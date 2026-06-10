"""News, social, and market sentiment data providers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from loguru import logger

from ai.event_patterns import PatternMatcher
from config import Settings
from storage import Storage

try:
    from newsapi import NewsApiClient
except ImportError:  # pragma: no cover - optional dependency.
    NewsApiClient = None  # type: ignore[assignment]

try:
    from pytrends.request import TrendReq
except ImportError:  # pragma: no cover - optional dependency.
    TrendReq = None  # type: ignore[assignment]

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - optional dependency.
    fuzz = None  # type: ignore[assignment]


class NewsDataService:
    """Fetch external sentiment inputs with graceful degradation."""

    def __init__(self, settings: Settings, storage: Storage) -> None:
        """Create the news data service."""

        self.settings = settings
        self.storage = storage
        self.pattern_matcher = PatternMatcher()
        self._newsapi = NewsApiClient(api_key=settings.newsapi_key) if settings.newsapi_key and NewsApiClient else None
        self._trends = TrendReq(hl="en-US", tz=-60) if TrendReq else None

    async def fetch_asset_headlines(self, asset: str) -> list[dict[str, Any]]:
        """Fetch and deduplicate asset-specific headlines."""

        symbol_name = asset.split("/")[0]
        tasks = [self._fetch_newsapi(symbol_name), self._fetch_cryptocompare(symbol_name)]
        groups = await asyncio.gather(*tasks)
        merged = [item for group in groups for item in group]
        filtered = [item for item in merged if self._headline_mentions_asset(item["headline"], symbol_name)]
        unique = await self._deduplicate_with_storage(asset, filtered)
        if unique:
            self.storage.insert_headlines(asset, unique)
        return unique

    async def fetch_fear_and_greed(self) -> dict[str, Any]:
        """Fetch the crypto fear and greed index."""

        url = "https://api.alternative.me/fng/?limit=1"
        try:
            response = await asyncio.to_thread(requests.get, url, timeout=10)
            response.raise_for_status()
            payload = response.json()
            row = payload["data"][0]
            return {
                "value": int(row["value"]),
                "classification": row.get("value_classification", "Unknown"),
                "score": round(int(row["value"]) / 100, 4),
            }
        except Exception as error:  # pragma: no cover - network dependent.
            logger.error(f"Fear & Greed fetch failed: {error}")
            return {"value": None, "classification": None, "score": 0.5}

    async def fetch_bybit_sentiment(self, asset: str) -> dict[str, float | None]:
        """Fetch long/short ratio and funding rate from Bybit public endpoints."""

        base = asset.replace("/", "")
        ratio_url = f"https://api.bybit.com/v5/market/account-ratio?category=linear&symbol={base}&period=1h&limit=1"
        funding_url = f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={base}&limit=1"

        def _get_json(url: str) -> dict[str, Any]:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()

        try:
            ratio_payload, funding_payload = await asyncio.gather(
                asyncio.to_thread(_get_json, ratio_url),
                asyncio.to_thread(_get_json, funding_url),
            )
            ratio_list = ratio_payload.get("result", {}).get("list", [])
            funding_list = funding_payload.get("result", {}).get("list", [])
            long_short_ratio = float(ratio_list[0]["buyRatio"]) if ratio_list else None
            funding_rate = float(funding_list[0]["fundingRate"]) if funding_list else None
            return {"long_short_ratio": long_short_ratio, "funding_rate": funding_rate}
        except Exception as error:  # pragma: no cover - network dependent.
            logger.error(f"Bybit sentiment fetch failed for {asset}: {error}")
            return {"long_short_ratio": None, "funding_rate": None}

    async def fetch_google_trends(self, asset: str) -> dict[str, Any]:
        """Fetch Google Trends score and spike data."""

        if not self._trends:
            return {"score": None, "direction": "flat", "spike": False}
        keyword = asset.split("/")[0]

        def _load() -> dict[str, Any]:
            assert self._trends is not None
            self._trends.build_payload([keyword, f"buy {keyword}", f"{keyword} price"], timeframe="now 7-d")
            interest = self._trends.interest_over_time()
            if interest.empty:
                return {"score": None, "direction": "flat", "spike": False}
            columns = [column for column in interest.columns if column != "isPartial"]
            latest = float(interest[columns].iloc[-1].mean())
            average = float(interest[columns].mean().mean())
            prior = float(interest[columns].iloc[0].mean())
            direction = "up" if latest > prior else "down" if latest < prior else "flat"
            return {"score": latest, "direction": direction, "spike": latest > (average * 1.5 if average else 1000)}

        try:
            return await asyncio.to_thread(_load)
        except Exception as error:  # pragma: no cover - network dependent.
            logger.error(f"Google Trends fetch failed for {asset}: {error}")
            return {"score": None, "direction": "flat", "spike": False}

    async def fetch_btc_dominance(self) -> float | None:
        """Fetch BTC dominance from CoinGecko global data."""

        url = "https://api.coingecko.com/api/v3/global"
        try:
            response = await asyncio.to_thread(requests.get, url, timeout=10)
            response.raise_for_status()
            payload = response.json()
            dominance = payload.get("data", {}).get("market_cap_percentage", {}).get("btc")
            return float(dominance) if dominance is not None else None
        except Exception as error:  # pragma: no cover - network dependent.
            logger.error(f"BTC dominance fetch failed: {error}")
            return None

    async def fetch_upcoming_events(self) -> list[dict[str, Any]]:
        """Fetch high-impact upcoming macro events."""

        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        now = datetime.now(UTC)
        try:
            response = await asyncio.to_thread(requests.get, url, timeout=10)
            response.raise_for_status()
            events = response.json()
        except Exception as error:  # pragma: no cover - network dependent.
            logger.error(f"Economic calendar fetch failed: {error}")
            return []

        results: list[dict[str, Any]] = []
        for event in events:
            if str(event.get("impact", "")).lower() != "high":
                continue
            raw_date = event.get("date")
            if not raw_date:
                continue
            try:
                event_time = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except ValueError:
                continue
            if event_time < now - timedelta(hours=1):
                continue
            results.append(
                {
                    "title": event.get("title") or event.get("event"),
                    "country": event.get("country"),
                    "impact": event.get("impact"),
                    "date": event_time.isoformat(),
                }
            )
        return results

    async def economic_calendar_blocked(self) -> bool:
        """Return True if a high-impact event is within +/- 30 minutes."""

        now = datetime.now(UTC)
        for event in await self.fetch_upcoming_events():
            try:
                event_time = datetime.fromisoformat(str(event["date"]))
            except ValueError:
                continue
            if abs((event_time - now).total_seconds()) <= 1800:
                return True
        return False

    async def _fetch_newsapi(self, asset_name: str) -> list[dict[str, Any]]:
        """Fetch headlines from NewsAPI."""

        if not self._newsapi:
            return []

        def _load() -> list[dict[str, Any]]:
            payload = self._newsapi.get_everything(
                q=f"{asset_name} OR {asset_name} crypto",
                language="en",
                sort_by="publishedAt",
                from_param=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
                page_size=25,
            )
            results: list[dict[str, Any]] = []
            for article in payload.get("articles", []):
                title = article.get("title")
                if not title:
                    continue
                description = article.get("description") or ""
                results.append(
                    {
                        "headline": f"{title} {description}".strip(),
                        "source": "newsapi",
                        "published_at": article["publishedAt"],
                        "url": article.get("url"),
                        "score": None,
                    }
                )
            return results

        try:
            return await asyncio.to_thread(_load)
        except Exception as error:  # pragma: no cover - network dependent.
            logger.error(f"NewsAPI fetch failed for {asset_name}: {error}")
            return []

    async def _fetch_cryptocompare(self, asset_name: str) -> list[dict[str, Any]]:
        """Fetch headlines from CryptoCompare."""

        auth = f"&api_key={self.settings.cryptocompare_api_key}" if self.settings.cryptocompare_api_key else ""
        url = f"https://min-api.cryptocompare.com/data/v2/news/?lang=EN&categories={asset_name}{auth}"
        try:
            response = await asyncio.to_thread(requests.get, url, timeout=10)
            response.raise_for_status()
            payload = response.json()
        except Exception as error:  # pragma: no cover - network dependent.
            logger.error(f"CryptoCompare fetch failed for {asset_name}: {error}")
            return []

        results: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for item in payload.get("Data", []):
            title = item.get("title", "")
            if not title:
                continue
            published_dt = datetime.fromtimestamp(item.get("published_on", now.timestamp()), tz=UTC)
            age_hours = max((now - published_dt).total_seconds() / 3600, 0.1)
            vote_score = float(item.get("upvotes", 0)) - float(item.get("downvotes", 0))
            decayed_score = vote_score / age_hours
            results.append(
                {
                    "headline": title,
                    "source": "cryptocompare",
                    "published_at": published_dt.isoformat(),
                    "url": item.get("url"),
                    "score": round(decayed_score, 4),
                }
            )
        return results

    async def _deduplicate_with_storage(self, asset: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deduplicate against memory and recent DB headlines."""

        since = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        recent = self.storage.find_recent_headline(asset, "", since)
        unique: list[dict[str, Any]] = []
        for item in items:
            title = item["headline"]
            if any(self._similar(title, row["title"]) >= 85 for row in recent):
                continue
            if any(self._similar(title, existing["headline"]) >= 85 for existing in unique):
                continue
            unique.append(item)
        return unique[:50]

    def _headline_mentions_asset(self, headline: str, asset_symbol: str) -> bool:
        """Return True if the headline plausibly refers to the asset."""

        lower = headline.lower()
        candidates = {asset_symbol.lower()}
        aliases = {
            "btc": {"bitcoin"},
            "eth": {"ethereum"},
            "sol": {"solana"},
        }
        candidates.update(aliases.get(asset_symbol.lower(), set()))
        return any(candidate in lower for candidate in candidates)

    def _similar(self, left: str, right: str) -> float:
        """Return fuzzy similarity score between two strings."""

        if left.lower() == right.lower():
            return 100.0
        if fuzz is None:
            return 0.0
        return float(fuzz.token_set_ratio(left, right))
