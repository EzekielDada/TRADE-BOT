"""Market regime detection."""

from __future__ import annotations

from config import Settings
from models import RegimeResult, TechnicalSignal


class MarketRegimeDetector:
    """Detect the current market regime from technical context."""

    def __init__(self, settings: Settings) -> None:
        """Create a regime detector."""

        self.settings = settings

    def detect(self, signal: TechnicalSignal) -> RegimeResult:
        """Classify the market regime for an asset."""

        metadata = signal.metadata
        reasons: list[str] = []

        if metadata.get("volatility_spike"):
            reasons.append("ATR is above 2x its recent average")
            return RegimeResult(
                regime="VOLATILE",
                confidence=0.8,
                reasons=reasons,
                position_size_multiplier=0.5,
                stop_loss_multiplier=1.25,
            )

        if signal.trend == "up" and signal.adx > 25 and signal.volume_signal == "high":
            reasons.append("Price is above key EMAs with strong ADX and rising volume")
            return RegimeResult("TRENDING_UP", 0.85, reasons, 1.0, 1.0)

        if signal.trend == "down" and signal.adx > 25:
            reasons.append("Price is below key EMAs with strong ADX")
            return RegimeResult("TRENDING_DOWN", 0.85, reasons, 1.0, 1.0)

        if signal.adx < 20 and signal.bb_position in {"near_upper", "near_lower", "middle"}:
            reasons.append("Low ADX with oscillation inside Bollinger Bands")
            return RegimeResult("RANGING", 0.75, reasons, 1.0, 1.0)

        reasons.append("Signals are mixed across the current timeframe stack")
        return RegimeResult("UNCERTAIN", 0.4, reasons, 0.0, 1.0)
