"""Consensus logic combining Groq and Gemini analyses."""

from __future__ import annotations

from dataclasses import dataclass

from models import AIAnalysis, ConsensusResult
from utils import clamp


RISK_KEYWORDS = {
    "regulation",
    "ban",
    "hack",
    "lawsuit",
    "sec",
    "cbn",
    "crash",
    "depeg",
    "insolvent",
    "frozen",
    "shutdown",
    "attack",
}


@dataclass(slots=True)
class ConsensusEngine:
    """Combine multiple AI analyses into a single trade decision."""

    agreement_threshold: float = 0.15
    disagreement_threshold: float = 0.30

    def combine(
        self,
        groq_result: AIAnalysis | None,
        gemini_result: AIAnalysis | None,
        *,
        pattern_signals: list[dict[str, object]] | None = None,
        pattern_score: float = 0.0,
    ) -> ConsensusResult:
        """Return the final consensus signal."""

        pattern_signals = pattern_signals or []
        upcoming_event_risk = gemini_result.upcoming_event_risk if gemini_result else "low"
        if groq_result is None and gemini_result is None:
            return ConsensusResult(
                final_score=0.5,
                final_confidence=0.0,
                models_agree=False,
                trade_safe=False,
                groq_score=None,
                gemini_score=None,
                gemini_recommendation="hold",
                risk_flags=["all_ai_unavailable"],
                reasoning="Both AI analyzers are unavailable. Manage open positions only.",
                pattern_signals=pattern_signals,
                pattern_score=pattern_score,
                position_size_modifier=0.0,
                upcoming_event_risk=upcoming_event_risk,
                status="ai_unavailable",
            )

        if groq_result is None:
            return self._single_model_consensus(gemini_result, pattern_signals, pattern_score)
        if gemini_result is None:
            return self._single_model_consensus(groq_result, pattern_signals, pattern_score)

        gap = abs(groq_result.sentiment_score - gemini_result.sentiment_score)
        combined_flags = list(dict.fromkeys(groq_result.risk_flags + gemini_result.risk_flags + gemini_result.macro_risks))
        trade_safe = not self._contains_hard_risk(combined_flags)
        if self._has_critical_pattern(pattern_signals) or pattern_score <= -0.60:
            trade_safe = False
            combined_flags.append("critical_pattern_risk")

        if gap > self.disagreement_threshold:
            return ConsensusResult(
                final_score=round((groq_result.sentiment_score + gemini_result.sentiment_score) / 2, 4),
                final_confidence=round(max(groq_result.confidence, gemini_result.confidence) * 0.75, 4),
                models_agree=False,
                trade_safe=False,
                groq_score=groq_result.sentiment_score,
                gemini_score=gemini_result.sentiment_score,
                gemini_recommendation=gemini_result.trade_recommendation,
                risk_flags=combined_flags + ["conflicting_ai_signals"],
                reasoning="AI models disagree materially, so new entries are blocked.",
                key_levels=gemini_result.key_levels,
                pattern_signals=pattern_signals,
                pattern_score=pattern_score,
                position_size_modifier=self._position_modifier(pattern_signals, pattern_score, max(groq_result.confidence, gemini_result.confidence), False),
                upcoming_event_risk=upcoming_event_risk,
                status="uncertain",
            )

        if gap <= self.agreement_threshold:
            weights = (0.5, 0.5)
            models_agree = True
        else:
            weights = self._weights(groq_result.confidence, gemini_result.confidence, strong_tilt=0.6)
            models_agree = False

        if groq_result.confidence < 0.5 or gemini_result.confidence < 0.5:
            weights = self._weights(groq_result.confidence, gemini_result.confidence, strong_tilt=0.7)
            models_agree = False

        final_score = (groq_result.sentiment_score * weights[0]) + (gemini_result.sentiment_score * weights[1])
        final_confidence = (groq_result.confidence * weights[0]) + (gemini_result.confidence * weights[1])
        if gap <= self.agreement_threshold:
            final_confidence *= 1.2

        position_modifier = self._position_modifier(pattern_signals, pattern_score, final_confidence, models_agree)
        return ConsensusResult(
            final_score=round(clamp(final_score, 0.0, 1.0), 4),
            final_confidence=round(clamp(final_confidence, 0.0, 1.0), 4),
            models_agree=models_agree,
            trade_safe=trade_safe,
            groq_score=groq_result.sentiment_score,
            gemini_score=gemini_result.sentiment_score,
            gemini_recommendation=gemini_result.trade_recommendation,
            risk_flags=combined_flags,
            reasoning=gemini_result.reasoning or groq_result.summary,
            key_levels=gemini_result.key_levels,
            pattern_signals=pattern_signals,
            pattern_score=pattern_score,
            position_size_modifier=position_modifier,
            upcoming_event_risk=upcoming_event_risk,
            status="ready" if trade_safe else "guarded",
        )

    def _single_model_consensus(
        self,
        result: AIAnalysis | None,
        pattern_signals: list[dict[str, object]],
        pattern_score: float,
    ) -> ConsensusResult:
        """Build a fallback consensus from one model."""

        assert result is not None
        risk_flags = list(dict.fromkeys(result.risk_flags + result.macro_risks))
        trade_safe = not self._contains_hard_risk(risk_flags) and result.confidence >= 0.5
        if self._has_critical_pattern(pattern_signals) or pattern_score <= -0.60:
            trade_safe = False
        return ConsensusResult(
            final_score=result.sentiment_score,
            final_confidence=result.confidence,
            models_agree=False,
            trade_safe=trade_safe,
            groq_score=result.sentiment_score if result.source == "groq" else None,
            gemini_score=result.sentiment_score if result.source == "gemini" else None,
            gemini_recommendation=result.trade_recommendation,
            risk_flags=risk_flags + ["single_model_mode"],
            reasoning=result.reasoning or result.summary,
            key_levels=result.key_levels,
            pattern_signals=pattern_signals,
            pattern_score=pattern_score,
            position_size_modifier=self._position_modifier(pattern_signals, pattern_score, result.confidence, False),
            upcoming_event_risk=result.upcoming_event_risk,
            status="degraded",
        )

    def _weights(self, groq_confidence: float, gemini_confidence: float, strong_tilt: float) -> tuple[float, float]:
        """Choose consensus weights from model confidence."""

        if groq_confidence == gemini_confidence:
            return (0.5, 0.5)
        if groq_confidence > gemini_confidence:
            return (strong_tilt, 1 - strong_tilt)
        return (1 - strong_tilt, strong_tilt)

    def _contains_hard_risk(self, flags: list[str]) -> bool:
        """Check whether any risk flag should block trading outright."""

        normalized = " ".join(flags).lower()
        return any(keyword in normalized for keyword in RISK_KEYWORDS)

    def _has_critical_pattern(self, signals: list[dict[str, object]]) -> bool:
        """Return True if any pattern signal is critical."""

        return any(str(item.get("severity", "")).lower() == "critical" for item in signals)

    def _position_modifier(
        self,
        pattern_signals: list[dict[str, object]],
        pattern_score: float,
        overall_confidence: float,
        models_agree: bool,
    ) -> float:
        """Calculate position-size modifier from risk factors."""

        modifier = 1.0
        if any(
            float(item.get("avg_drop_percent") or item.get("avg_gain_percent") or 0.0) > 20
            for item in pattern_signals
        ):
            modifier *= 0.50
        if overall_confidence < 0.60:
            modifier *= 0.75
        if not models_agree:
            modifier *= 0.50
        if pattern_score <= -0.60:
            modifier *= 0.50
        return round(clamp(modifier, 0.0, 1.0), 4)
