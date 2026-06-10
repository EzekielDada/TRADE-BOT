"""Scheduled async main loop for the trading bot."""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime
from typing import Any

import schedule
from loguru import logger

from ai.consensus import ConsensusEngine
from ai.gemini_analyzer import GeminiAnalyzer
from ai.groq_analyzer import GroqAnalyzer
from config import Settings, configure_logging
from data.market_data import MarketDataService
from data.news_data import NewsDataService
from execution.order_manager import OrderManager
from execution.risk_manager import RiskManager
from storage import Storage
from strategies.market_regime import MarketRegimeDetector
from strategies.sentiment import SentimentAggregator
from strategies.signals import SignalAggregator
from strategies.technical import TechnicalStrategy


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
        self._shutdown_event = asyncio.Event()
        self._briefing_complete = asyncio.Event()
        if self.storage.get_state("briefing_complete", False):
            self._briefing_complete.set()
        self._register_jobs()

    async def run(self) -> None:
        """Run the bot until a shutdown signal is received."""

        self._install_signal_handlers()
        logger.info("Trading bot started.")
        try:
            while not self._shutdown_event.is_set():
                runtime_overrides = self.storage.get_state("runtime_overrides", {})
                await self._refresh_settings(self.settings.with_updates(**runtime_overrides))
                await asyncio.to_thread(schedule.run_pending)
                if self.storage.get_state("shutdown_requested", False):
                    self._shutdown_event.set()
                    continue
                await asyncio.sleep(1)
        finally:
            await self.shutdown()

    async def run_once(self) -> None:
        """Execute one full trading cycle."""

        logger.info("Running trading cycle.")
        latest_prices: dict[str, float] = {}
        economic_blocked = await self.news_data.economic_calendar_blocked()
        selected_assets = self.storage.get_state("selected_assets", self.settings.symbols)
        briefing_complete = self.storage.get_state("briefing_complete", False)

        for symbol in selected_assets:
            frames = await self.market_data.fetch_symbol_frames(symbol)
            technical_signal = self.technical.route_strategy(symbol, frames)
            regime = self.regime.detect(technical_signal)
            snapshot = await self.market_data.fetch_snapshot(symbol, frames[self.settings.primary_timeframe])
            latest_prices[symbol] = snapshot.price
            sentiment_snapshot = await self.sentiment.build_snapshot(symbol, snapshot.volume_anomaly)

            groq_task = self.groq.analyze(symbol, sentiment_snapshot)
            gemini_task = self.gemini.analyze(
                symbol,
                sentiment_snapshot,
                technical_signal,
                {**snapshot.to_dict(), "regime": regime.regime},
            )
            groq_result, gemini_result = await asyncio.gather(groq_task, gemini_task)
            pattern_signals = sentiment_snapshot.pattern_matches
            pattern_score = self.news_data.pattern_matcher.aggregate_pattern_score(pattern_signals)
            consensus = self.consensus.combine(groq_result, gemini_result, pattern_signals=pattern_signals, pattern_score=pattern_score)
            logger.bind(ai_log=True).info(f"{symbol} Groq response: {groq_result.to_dict() if groq_result else 'unavailable'}")
            logger.bind(ai_log=True).info(f"{symbol} Gemini response: {gemini_result.to_dict() if gemini_result else 'unavailable'}")

            account = self.orders.account_snapshot(latest_prices)
            weekly_limit_breached = account.weekly_pnl <= -(account.peak_equity * self.settings.weekly_loss_limit)
            decision = self.signals.decide(
                asset=symbol,
                technical_signal=technical_signal,
                consensus=consensus,
                regime=regime,
                market_sentiment=sentiment_snapshot.to_dict(),
                has_open_position=symbol in self.orders.positions,
                daily_limit_breached=self.risk.should_halt_new_entries(account),
                weekly_limit_breached=weekly_limit_breached,
                economic_event_blocked=economic_blocked,
                briefing_complete=briefing_complete,
                selected_assets=selected_assets,
                positions=self.orders.positions,
                account=account,
            )
            self.storage.save_signal(symbol, decision.action, decision.score, decision.breakdown)
            self.storage.set_state("active_patterns", pattern_signals)
            logger.bind(signal_log=True).info(f"{symbol} => {decision.action} score={decision.score} breakdown={decision.breakdown}")

            if consensus.status == "ai_unavailable":
                logger.warning(f"{symbol}: both AI analyzers unavailable; managing existing positions only.")
                continue

            if decision.action in {"buy", "strong_buy"}:
                risk_check = self.risk.can_open_position(
                    signal=decision,
                    technical_signal=technical_signal,
                    account=account,
                    positions=self.orders.positions,
                    price=snapshot.price,
                )
                if risk_check.approved and risk_check.order_request:
                    await self.orders.execute_entry(risk_check.order_request)
                else:
                    logger.bind(signal_log=True).info(f"{symbol} entry blocked: {risk_check.reason}")
            elif decision.action in {"sell", "strong_sell"} and symbol in self.orders.positions:
                await self.orders.close_position(symbol, snapshot.price)

        closed = await self.orders.manage_open_positions(latest_prices)
        for trade in closed:
            logger.bind(trade_log=True).info(f"Managed exit for {trade.asset} with PnL {trade.pnl}")

    async def run_premarket_briefing(self) -> None:
        """Build the daily briefing and select assets."""

        logger.info("Running premarket briefing.")
        asset_reports: list[dict[str, Any]] = []
        for symbol in self.settings.symbols:
            frames = await self.market_data.fetch_symbol_frames(symbol)
            technical_signal = self.technical.route_strategy(symbol, frames)
            regime = self.regime.detect(technical_signal)
            snapshot = await self.market_data.fetch_snapshot(symbol, frames[self.settings.primary_timeframe])
            sentiment_snapshot = await self.sentiment.build_snapshot(symbol, snapshot.volume_anomaly)
            bias_score = round((technical_signal.technical_score * 0.5) + (sentiment_snapshot.aggregated_score * 0.5), 4)
            asset_reports.append(
                {
                    "asset": symbol,
                    "bias_score": bias_score,
                    "regime": regime.to_dict(),
                    "technical": technical_signal.to_dict(),
                    "sentiment": sentiment_snapshot.to_dict(),
                    "price": snapshot.to_dict(),
                    "bull_catalysts": [item["headline"] for item in sentiment_snapshot.market_context.get("headlines", [])[:3]],
                    "bear_risks": [item["headline"] for item in sentiment_snapshot.market_context.get("headlines", [])[3:6]],
                }
            )
        asset_reports.sort(key=lambda item: item["bias_score"], reverse=True)
        selected_assets = [item["asset"] for item in asset_reports[: self.settings.max_assets_to_trade_daily]]
        report = {
            "report_date": datetime.now(UTC).date().isoformat(),
            "market_bias": "bullish" if sum(item["bias_score"] for item in asset_reports) / max(len(asset_reports), 1) >= 0.55 else "neutral",
            "confidence": round(sum(item["bias_score"] for item in asset_reports) / max(len(asset_reports), 1), 4),
            "selected_assets": selected_assets,
            "assets": asset_reports,
        }
        report_date = report["report_date"]
        self.storage.save_report("daily_briefing", report_date, report)
        self.storage.set_state("last_briefing_date", report_date)
        self.storage.set_state("selected_assets", selected_assets)
        self.storage.set_state("briefing_complete", True)
        self._briefing_complete.set()

    async def update_intelligence(self) -> None:
        """Refresh intraday intelligence snapshot."""

        logger.info("Refreshing intraday intelligence.")
        selected_assets = self.storage.get_state("selected_assets", self.settings.symbols)
        updates: list[dict[str, Any]] = []
        for symbol in selected_assets:
            sentiment_snapshot = await self.sentiment.build_snapshot(symbol)
            updates.append(
                {
                    "asset": symbol,
                    "aggregated_score": sentiment_snapshot.aggregated_score,
                    "patterns": sentiment_snapshot.pattern_matches,
                    "upcoming_events": sentiment_snapshot.upcoming_events,
                }
            )
        self.storage.save_report("intraday_intelligence", datetime.now(UTC).isoformat(), {"updates": updates})
        self.storage.set_state("active_patterns", [pattern for update in updates for pattern in update["patterns"]])

    async def end_of_day_review(self) -> None:
        """Generate end-of-day report and reset briefing flag for tomorrow."""

        logger.info("Running end-of-day review.")
        trades = self.orders.recent_trades(limit=200)
        today = datetime.now(UTC).date().isoformat()
        today_trades = [trade for trade in trades if str(trade.get("entry_time", "")).startswith(today)]
        total_pnl = round(sum(float(trade.get("pnl") or 0.0) for trade in today_trades), 2)
        report = {
            "report_date": today,
            "trades_taken": len(today_trades),
            "total_pnl": total_pnl,
            "wins": len([trade for trade in today_trades if float(trade.get("pnl") or 0.0) > 0]),
            "losses": len([trade for trade in today_trades if float(trade.get("pnl") or 0.0) <= 0]),
        }
        self.storage.save_report("end_of_day", today, report)
        self.storage.set_state("briefing_complete", False)
        self._briefing_complete.clear()

    async def fill_pattern_log_outcomes(self) -> None:
        """Summarize pattern outcomes from recent signals and trades."""

        signals = self.storage.fetch_signals(limit=200)
        trades = {trade["trade_id"]: trade for trade in self.storage.fetch_trades(limit=200)}
        summary: dict[str, dict[str, float]] = {}
        for signal in signals:
            breakdown = signal.get("breakdown")
            if isinstance(breakdown, str):
                import json
                breakdown_data = json.loads(breakdown)
            else:
                breakdown_data = breakdown
            for pattern in breakdown_data.get("pattern_matches", []):
                name = pattern.get("pattern_name", "unknown")
                bucket = summary.setdefault(name, {"count": 0, "avg_signal_score": 0.0})
                bucket["count"] += 1
                bucket["avg_signal_score"] += float(signal["score"])
        for item in summary.values():
            item["avg_signal_score"] = round(item["avg_signal_score"] / max(item["count"], 1), 2)
        self.storage.save_report("pattern_outcomes", datetime.now(UTC).date().isoformat(), summary)

    async def run_trading_loop(self) -> None:
        """Wait for the daily briefing gate before trading."""

        await self._briefing_complete.wait()
        if self.settings.bot_paused:
            logger.info("Trading loop skipped because bot is paused.")
            return
        await self.run_once()

    async def shutdown(self) -> None:
        """Gracefully close resources."""

        logger.info("Shutting down trading bot.")
        await self.orders.close()
        await self.market_data.close()

    async def _refresh_settings(self, settings: Settings) -> None:
        """Apply runtime settings to all services."""

        self.settings = settings
        self.market_data.settings = settings
        self.news_data.settings = settings
        self.technical.settings = settings
        self.regime.settings = settings
        self.groq.settings = settings
        self.gemini.settings = settings
        self.signals.settings = settings
        self.risk.settings = settings
        await self.orders.refresh_settings(settings)

    def _register_jobs(self) -> None:
        """Register the schedule-based timed jobs."""

        schedule.clear()
        schedule.every().day.at(self.settings.premarket_time_wat).do(self._schedule_async, self.run_premarket_briefing)
        schedule.every(self.settings.intraday_update_hours).hours.do(self._schedule_async, self.update_intelligence)
        schedule.every().day.at(self.settings.eod_review_time_wat).do(self._schedule_async, self.end_of_day_review)
        schedule.every(15).minutes.do(self._schedule_async, self.run_trading_loop)
        schedule.every(24).hours.do(self._schedule_async, self.fill_pattern_log_outcomes)

    def _schedule_async(self, coroutine_factory: Any) -> None:
        """Schedule an async coroutine from the sync scheduler."""

        asyncio.create_task(coroutine_factory())

    def _install_signal_handlers(self) -> None:
        """Install process signal handlers."""

        try:
            loop = asyncio.get_running_loop()
            for signame in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signame, self._shutdown_event.set)
        except NotImplementedError:
            logger.warning("Signal handlers are not available on this platform.")


async def main() -> None:
    """Entry point for the trading bot."""

    configure_logging()
    settings = Settings.from_env()
    bot = TradingBot(settings)
    if not bot.storage.get_state("briefing_complete", False):
        await bot.run_premarket_briefing()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
