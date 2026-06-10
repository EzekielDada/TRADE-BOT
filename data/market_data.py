"""Market data access with primary and backup public exchange integrations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator

import pandas as pd
import requests
from loguru import logger

from config import Settings
from storage import Storage
from utils import ExternalServiceError, with_retry

try:
    import ccxt.async_support as ccxt_async
except ImportError:  # pragma: no cover - optional dependency.
    ccxt_async = None  # type: ignore[assignment]


BYBIT_INTERVAL_MAP = {"15m": "15", "1h": "60", "4h": "240"}


@dataclass(slots=True)
class MarketSnapshot:
    """Latest price context for a symbol."""

    symbol: str
    price: float
    change_24h: float
    change_7d: float
    volume_anomaly: float

    def to_dict(self) -> dict[str, float | str]:
        """Return a JSON-serializable dictionary."""

        return {
            "symbol": self.symbol,
            "price": self.price,
            "change_24h": self.change_24h,
            "change_7d": self.change_7d,
            "volume_anomaly": self.volume_anomaly,
        }


class MarketDataService:
    """Fetch OHLCV data and live prices from real exchanges."""

    def __init__(self, settings: Settings, storage: Storage) -> None:
        """Create the market data service."""

        self.settings = settings
        self.storage = storage
        self._primary_exchange = self._build_exchange(settings.exchange, settings.bybit_api_key, settings.bybit_secret)
        self.price_cache: dict[str, float] = {}

    def _build_exchange(self, name: str, api_key: str, secret: str) -> Any:
        """Build an async CCXT exchange instance if available."""

        if ccxt_async is None or not hasattr(ccxt_async, name):
            return None
        exchange_class = getattr(ccxt_async, name)
        options: dict[str, Any] = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
        if name == "bybit" and self.settings.bybit_testnet:
            options["urls"] = {"api": {"public": "https://api-testnet.bybit.com", "private": "https://api-testnet.bybit.com"}}
        return exchange_class(options)

    async def fetch_candles(self, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
        """Fetch candles for a symbol/timeframe using real exchange data."""

        last_error: Exception | None = None
        if self._primary_exchange is not None:
            try:
                candles = await self._fetch_from_exchange(self._primary_exchange, self.settings.exchange, symbol, timeframe, limit)
                self.storage.insert_candles(self.settings.exchange, symbol, timeframe, candles)
                return pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            except Exception as error:  # pragma: no cover - network dependent.
                last_error = error
                logger.warning(f"Exchange fetch failed for {symbol} {timeframe}: {self.settings.exchange} failed with {error}")

        try:
            candles = await self._fetch_bybit_public(symbol, timeframe, limit)
            self.storage.insert_candles("bybit_public", symbol, timeframe, candles)
            return pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        except Exception as error:  # pragma: no cover - network dependent.
            last_error = error

        raise ExternalServiceError(f"Unable to fetch real market data for {symbol} {timeframe}: {last_error}")

    async def fetch_symbol_frames(self, symbol: str) -> dict[str, pd.DataFrame]:
        """Fetch all required timeframes for one symbol."""

        timeframes = [self.settings.entry_timeframe, self.settings.primary_timeframe, self.settings.trend_timeframe]
        frames = await asyncio.gather(*(self.fetch_candles(symbol, timeframe) for timeframe in timeframes))
        return dict(zip(timeframes, frames, strict=True))

    async def fetch_snapshot(self, symbol: str, primary_frame: pd.DataFrame) -> MarketSnapshot:
        """Build a latest market snapshot from primary timeframe candles."""

        latest = primary_frame.iloc[-1]
        prior_24h = primary_frame.iloc[-24] if len(primary_frame) >= 24 else primary_frame.iloc[0]
        prior_7d = primary_frame.iloc[-168] if len(primary_frame) >= 168 else primary_frame.iloc[0]
        change_24h = ((latest["close"] - prior_24h["close"]) / prior_24h["close"]) * 100 if prior_24h["close"] else 0.0
        change_7d = ((latest["close"] - prior_7d["close"]) / prior_7d["close"]) * 100 if prior_7d["close"] else 0.0
        average_volume = primary_frame["volume"].tail(20).mean() or latest["volume"]
        volume_anomaly = float(latest["volume"] / average_volume) if average_volume else 1.0
        price = float(latest["close"])
        self.price_cache[symbol] = price
        return MarketSnapshot(
            symbol=symbol,
            price=price,
            change_24h=round(float(change_24h), 4),
            change_7d=round(float(change_7d), 4),
            volume_anomaly=round(volume_anomaly, 4),
        )

    async def price_stream(self, symbol: str, interval_seconds: float = 3.0) -> AsyncIterator[float]:
        """Yield live public prices for a symbol."""

        while True:
            price = await self.fetch_latest_price(symbol)
            self.price_cache[symbol] = price
            yield price
            await asyncio.sleep(interval_seconds)

    async def fetch_latest_price(self, symbol: str) -> float:
        """Fetch the latest public price for a symbol."""

        symbol_code = symbol.replace("/", "")
        bybit_url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol_code}"

        def _load() -> float:
            response = requests.get(bybit_url, timeout=10)
            response.raise_for_status()
            payload = response.json()
            tickers = payload.get("result", {}).get("list", [])
            if not tickers:
                raise ExternalServiceError(f"No Bybit ticker data for {symbol}")
            return float(tickers[0]["lastPrice"])

        try:
            return await asyncio.to_thread(_load)
        except Exception:
            frame = await self.fetch_candles(symbol, self.settings.entry_timeframe, limit=2)
            return float(frame.iloc[-1]["close"])

    async def close(self) -> None:
        """Close any underlying exchange sessions."""

        if self._primary_exchange:
            await self._primary_exchange.close()

    async def _fetch_from_exchange(self, exchange: Any, exchange_name: str, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        """Fetch candles from an exchange with retry."""

        async def _call() -> list[list[float]]:
            return await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

        return await with_retry(_call, attempts=3, base_delay=1.5)

    async def _fetch_bybit_public(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        """Fetch public OHLCV data directly from Bybit REST."""

        interval = BYBIT_INTERVAL_MAP[timeframe]
        symbol_code = symbol.replace("/", "")
        url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol_code}&interval={interval}&limit={limit}"

        def _load() -> list[list[float]]:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("result", {}).get("list", [])
            if not rows:
                raise ExternalServiceError(f"No Bybit public candles for {symbol} {timeframe}")
            candles = [
                [
                    int(row[0]),
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    float(row[5]),
                ]
                for row in reversed(rows)
            ]
            return candles

        return await asyncio.to_thread(_load)
