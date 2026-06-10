"""Final signal aggregation across technical and sentiment layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from config import Settings
from execution.risk_manager import CorrelationFilterResult, check_correlation_filter
from models import AccountSnapshot, ConsensusResult, Position, RegimeResult, SignalDecision, TechnicalSignal
from utils import clamp


@dataclass(slots=True)
class SignalAggregator:
    """Combine all sub-signals into an actionable trade decision."""

    settings: Settings

    def decide(
        self,
        *,
        asset: str,
        technical_signal: TechnicalSignal,
        consensus: ConsensusResult,
        regime: RegimeResult,
        market_sentiment: dict[str, Any],
        has_open_position: bool,
        daily_limit_breached: bool,
        weekly_limit_breached: bool,
        economic_event_blocked: bool,
        briefing_complete: bool,
        selected_assets: list[str],
        positions: dict[str, Position] | None = None,
        account: AccountSnapshot | None = None,
    ) -> SignalDecision:
        """Build the final trade decision."""

        technical_points = technical_signal.technical_score * 40
        ai_points = consensus.final_score * 40
        sentiment_points = self._market_sentiment_points(market_sentiment)
        score = round(technical_points + ai_points + sentiment_points, 2)

        positions = positions or {}
        account = account or AccountSnapshot(
            equity=0.0, available_cash=0.0, daily_pnl=0.0, weekly_pnl=0.0, peak_equity=0.0, open_positions=0
        )
        would_be_buy = score >= 65
        correlation_result: CorrelationFilterResult = (
            check_correlation_filter(asset, "buy", positions, account)
            if would_be_buy
            else CorrelationFilterResult(
                triggered=False,
                blocked=False,
                size_multiplier=1.0,
                reason="Score below buy threshold",
                action_taken="none",
                existing_positions=sorted(symbol for symbol, position in positions.items() if position.side == "buy"),
            )
        )

        filters = {
            "trade_safe": consensus.trade_safe,
            "models_agree": consensus.models_agree,
            "regime_allowed": regime.regime not in {"UNCERTAIN", "TRENDING_DOWN"},
            "no_existing_position": not has_open_position,
            "daily_limit_ok": not daily_limit_breached,
            "weekly_limit_ok": not weekly_limit_breached,
            "briefing_complete": briefing_complete,
            "selected_asset": asset in selected_assets,
            "no_critical_pattern": not any(str(match.get("severity", "")).lower() == "critical" for match in consensus.pattern_signals),
            "event_risk_ok": consensus.upcoming_event_risk != "extreme",
            "economic_window_ok": not economic_event_blocked,
            # True (passes) unless the correlation filter rejects the trade outright; size cuts
            # are applied separately and don't block entry on their own.
            "correlation_filter_triggered": not correlation_result.blocked,
        }
        eligible_to_buy = all(filters.values())

        reasons = [
            f"Technical points: {technical_points:.2f}/40",
            f"AI points: {ai_points:.2f}/40",
            f"Market sentiment points: {sentiment_points:.2f}/20",
            f"Regime: {regime.regime}",
        ]

        position_modifier = consensus.position_size_modifier * regime.position_size_multiplier
        if score >= 80 and eligible_to_buy:
            action = "strong_buy"
            position_fraction = position_modifier
        elif score >= 65 and eligible_to_buy:
            action = "buy"
            position_fraction = position_modifier * 0.5
        elif score < 25:
            action = "strong_sell"
            position_fraction = 0.0
        elif score < 40:
            action = "sell"
            position_fraction = 0.0
        else:
            action = "hold"
            position_fraction = 0.0

        if not eligible_to_buy and action in {"buy", "strong_buy"}:
            action = "hold"
            position_fraction = 0.0
            reasons.append("Buy filters blocked entry")

        for filter_name, passed in filters.items():
            if not passed:
                reasons.append(f"Filter blocked: {filter_name}")

        return SignalDecision(
            asset=asset,
            score=clamp(score, 0.0, 100.0),
            action=action,
            position_fraction=round(position_fraction, 4),
            reasons=reasons,
            trade_safe=consensus.trade_safe,
            models_agree=consensus.models_agree,
            market_regime=regime.regime,
            breakdown={
                "technical_points": round(technical_points, 2),
                "ai_points": round(ai_points, 2),
                "market_sentiment_points": round(sentiment_points, 2),
                "technical": technical_signal.to_dict(),
                "consensus": consensus.to_dict(),
                "regime": regime.to_dict(),
                "market_sentiment": market_sentiment,
                "filters": filters,
                "correlation_filter": {
                    "triggered": correlation_result.triggered,
                    "blocked": correlation_result.blocked,
                    "size_multiplier": correlation_result.size_multiplier,
                    "action_taken": correlation_result.action_taken,
                    "reason": correlation_result.reason,
                    "existing_positions": correlation_result.existing_positions,
                },
                "pattern_matches": consensus.pattern_signals,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    def _market_sentiment_points(self, market_sentiment: dict[str, Any]) -> float:
        """Convert market sentiment measures into a 20-point score."""

        fear_greed = market_sentiment.get("fear_greed_value")
        long_short_ratio = market_sentiment.get("long_short_ratio")
        funding_rate = market_sentiment.get("funding_rate")

        fear_greed_points = 5.0
        if fear_greed is not None:
            fear_greed_points = clamp((100 - abs(fear_greed - 50)) / 10, 0.0, 10.0)

        ls_points = 2.5
        if long_short_ratio is not None:
            if long_short_ratio > 0.65:
                ls_points = 1.0
            elif long_short_ratio < 0.35:
                ls_points = 4.0

        funding_points = 2.5
        if funding_rate is not None:
            if funding_rate > 0.0001:
                funding_points = 1.0
            elif funding_rate < 0:
                funding_points = 3.5

        return round(clamp(fear_greed_points + ls_points + funding_points, 0.0, 20.0), 2)
