"""Unit tests for the AI consensus engine."""

from __future__ import annotations

import unittest

from ai.consensus import ConsensusEngine
from models import AIAnalysis


class ConsensusEngineTests(unittest.TestCase):
    """Verify consensus weighting and safety rules."""

    def setUp(self) -> None:
        """Create a fresh engine for each test."""

        self.engine = ConsensusEngine()

    def test_agreeing_models_boost_confidence(self) -> None:
        """Confidence should be boosted when scores are closely aligned."""

        groq = AIAnalysis(source="groq", sentiment_score=0.62, confidence=0.7)
        gemini = AIAnalysis(source="gemini", sentiment_score=0.68, confidence=0.8, trade_recommendation="buy")
        result = self.engine.combine(groq, gemini)
        self.assertTrue(result.models_agree)
        self.assertTrue(result.trade_safe)
        self.assertGreater(result.final_confidence, 0.74)

    def test_disagreement_blocks_trading(self) -> None:
        """Large score gaps should mark the signal uncertain."""

        groq = AIAnalysis(source="groq", sentiment_score=0.20, confidence=0.8)
        gemini = AIAnalysis(source="gemini", sentiment_score=0.70, confidence=0.9, trade_recommendation="sell")
        result = self.engine.combine(groq, gemini)
        self.assertFalse(result.models_agree)
        self.assertFalse(result.trade_safe)
        self.assertEqual(result.status, "uncertain")

    def test_hard_risk_keywords_force_unsafe(self) -> None:
        """Hard risk keywords should always block trade safety."""

        groq = AIAnalysis(source="groq", sentiment_score=0.60, confidence=0.8, risk_flags=["SEC investigation"])
        gemini = AIAnalysis(source="gemini", sentiment_score=0.58, confidence=0.8, trade_recommendation="hold")
        result = self.engine.combine(groq, gemini)
        self.assertFalse(result.trade_safe)

    def test_position_modifier_reduced_by_pattern_risk(self) -> None:
        """Large pattern impacts should reduce position size."""

        groq = AIAnalysis(source="groq", sentiment_score=0.62, confidence=0.7)
        gemini = AIAnalysis(source="gemini", sentiment_score=0.68, confidence=0.8, trade_recommendation="buy")
        patterns = [{"severity": "high", "avg_drop_percent": 30, "pattern_name": "regulation_ban"}]
        result = self.engine.combine(groq, gemini, pattern_signals=patterns, pattern_score=-0.2)
        self.assertLess(result.position_size_modifier, 1.0)

    def test_critical_patterns_always_block(self) -> None:
        """Critical patterns should always block new trades."""

        gemini = AIAnalysis(source="gemini", sentiment_score=0.63, confidence=0.71, trade_recommendation="buy")
        result = self.engine.combine(None, gemini, pattern_signals=[{"severity": "critical", "pattern_name": "exchange_collapse"}], pattern_score=-0.9)
        self.assertFalse(result.trade_safe)


if __name__ == "__main__":
    unittest.main()
