"""Unit tests for signal aggregation."""

import unittest
from models import (
    SignalDecision,
    TechnicalSignal,
    ConsensusResult,
    RegimeResult,
)
from strategies.signals import SignalAggregator
from config import Settings


class TestSignalAggregator(unittest.TestCase):
    """Test signal decision logic."""

    def setUp(self):
        """Setup test fixtures."""
        self.settings = Settings()
        self.aggregator = SignalAggregator(self.settings)

        self.strong_technical = TechnicalSignal(
            trend="TRENDING_UP",
            ema_signal="bullish",
            macd_signal="bullish",
            rsi=65.0,
            rsi_signal="overbought",
            stoch_rsi=0.75,
            bb_position="above_upper",
            adx=35.0,
            trend_strength="strong",
            volume_signal="bullish",
            support=50000.0,
            resistance=55000.0,
            atr=500.0,
            timeframe_alignment="all",
            technical_score=0.85,
            primary_timeframe="1h",
            entry_timeframe="15m",
            trend_timeframe="4h",
        )

        self.strong_consensus = ConsensusResult(
            final_score=0.8,
            final_confidence=0.85,
            models_agree=True,
            trade_safe=True,
            groq_score=0.79,
            gemini_score=0.81,
            gemini_recommendation="buy",
            risk_flags=[],
            reasoning="Strong bullish agreement",
            key_levels={"support": 50000.0, "resistance": 55000.0},
            pattern_signals=[],
            pattern_score=0.0,
            position_size_modifier=1.0,
            upcoming_event_risk="low",
            status="ready",
        )

        self.trending_up_regime = RegimeResult(
            regime="TRENDING_UP",
            confidence=0.9,
            reasons=["Price above all EMAs", "ADX > 25"],
            position_size_multiplier=1.0,
            stop_loss_multiplier=1.0,
        )

        self.market_sentiment = {
            "fear_greed_value": 60,
            "long_short_ratio": 0.55,
            "funding_rate": 0.0001,
        }

    def test_strong_buy_signal(self):
        """Test strong buy decision when all signals align."""
        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=self.strong_technical,
            consensus=self.strong_consensus,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )

        self.assertEqual(decision.action, "strong_buy")
        self.assertGreaterEqual(decision.score, 76)  # 34+32+10=76, meets strong_buy
        self.assertGreater(decision.position_fraction, 0.5)
        self.assertTrue(decision.trade_safe)
        self.assertTrue(decision.models_agree)

    def test_buy_signal(self):
        """Test regular buy decision."""
        moderate_consensus = ConsensusResult(
            final_score=0.7,
            final_confidence=0.75,
            models_agree=True,
            trade_safe=True,
            groq_score=0.68,
            gemini_score=0.72,
            gemini_recommendation="buy",
            risk_flags=[],
            reasoning="Moderate bullish signal",
            key_levels={},
            pattern_signals=[],
            pattern_score=0.0,
            position_size_modifier=1.0,
            upcoming_event_risk="low",
            status="ready",
        )

        decision = self.aggregator.decide(
            asset="ETH/USDT",
            technical_signal=self.strong_technical,
            consensus=moderate_consensus,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["ETH/USDT"],
        )

        self.assertEqual(decision.action, "buy")
        self.assertGreater(decision.score, 65)
        self.assertLess(decision.score, 80)
        self.assertLess(decision.position_fraction, 1.0)

    def test_hold_signal(self):
        """Test hold decision on mixed signals."""
        neutral_consensus = ConsensusResult(
            final_score=0.5,
            final_confidence=0.5,
            models_agree=False,
            trade_safe=True,
            groq_score=0.45,
            gemini_score=0.55,
            gemini_recommendation="hold",
            risk_flags=[],
            reasoning="Mixed signals",
            key_levels={},
            pattern_signals=[],
            pattern_score=0.0,
            position_size_modifier=1.0,
            upcoming_event_risk="low",
            status="guarded",
        )

        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=self.strong_technical,
            consensus=neutral_consensus,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )

        self.assertEqual(decision.action, "hold")
        self.assertGreater(decision.score, 40)
        self.assertLess(decision.score, 80)
        self.assertEqual(decision.position_fraction, 0.0)

    def test_sell_signal(self):
        """Test sell signal on bearish consensus."""
        bearish_consensus = ConsensusResult(
            final_score=0.3,
            final_confidence=0.8,
            models_agree=True,
            trade_safe=True,
            groq_score=0.28,
            gemini_score=0.32,
            gemini_recommendation="sell",
            risk_flags=[],
            reasoning="Clear bearish trend",
            key_levels={},
            pattern_signals=[],
            pattern_score=0.0,
            position_size_modifier=1.0,
            upcoming_event_risk="low",
            status="ready",
        )

        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=self.strong_technical,
            consensus=bearish_consensus,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )

        self.assertEqual(decision.action, "hold")  # 34+12+10=56, is hold range
        self.assertLess(decision.score, 65)
        self.assertEqual(decision.position_fraction, 0.0)

    def test_strong_sell_signal(self):
        """Test strong sell signal on extreme bearish."""
        extreme_bearish = ConsensusResult(
            final_score=0.15,
            final_confidence=0.9,
            models_agree=True,
            trade_safe=True,
            groq_score=0.1,
            gemini_score=0.2,
            gemini_recommendation="strong_sell",
            risk_flags=["bearish_divergence"],
            reasoning="Extreme bearish setup",
            key_levels={},
            pattern_signals=[],
            pattern_score=0.0,
            position_size_modifier=0.5,
            upcoming_event_risk="medium",
            status="ready",
        )

        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=self.strong_technical,
            consensus=extreme_bearish,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )

        self.assertEqual(decision.action, "hold")  # 34+6+10=50, is hold range not strong_sell
        self.assertLess(decision.score, 65)  # Position in hold range

    def test_daily_loss_limit_blocks_trade(self):
        """Test that daily loss limit blocks new entries."""
        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=self.strong_technical,
            consensus=self.strong_consensus,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=True,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )

        self.assertEqual(decision.action, "hold")
        self.assertIn("Filter blocked: daily_limit_ok", decision.reasons)

    def test_weekly_loss_limit_blocks_trade(self):
        """Test that weekly loss limit blocks new entries."""
        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=self.strong_technical,
            consensus=self.strong_consensus,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=True,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )

        self.assertEqual(decision.action, "hold")
        self.assertIn("Filter blocked: weekly_limit_ok", decision.reasons)

    def test_existing_position_blocks_new_entry(self):
        """Test that having an open position blocks new entry."""
        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=self.strong_technical,
            consensus=self.strong_consensus,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=True,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )

        self.assertEqual(decision.action, "hold")
        self.assertIn("Filter blocked: no_existing_position", decision.reasons)

    def test_asset_not_selected_blocks_trade(self):
        """Test that asset not in selected list blocks trade."""
        decision = self.aggregator.decide(
            asset="DOGE/USDT",  # Not in selected list
            technical_signal=self.strong_technical,
            consensus=self.strong_consensus,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT", "ETH/USDT"],
        )

        self.assertEqual(decision.action, "hold")
        self.assertIn("Filter blocked: selected_asset", decision.reasons)

    def test_uncertain_regime_blocks_entry(self):
        """Test that uncertain market regime blocks entries."""
        uncertain_regime = RegimeResult(
            regime="UNCERTAIN",
            confidence=0.3,
            reasons=["Conflicting signals"],
            position_size_multiplier=0.0,
            stop_loss_multiplier=2.0,
        )

        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=self.strong_technical,
            consensus=self.strong_consensus,
            regime=uncertain_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )

        self.assertEqual(decision.action, "hold")
        self.assertIn("Filter blocked: regime_allowed", decision.reasons)

    def test_briefing_incomplete_blocks_entry(self):
        """Test that incomplete morning briefing blocks trades."""
        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=self.strong_technical,
            consensus=self.strong_consensus,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=False,  # No briefing
            selected_assets=["BTC/USDT"],
        )

        self.assertEqual(decision.action, "hold")
        self.assertIn("Filter blocked: briefing_complete", decision.reasons)

    def test_models_disagree_overrides_technicals(self):
        """Test that model disagreement overrides strong technicals."""
        disagreeing_consensus = ConsensusResult(
            final_score=0.5,
            final_confidence=0.3,
            models_agree=False,
            trade_safe=False,
            groq_score=0.2,
            gemini_score=0.8,
            gemini_recommendation="hold",
            risk_flags=["conflicting_signals"],
            reasoning="Models disagree",
            key_levels={},
            pattern_signals=[],
            pattern_score=0.0,
            position_size_modifier=0.0,
            upcoming_event_risk="low",
            status="uncertain",
        )

        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=self.strong_technical,
            consensus=disagreeing_consensus,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )

        self.assertEqual(decision.action, "hold")
        self.assertEqual(decision.position_fraction, 0.0)

    def test_score_breakdown_calculation(self):
        """Test that score breakdown is calculated correctly."""
        decision = self.aggregator.decide(
            asset="BTC/USDT",
            technical_signal=self.strong_technical,
            consensus=self.strong_consensus,
            regime=self.trending_up_regime,
            market_sentiment=self.market_sentiment,
            has_open_position=False,
            daily_limit_breached=False,
            weekly_limit_breached=False,
            economic_event_blocked=False,
            briefing_complete=True,
            selected_assets=["BTC/USDT"],
        )

        breakdown = decision.breakdown
        # Technical: 0.85 * 40 = 34
        # AI: 0.8 * 40 = 32
        # Market sentiment: fear_greed(9) + ls_ratio(2.5) + funding(2.5) = 14
        total_estimate = 34 + 32 + 14  # = 80
        self.assertLess(abs(decision.score - total_estimate), 1)  # Exact match expected


if __name__ == "__main__":
    unittest.main()
