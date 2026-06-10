"""Configuration management for the trading bot."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency.
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        """Fallback no-op when python-dotenv is unavailable."""

        return False


try:
    from loguru import logger
except ImportError:  # pragma: no cover - optional dependency.
    class _FallbackLogger:
        """Tiny logger shim for environments without loguru."""

        def __init__(self) -> None:
            self._logger = logging.getLogger("trading_bot")
            if not self._logger.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
                handler.setFormatter(formatter)
                self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

        def remove(self) -> None:
            """Compatibility no-op."""

        def add(self, *args: Any, **kwargs: Any) -> None:
            """Compatibility no-op."""

        def info(self, message: str) -> None:
            """Log an info message."""

            self._logger.info(message)

        def warning(self, message: str) -> None:
            """Log a warning message."""

            self._logger.warning(message)

        def error(self, message: str) -> None:
            """Log an error message."""

            self._logger.error(message)

    logger = _FallbackLogger()


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "runtime"
DB_PATH = DATA_DIR / "bot.db"
LOG_DIR = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports"


def _split_csv(value: str, fallback: list[str]) -> list[str]:
    """Parse a comma-separated string into a list."""

    parsed = [item.strip() for item in value.split(",") if item.strip()]
    return parsed or fallback


def _get_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable."""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_float(name: str, default: float) -> float:
    """Read a float environment variable."""

    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    """Read an integer environment variable."""

    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(slots=True)
class Settings:
    """Runtime configuration loaded from environment variables."""

    exchange: str = "bybit"
    symbols: list[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])
    primary_timeframe: str = "1h"
    entry_timeframe: str = "15m"
    trend_timeframe: str = "4h"
    paper_trading: bool = True
    bybit_testnet: bool = True
    sentiment_weight: float = 0.40
    technical_weight: float = 0.40
    market_sentiment_weight: float = 0.20
    ema_periods: list[int] = field(default_factory=lambda: [9, 20, 50, 200])
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    rsi_oversold: int = 35
    rsi_overbought: int = 70
    atr_period: int = 14
    adx_trend_threshold: int = 25
    risk_per_trade: float = 0.02
    daily_loss_limit: float = 0.05
    weekly_loss_limit: float = 0.10
    max_drawdown: float = 0.15
    max_positions: int = 3
    min_reward_risk: float = 2.5
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_model: str = "gemini-2.0-flash"
    sentiment_cache_minutes: int = 10
    bot_paused: bool = False
    loop_interval_seconds: int = 900
    initial_cash: float = 10_000.0
    premarket_time_wat: str = "06:00"
    eod_review_time_wat: str = "23:00"
    intraday_update_hours: int = 2
    premarket_news_window_days: int = 7
    max_assets_to_trade_daily: int = 3
    high_risk_position_multiplier: float = 0.50
    extreme_risk_skip_trading: bool = True
    save_daily_reports: bool = True
    timezone: str = "Africa/Lagos"
    sqlite_path: Path = DB_PATH
    reports_dir: Path = REPORTS_DIR
    groq_api_key: str = ""
    gemini_api_key: str = ""
    bybit_api_key: str = ""
    bybit_secret: str = ""
    newsapi_key: str = ""
    cryptocompare_api_key: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from the current environment."""

        load_dotenv(BASE_DIR / ".env")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "daily").mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "eod").mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "backtest").mkdir(parents=True, exist_ok=True)
        return cls(
            exchange=os.getenv("EXCHANGE", "bybit"),
            symbols=_split_csv(os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT"), ["BTC/USDT", "ETH/USDT"]),
            primary_timeframe=os.getenv("PRIMARY_TIMEFRAME", "1h"),
            entry_timeframe=os.getenv("ENTRY_TIMEFRAME", "15m"),
            trend_timeframe=os.getenv("TREND_TIMEFRAME", "4h"),
            paper_trading=_get_bool("PAPER_TRADING", True),
            bybit_testnet=_get_bool("BYBIT_TESTNET", True),
            sentiment_weight=_get_float("SENTIMENT_WEIGHT", 0.40),
            technical_weight=_get_float("TECHNICAL_WEIGHT", 0.40),
            market_sentiment_weight=_get_float("MARKET_SENTIMENT_WEIGHT", 0.20),
            ema_periods=[int(item) for item in _split_csv(os.getenv("EMA_PERIODS", "9,20,50,200"), ["9", "20", "50", "200"])],
            macd_fast=_get_int("MACD_FAST", 12),
            macd_slow=_get_int("MACD_SLOW", 26),
            macd_signal=_get_int("MACD_SIGNAL", 9),
            rsi_period=_get_int("RSI_PERIOD", 14),
            rsi_oversold=_get_int("RSI_OVERSOLD", 35),
            rsi_overbought=_get_int("RSI_OVERBOUGHT", 70),
            atr_period=_get_int("ATR_PERIOD", 14),
            adx_trend_threshold=_get_int("ADX_TREND_THRESHOLD", 25),
            risk_per_trade=_get_float("RISK_PER_TRADE", 0.02),
            daily_loss_limit=_get_float("DAILY_LOSS_LIMIT", 0.05),
            weekly_loss_limit=_get_float("WEEKLY_LOSS_LIMIT", 0.10),
            max_drawdown=_get_float("MAX_DRAWDOWN", 0.15),
            max_positions=_get_int("MAX_POSITIONS", 3),
            min_reward_risk=_get_float("MIN_REWARD_RISK", 2.5),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            sentiment_cache_minutes=_get_int("SENTIMENT_CACHE_MINUTES", 10),
            bot_paused=_get_bool("BOT_PAUSED", False),
            loop_interval_seconds=_get_int("LOOP_INTERVAL_SECONDS", 900),
            initial_cash=_get_float("INITIAL_CASH", 10_000.0),
            premarket_time_wat=os.getenv("PREMARKET_TIME_WAT", "06:00"),
            eod_review_time_wat=os.getenv("EOD_REVIEW_TIME_WAT", "23:00"),
            intraday_update_hours=_get_int("INTRADAY_UPDATE_HOURS", 2),
            premarket_news_window_days=_get_int("PREMARKET_NEWS_WINDOW_DAYS", 7),
            max_assets_to_trade_daily=_get_int("MAX_ASSETS_TO_TRADE_DAILY", 3),
            high_risk_position_multiplier=_get_float("HIGH_RISK_POSITION_MULTIPLIER", 0.50),
            extreme_risk_skip_trading=_get_bool("EXTREME_RISK_SKIP_TRADING", True),
            save_daily_reports=_get_bool("SAVE_DAILY_REPORTS", True),
            timezone=os.getenv("TIMEZONE", "Africa/Lagos"),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            bybit_api_key=os.getenv("BYBIT_API_KEY", ""),
            bybit_secret=os.getenv("BYBIT_SECRET", ""),
            newsapi_key=os.getenv("NEWSAPI_KEY", ""),
            cryptocompare_api_key=os.getenv("CRYPTOCOMPARE_API_KEY", ""),
        )

    def with_updates(self, **kwargs: Any) -> "Settings":
        """Return a copy with runtime overrides applied."""

        if "reports_dir" in kwargs and isinstance(kwargs["reports_dir"], str):
            kwargs["reports_dir"] = Path(kwargs["reports_dir"])
        return replace(self, **kwargs)


def configure_logging() -> None:
    """Configure console and rotating file logging."""

    logger.remove()
    base_format = "{time:YYYY-MM-DD HH:mm:ss ZZ} | {level} | {module}:{function} | {message}"
    logger.add(sink=lambda msg: print(msg, end="", flush=True), format=base_format, level="INFO")
    logger.add(LOG_DIR / "bot.log", format=base_format, rotation="1 day", retention="30 days", level="INFO")
    logger.add(
        LOG_DIR / "trades.log",
        format=base_format,
        rotation="1 day",
        retention="30 days",
        level="INFO",
        filter=lambda record: record["extra"].get("trade_log", False),
    )
    logger.add(
        LOG_DIR / "signals.log",
        format=base_format,
        rotation="1 day",
        retention="30 days",
        level="INFO",
        filter=lambda record: record["extra"].get("signal_log", False),
    )
    logger.add(
        LOG_DIR / "patterns.log",
        format=base_format,
        rotation="1 day",
        retention="30 days",
        level="INFO",
        filter=lambda record: record["extra"].get("pattern_log", False),
    )
    logger.add(
        LOG_DIR / "commands.log",
        format=base_format,
        rotation="1 day",
        retention="30 days",
        level="INFO",
        filter=lambda record: record["extra"].get("command_log", False),
    )
    logger.add(LOG_DIR / "errors.log", format=base_format + "\n{exception}", rotation="1 day", retention="30 days", level="ERROR")
    logger.add(
        LOG_DIR / "ai_responses.log",
        format=base_format,
        rotation="1 day",
        retention="30 days",
        level="INFO",
        filter=lambda record: record["extra"].get("ai_log", False),
    )
