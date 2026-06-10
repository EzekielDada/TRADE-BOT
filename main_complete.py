"""Main trading bot orchestration with async scheduling."""

from __future__ import annotations

import asyncio
import json
import platform
import signal
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import schedule
from loguru import logger

from ai.consensus import ConsensusEngine
from ai.event_patterns import PatternMatcher
from ai.gemini_analyzer import GeminiAnalyzer
from ai.groq_analyzer import GroqAnalyzer
from config import Settings, configure_logging
from data.market_data import MarketDataService
from data.news_data import NewsDataService
from execution.order_manager import OrderManager
from execution.risk_manager import RiskManager
from models import Position, SignalDecision, TradeRecord
from storage import Storage
from strategies.market_regime import MarketRegimeDetector
from strategies.sentiment import SentimentAggregator
from strategies.signals import SignalAggregator
from strategies.technical import TechnicalStrategy
from utils import ExternalServiceError, ServiceUnavailableError, wat_now, utc_now


class TradingBot:
    """Coordinates the trading bot subsystems."""

    def __init__(self, settings: Settings) -> None:
        """Create the bot and all services."""
        self.settings = settings
        self.storage = Storage(settings.sqlite_path)
        self.market_data = MarketDataService(settings, self.storage)
        self.news_data = NewsDataService(settings, self.storage)
        self.sentiment = SentimentAggregator(self.news_data)
        self.technical = TechnicalStrategy(settings)
        self.regime = MarketRegimeDetector(settings)
        self.groq = GroqAnalyzer(settings)
        self.gemini = GeminiAnalyzer(settings)
        self.consensus = ConsensusEngine()
        self.signals = SignalAggregator(settings)
        self.risk = RiskManager(settings)
        self.orders = OrderManager(settings, self.storage)
        self.pattern_matcher = PatternMatcher()

        self._shutdown_event = asyncio.Event()
        self._briefing_complete = asyncio.Event()
        self._selected_assets = []
        self._peak_balance = settings.initial_cash
        self._trades_today = []
        self._trades_this_week = []

        # Load persisted state
        if self.storage.get_state("briefing_complete", "false").lower() == "true":
            self._briefing_complete.set()

    async def run(self) -> None:
        """Main bot loop with scheduled jobs."""
        logger.info("🤖 Trading Bot Starting...")
        logger.info(f"Mode: {'📄 PAPER' if self.settings.paper_trading else '💰 LIVE'}")
        logger.info(f"Exchange: {self.settings.exchange}")
        logger.info(f"Symbols: {self.settings.symbols}")

        # Setup signal handlers (Unix only — Windows does not support add_signal_handler)
        if platform.system() != "Windows":
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

        # Schedule all jobs
        schedule.every().day.at(self.settings.premarket_time_wat).do(
            lambda: asyncio.create_task(self.run_premarket_briefing())
        )
        schedule.every(self.settings.intraday_update_hours).hours.do(
            lambda: asyncio.create_task(self.update_intelligence())
        )
        schedule.every().day.at(self.settings.eod_review_time_wat).do(
            lambda: asyncio.create_task(self.end_of_day_review())
        )
        schedule.every(self.settings.loop_interval_seconds // 60).minutes.do(
            lambda: asyncio.create_task(self.trading_loop())
        )

        logger.info("✓ All jobs scheduled")

        # Main scheduler loop
        while not self._shutdown_event.is_set():
            schedule.run_pending()
            await asyncio.sleep(10)

        await self.shutdown()

    async def run_premarket_briefing(self) -> None:
        """Run at market open to select assets and generate daily intelligence."""
        logger.info("📋 Starting premarket briefing...")

        try:
            # Phase 1: Asset selection
            self._selected_assets = await self._select_assets_for_today()
            logger.info(f"✓ Selected assets: {self._selected_assets}")

            # Phase 2: Deep research per asset
            briefing_data = {
                "timestamp": wat_now().isoformat(),
                "selected_assets": self._selected_assets,
                "market_bias": "neutral",
                "upcoming_risks": [],
                "per_asset": {},
            }

            for asset in self._selected_assets:
                research = await self._research_asset_events(asset)
                briefing_data["per_asset"][asset] = research

            # Phase 3: Save report
            if self.settings.save_daily_reports:
                report_date = wat_now().date().isoformat()
                report_path = self.settings.reports_dir / "daily" / f"{report_date}.json"
                report_path.parent.mkdir(parents=True, exist_ok=True)
                with open(report_path, "w") as f:
                    json.dump(briefing_data, f, indent=2)
                logger.info(f"✓ Briefing saved: {report_path}")

            self._briefing_complete.set()
            self.storage.set_state("briefing_complete", "true")
            logger.info("✓ Premarket briefing complete")

        except Exception as e:
            logger.error(f"✗ Premarket briefing failed: {e}")

    async def _select_assets_for_today(self) -> list[str]:
        """Use configured symbols to select top trading opportunities."""
        return self.settings.symbols[: self.settings.max_assets_to_trade_daily]

    async def _research_asset_events(self, asset: str) -> dict[str, Any]:
        """Deep research one asset for patterns and events."""
        try:
            news_items = await self.news_data.fetch_asset_headlines(asset)
            headline_texts = [item["headline"] for item in news_items]
            patterns = self.pattern_matcher.match_headlines(headline_texts)

            return {
                "asset": asset,
                "headlines_24h": len(news_items),
                "patterns_detected": len(patterns),
                "research_time": wat_now().isoformat(),
            }
        except Exception as e:
            logger.warning(f"Research failed for {asset}: {e}")
            return {"asset": asset, "error": str(e)}

    async def update_intelligence(self) -> None:
        """Update intelligence every 2 hours during trading."""
        logger.info("🔄 Updating intraday intelligence...")

        try:
            for asset in self._selected_assets:
                news_items = await self.news_data.fetch_asset_headlines(asset)
                headline_texts = [item["headline"] for item in news_items]
                patterns = self.pattern_matcher.match_headlines(headline_texts)

                if any(p.get("severity") == "critical" for p in patterns):
                    logger.warning(f"⚠ Critical pattern detected for {asset}")

        except Exception as e:
            logger.warning(f"Intelligence update failed: {e}")

    async def end_of_day_review(self) -> None:
        """Review day's performance at EOD."""
        logger.info("📊 End of day review...")

        try:
            today_date = wat_now().date().isoformat()

            # Calculate today's stats
            trades_today = len(self._trades_today)
            wins = sum(1 for t in self._trades_today if (t.pnl or 0) > 0)
            losses = sum(1 for t in self._trades_today if (t.pnl or 0) < 0)

            # Save to database
            daily_pnl = sum(t.pnl or 0 for t in self._trades_today)

            with self.storage.connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO daily_pnl
                    (date, starting_balance, ending_balance, trades_taken, wins, losses, gross_pnl, fees_paid, net_pnl)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        today_date,
                        10000.0,
                        10000.0 + daily_pnl,
                        trades_today,
                        wins,
                        losses,
                        daily_pnl,
                        daily_pnl * 0.001,
                        daily_pnl * 0.999,
                    ),
                )

            logger.info(f"✓ EOD Review: {wins}W {losses}L, PnL: ${daily_pnl:.2f}")

        except Exception as e:
            logger.error(f"✗ EOD review failed: {e}")

    async def trading_loop(self) -> None:
        """Main 15-minute trading loop."""
        if not self._briefing_complete.is_set():
            logger.info("⏳ Waiting for premarket briefing...")
            return

        if self.settings.bot_paused:
            logger.debug("🤐 Bot paused, skipping trading loop")
            return

        try:
            logger.info("🔄 Trading loop iteration...")

            for asset in self._selected_assets:
                await self._process_asset(asset)

        except Exception as e:
            logger.error(f"Trading loop error: {e}")

    async def _process_asset(self, asset: str) -> None:
        """Process one asset through full trading pipeline."""
        try:
            # Fetch all timeframes required for technical analysis
            frames = await self.market_data.fetch_symbol_frames(asset)
            primary_frame = frames[self.settings.primary_timeframe]
            if primary_frame.empty:
                logger.warning(f"No candle data for {asset}")
                return

            # Get current price
            price = await self.market_data.fetch_latest_price(asset)

            # Calculate technical signals across all timeframes
            technical_signal = self.technical.calculate(frames)

            # Detect market regime
            regime = self.regime.detect(technical_signal)

            # Build sentiment snapshot (fetches headlines, fear/greed, etc. internally)
            sentiment_snapshot = await self.sentiment.build_snapshot(asset)
            headlines = sentiment_snapshot.headlines

            # Run AI analysis in parallel
            groq_result, gemini_result = await asyncio.gather(
                self.groq.analyze(asset, sentiment_snapshot),
                self.gemini.analyze(asset, sentiment_snapshot, technical_signal),
                return_exceptions=True,
            )

            # Pattern analysis
            patterns = self.pattern_matcher.match_headlines(headlines)
            pattern_score = self.pattern_matcher.aggregate_pattern_score(patterns)

            consensus = self.consensus.combine(
                groq_result if not isinstance(groq_result, Exception) else None,
                gemini_result if not isinstance(gemini_result, Exception) else None,
                pattern_signals=patterns,
                pattern_score=pattern_score,
            )

            # Generate signal
            signal = self.signals.decide(
                asset=asset,
                technical_signal=technical_signal,
                consensus=consensus,
                regime=regime,
                market_sentiment={},
                has_open_position=asset in self.orders.positions,
                daily_limit_breached=False,
                weekly_limit_breached=False,
                economic_event_blocked=False,
                briefing_complete=self._briefing_complete.is_set(),
                selected_assets=self._selected_assets,
            )

            # Log signal
            logger.bind(signal_log=True).info(f"{asset}: {signal.action} (score: {signal.score})")

            # Risk check and execute
            if signal.action in {"buy", "strong_buy"}:
                account = self.orders.account_snapshot({asset: price})
                positions = self.orders.positions

                risk_check = self.risk.can_open_position(
                    signal=signal,
                    technical_signal=technical_signal,
                    account=account,
                    positions=positions,
                    price=price,
                )

                if risk_check.approved and risk_check.order_request:
                    position = await self.orders.execute_entry(risk_check.order_request)
                    if position:
                        logger.bind(trade_log=True).info(f"Executed {asset}: {position.trade_id}")
                else:
                    logger.warning(f"Order rejected: {risk_check.reason}")

        except Exception as e:
            logger.error(f"Error processing {asset}: {e}")

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("🛑 Shutting down...")

        # Close all open positions if live trading
        if not self.settings.paper_trading:
            for symbol in list(self.orders.positions.keys()):
                try:
                    position = self.orders.positions[symbol]
                    await self.orders.close_position(symbol, position.entry_price)
                except Exception as e:
                    logger.error(f"Failed to close position {symbol}: {e}")

        # Close exchange connections
        await self.market_data.close()
        await self.orders.close()

        self._shutdown_event.set()
        logger.info("✓ Bot stopped")


async def main() -> None:
    """Entry point."""
    configure_logging()
    settings = Settings.from_env()

    bot = TradingBot(settings)
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
