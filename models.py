"""Shared domain models for the trading bot."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


@dataclass(slots=True)
class PatternMatch:
    """Matched historical event pattern for a headline."""

    pattern_name: str
    matched_keyword: str
    headline: str
    match_score: float
    typical_impact: str
    severity: str
    confidence: float
    historical_examples: list[str] = field(default_factory=list)
    avg_drop_percent: float | None = None
    avg_gain_percent: float | None = None
    duration_days: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)


@dataclass(slots=True)
class AIAnalysis:
    """Normalized output from an AI analyzer."""

    source: str
    sentiment_score: float
    confidence: float
    risk_flags: list[str] = field(default_factory=list)
    key_themes: list[str] = field(default_factory=list)
    summary: str = ""
    trade_recommendation: str = "hold"
    reasoning: str = ""
    macro_risks: list[str] = field(default_factory=list)
    time_horizon: str = "medium"
    key_levels: dict[str, float] = field(default_factory=dict)
    pattern_influence: str = ""
    upcoming_event_risk: str = "low"
    raw_payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


@dataclass(slots=True)
class ConsensusResult:
    """Combined AI signal after consensus weighting."""

    final_score: float
    final_confidence: float
    models_agree: bool
    trade_safe: bool
    groq_score: float | None
    gemini_score: float | None
    gemini_recommendation: str
    risk_flags: list[str] = field(default_factory=list)
    reasoning: str = ""
    key_levels: dict[str, float] = field(default_factory=dict)
    pattern_signals: list[dict[str, Any]] = field(default_factory=list)
    pattern_score: float = 0.0
    position_size_modifier: float = 1.0
    upcoming_event_risk: str = "low"
    status: str = "ready"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)


@dataclass(slots=True)
class TechnicalSignal:
    """Structured technical analysis output."""

    trend: str
    ema_signal: str
    macd_signal: str
    rsi: float
    rsi_signal: str
    stoch_rsi: float
    bb_position: str
    adx: float
    trend_strength: str
    volume_signal: str
    support: float
    resistance: float
    atr: float
    timeframe_alignment: str
    technical_score: float
    primary_timeframe: str
    entry_timeframe: str
    trend_timeframe: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)


@dataclass(slots=True)
class SentimentSnapshot:
    """Aggregated non-AI sentiment inputs."""

    asset: str
    headlines: list[str]
    fear_greed_value: int | None
    fear_greed_label: str | None
    long_short_ratio: float | None
    funding_rate: float | None
    google_trends_score: float | None
    google_trends_direction: str = "flat"
    google_trends_spike: bool = False
    volume_anomaly: float | None = None
    aggregated_score: float = 0.5
    news_score: float = 0.5
    sources_available: int = 0
    data_freshness: str = "stale"
    btc_dominance: float | None = None
    upcoming_events: list[dict[str, Any]] = field(default_factory=list)
    pattern_matches: list[dict[str, Any]] = field(default_factory=list)
    market_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)


@dataclass(slots=True)
class RegimeResult:
    """Detected market regime for one symbol."""

    regime: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    position_size_multiplier: float = 1.0
    stop_loss_multiplier: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)


@dataclass(slots=True)
class SignalDecision:
    """Final aggregated trade decision."""

    asset: str
    score: float
    action: str
    position_fraction: float
    reasons: list[str] = field(default_factory=list)
    trade_safe: bool = False
    models_agree: bool = False
    market_regime: str = "UNCERTAIN"
    breakdown: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


@dataclass(slots=True)
class Position:
    """Current open position."""

    asset: str
    side: str
    size: float
    entry_price: float
    stop_loss: float
    take_profit: float
    signal_score: float
    trade_id: str
    pattern_matches: list[dict[str, Any]] = field(default_factory=list)
    ai_reasoning: str = ""
    opened_at: datetime = field(default_factory=utc_now)
    trailing_active: bool = False
    trail_price: float | None = None
    trail_distance: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        payload = asdict(self)
        payload["opened_at"] = self.opened_at.isoformat()
        return payload


@dataclass(slots=True)
class TradeRecord:
    """Persisted trade record."""

    trade_id: str
    asset: str
    side: str
    entry_price: float
    exit_price: float | None
    size: float
    pnl: float | None
    signal_score: float
    status: str
    entry_time: datetime
    exit_time: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        payload = asdict(self)
        payload["entry_time"] = self.entry_time.isoformat()
        payload["exit_time"] = self.exit_time.isoformat() if self.exit_time else None
        return payload


@dataclass(slots=True)
class AccountSnapshot:
    """Current account equity state."""

    equity: float
    available_cash: float
    daily_pnl: float
    weekly_pnl: float
    peak_equity: float
    open_positions: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)


@dataclass(slots=True)
class OrderRequest:
    """Order submission request."""

    asset: str
    side: str
    price: float
    size: float
    stop_loss: float
    take_profit: float
    signal_score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)
