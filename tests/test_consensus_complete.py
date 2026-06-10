"""Unit tests for consensus engine."""

import unittest
from models import AIAnalysis, ConsensusResult
from ai.consensus import ConsensusEngine, RISK_KEYWORDS


class TestConsensusEngine(unittest.TestCase):
    """Test consensus logic."""

    def setUp(self):
        """Setup test fixtures."""
        self.engine = ConsensusEngine()
        self.groq_bullish = AIAnalysis(
            source="groq",
            sentiment_score=0.75,
            confidence=0.8,
            key_themes=["bullish"],
            risk_flags=[],
            summary="Strong bullish signal",
        )
        self.gemini_bullish = AIAnalysis(
            source="gemini",
            sentiment_score=0.78,
            confidence=0.85,
            key_themes=["bullish"],
            macro_risks=[],
            trade_recommendation="buy",
            reasoning="Positive trend with support",
        )
        self.groq_bearish = AIAnalysis(
            source="groq",
            sentiment_score=0.25,
            confidence=0.7,
            key_themes=["bearish"],
            risk_flags=["high_volatility"],
            summary="Bearish pressure",
        )
        self.gemini_bearish = AIAnalysis(
            source="gemini",
            sentiment_score=0.22,
            confidence=0.75,
            key_themes=["bearish"],
            macro_risks=["inflation_risk"],
            trade_recommendation="sell",
            reasoning="Downtrend confirmed",
        )

    def test_both_models_bullish_agreement(self):
        """Test when both models agree bullish."""
        result = self.engine.combine(self.groq_bullish, self.gemini_bullish)

        self.assertTrue(result.models_agree)
        self.assertGreater(result.final_score, 0.7)
        self.assertGreater(result.final_confidence, 0.7)
        self.assertTrue(result.trade_safe)
        self.assertEqual(result.status, "ready")

    def test_both_models_bearish_agreement(self):
        """Test when both models agree bearish."""
        result = self.engine.combine(self.groq_bearish, self.gemini_bearish)

        self.assertTrue(result.models_agree)
        self.assertLess(result.final_score, 0.4)
        self.assertTrue(result.trade_safe)  # Bearish is safe to act on

    def test_models_disagreement_large_gap(self):
        """Test when models disagree significantly (>0.30)."""
        result = self.engine.combine(self.groq_bullish, self.groq_bearish)

        # Gap is 0.5, exceeds 0.30 threshold
        self.assertFalse(result.models_agree)
        self.assertFalse(result.trade_safe)  # Trade blocked
        self.assertEqual(result.status, "uncertain")
        self.assertIn("conflicting_ai_signals", result.risk_flags)

    def test_models_partial_disagreement(self):
        """Test when models disagree within 0.15-0.30 range."""
        gemini_medium = AIAnalysis(
            source="gemini",
            sentiment_score=0.6,
            confidence=0.8,
            key_themes=["neutral_bullish"],
            macro_risks=[],
            trade_recommendation="hold",
            reasoning="Mixed signals",
        )
        result = self.engine.combine(self.groq_bullish, gemini_medium)

        # Gap is 0.15, within partial disagreement zone
        self.assertFalse(result.models_agree)
        self.assertTrue(result.trade_safe)  # Still tradeable

    def test_low_confidence_both_models(self):
        """Test when both models have low confidence."""
        low_conf_groq = AIAnalysis(
            source="groq",
            sentiment_score=0.5,
            confidence=0.3,
            key_themes=[],
            risk_flags=[],
            summary="Unclear",
        )
        low_conf_gemini = AIAnalysis(
            source="gemini",
            sentiment_score=0.52,
            confidence=0.35,
            key_themes=[],
            macro_risks=[],
            trade_recommendation="hold",
            reasoning="Not enough data",
        )
        result = self.engine.combine(low_conf_groq, low_conf_gemini)

        # Low confidence should reduce position size
        self.assertLess(result.final_confidence, 0.5)
        self.assertLess(result.position_size_modifier, 1.0)

    def test_hard_risk_keywords_block_trades(self):
        """Test that hard risk keywords prevent trading."""
        risky_groq = AIAnalysis(
            source="groq",
            sentiment_score=0.8,
            confidence=0.9,
            key_themes=["bullish"],
            risk_flags=["SEC enforcement action"],
            summary="Positive but regulated",
        )
        result = self.engine.combine(risky_groq, self.gemini_bullish)

        # Code correctly blocks trading when risk keywords detected
        self.assertFalse(result.trade_safe)
        # Risk flags should contain the SEC warning
        self.assertTrue(any("SEC" in str(flag) for flag in result.risk_flags))

    def test_single_groq_only(self):
        """Test fallback to single Groq model."""
        result = self.engine.combine(self.groq_bullish, None)

        self.assertEqual(result.groq_score, self.groq_bullish.sentiment_score)
        self.assertIsNone(result.gemini_score)
        self.assertIn("single_model_mode", result.risk_flags)
        # Should still be tradeable if confident
        self.assertTrue(result.trade_safe)

    def test_single_gemini_only(self):
        """Test fallback to single Gemini model."""
        result = self.engine.combine(None, self.gemini_bullish)

        self.assertIsNone(result.groq_score)
        self.assertEqual(result.gemini_score, self.gemini_bullish.sentiment_score)
        self.assertIn("single_model_mode", result.risk_flags)

    def test_both_models_unavailable(self):
        """Test when both AI models are down."""
        result = self.engine.combine(None, None)

        self.assertEqual(result.final_confidence, 0.0)
        self.assertFalse(result.trade_safe)
        self.assertEqual(result.position_size_modifier, 0.0)
        self.assertIn("all_ai_unavailable", result.risk_flags)

    def test_critical_pattern_blocks_trade(self):
        """Test that critical patterns block trades even with bullish AI."""
        critical_pattern = {
            "pattern_name": "exchange_collapse",
            "severity": "critical",
            "typical_impact": "bearish",
        }
        result = self.engine.combine(
            self.groq_bullish,
            self.gemini_bullish,
            pattern_signals=[critical_pattern],
        )

        self.assertFalse(result.trade_safe)
        self.assertIn("critical_pattern_risk", result.risk_flags)

    def test_pattern_score_extreme_bearish_blocks_trade(self):
        """Test that extreme bearish pattern score blocks trades."""
        result = self.engine.combine(
            self.groq_bullish,
            self.gemini_bullish,
            pattern_score=-0.75,  # Below -0.60 threshold
        )

        self.assertFalse(result.trade_safe)

    def test_position_size_modifier_calculations(self):
        """Test position size modifiers are calculated correctly."""
        # Models disagree → 50% reduction
        result = self.engine.combine(self.groq_bullish, self.groq_bearish)
        # When models disagree significantly, position is reduced to 50%
        self.assertEqual(result.position_size_modifier, 0.5)

        # Low confidence → combined reduction
        # groq (0.8) + low_conf (0.4): agreement on score, but confidence boost applied
        # Final confidence will be high enough that only no special reduction applies
        low_conf = AIAnalysis(
            source="gemini",
            sentiment_score=0.25,  # Disagree with groq_bullish (0.75)
            confidence=0.4,
            key_themes=[],
            macro_risks=[],
            trade_recommendation="hold",
            reasoning="Weak signal",
        )
        result = self.engine.combine(self.groq_bullish, low_conf)
        # Gap > 0.30, so models_agree=False → 50% modifier
        self.assertEqual(result.position_size_modifier, 0.5)

    def test_confidence_boost_when_models_agree(self):
        """Test that confidence is boosted when models agree closely."""
        # Both at 0.8, gap < 0.15
        result = self.engine.combine(self.groq_bullish, self.gemini_bullish)
        avg_input_conf = (self.groq_bullish.confidence + self.gemini_bullish.confidence) / 2
        # Should be boosted by 20%
        self.assertGreater(result.final_confidence, avg_input_conf * 1.15)


if __name__ == "__main__":
    unittest.main()
