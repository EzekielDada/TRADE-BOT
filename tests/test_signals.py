"""Unit tests for the final signal aggregator."""

from __future__ import annotations

import unittest

from config import Settings
from models import ConsensusResult, RegimeResult, TechnicalSignal
from strategies.signals import SignalAggregator


def _technical_signal(score: float) -> TechnicalSignal:
    """Create a reusable technical signal fixture."""

    return TechnicalSignal(
        trend="up",
        ema_signal="bullish_cross",
        macd_signal="bullish",
        rsi=48.0,
        rsi_signal="neutral",
        stoch_rsi=52.0,
        bb_position="middle",
        adx=28.0,
        trend_strength="strong",
        volume_signal="high",
        support=60_000.0,
        resistance=68_000.0,
        atr=1_000.0,
        timeframe_alignment="all",
        technical_score=score,
        primary_timeframe="1h",
        entry_timeframe="15m",
        trend_timeframe="4h",
        metadata={},
    )


class SignalAggregatorTests(unittest.TestCase):
    """Verify score aggregation and entry filters."""

    def setUp(self) -> None:
        """Create a reusable aggregator."""

        self.aggregator = SignalAggregator(Settings())
        self.consensus = ConsensusResult(
            final_score=0.9,
            final_confidence=0.8,
            models_agree=True,
            trade_safe=True,
            groq_score=0.88,
            gemini_score=0.92,
            gemini_recommendation="strong_buy",
            risk_flags=[],
            reasoning="Aligned bullish setup.",
            key_levels={"support": 60_000, "resistance": 68_000},
            pattern_signals=[],
            pattern_score=0.0,
            position_size_modifier=1.0,
            upcoming_event_risk="low",
            status="ready",
        )
        self.regime = RegimeResult("TRENDING_UP", 0.9, ["Trend confirmed"], 1.0, 1.0)
        self.market_sentiment = {
            "fear_greed_value": 40,
            "long_short_ratio": 0.50,
            "funding_rate": 0.0,
            "volume_anomaly": 3.2,
        }

    def test_high_score_yields_strong_buy(self) -> None:
        """A strong aligned setup should produce a strong buy."""

        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=_technical_signal(0.95),
            consensus=self.consensus,
            regime=self.regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )
        self.assertEqual(decision.action, "strong_buy")
        self.assertGreaterEqual(decision.score, 80)

    def test_filters_downgrade_entry_to_hold(self) -> None:
        """Blocked entry filters should prevent buys."""

        blocked_consensus = ConsensusResult(
            final_score=0.9,
            final_confidence=0.8,
            models_agree=False,
            trade_safe=False,
            groq_score=0.2,
            gemini_score=0.9,
            gemini_recommendation="hold",
            risk_flags=["conflicting_ai_signals"],
            reasoning="Conflict",
            key_levels={},
            pattern_signals=[{"severity": "critical"}],
            pattern_score=-0.9,
            position_size_modifier=0.25,
            upcoming_event_risk="extreme",
            status="uncertain",
        )
        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=_technical_signal(0.95),
            consensus=blocked_consensus,
            regime=self.regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )
        self.assertEqual(decision.action, "hold")

    def test_low_score_can_signal_sell(self) -> None:
        """A weak setup should signal sell or strong sell."""

        bearish_consensus = ConsensusResult(
            final_score=0.1,
            final_confidence=0.9,
            models_agree=True,
            trade_safe=True,
            groq_score=0.1,
            gemini_score=0.1,
            gemini_recommendation="strong_sell",
            risk_flags=[],
            reasoning="Bearish",
            key_levels={},
            pattern_signals=[],
            pattern_score=0.0,
            position_size_modifier=1.0,
            upcoming_event_risk="low",
            status="ready",
        )
        bearish_signal = _technical_signal(0.05)
        bearish_signal.trend = "down"
        bearish_signal.macd_signal = "bearish"
        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=bearish_signal,
            consensus=bearish_consensus,
            regime=RegimeResult("TRENDING_DOWN", 0.9, ["Downtrend"], 1.0, 1.0),
            market_sentiment={"fear_greed_value": 85, "long_short_ratio": 0.7, "funding_rate": 0.02, "volume_anomaly": 1.0},
            has_open_position=True,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )
        self.assertIn(decision.action, {"sell", "strong_sell"})


if __name__ == "__main__":
    unittest.main()
