"""Risk management rules and position sizing."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from config import Settings
from models import AccountSnapshot, OrderRequest, Position, SignalDecision, TechnicalSignal


CORRELATION_GROUPS: dict[str, list[str]] = {
    "risk_on_crypto": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"],
    "risk_on_equity": ["SPY", "QQQ", "NASDAQ", "SP500"],
    "commodities_energy": ["OIL/USDT", "CRUDE/USDT"],
    "commodities_metals": ["GOLD/USDT", "XAU/USDT", "SILVER/USDT"],
}

CORRELATION_GROUP_EXPOSURE_LIMIT = 0.15
CORRELATION_SAME_GROUP_SIZE_CUT = 0.40
CORRELATION_EQUITY_EXPOSURE_SIZE_CUT = 0.30
CORRELATION_EQUITY_LONGS_THRESHOLD = 2


@dataclass(slots=True)
class RiskCheck:
    """Risk approval output for a proposed trade."""

    approved: bool
    reason: str
    order_request: OrderRequest | None = None


@dataclass(slots=True)
class CorrelationFilterResult:
    """Outcome of the pre-trade correlation exposure check."""

    triggered: bool
    blocked: bool
    size_multiplier: float
    reason: str
    action_taken: str
    existing_positions: list[str]


def _correlation_group(asset: str) -> str | None:
    """Return the name of the correlation group containing asset, if any."""

    for group_name, members in CORRELATION_GROUPS.items():
        if asset in members:
            return group_name
    return None


def _is_crypto_asset(asset: str) -> bool:
    """Return True if asset should be treated as crypto for correlation purposes."""

    if asset in CORRELATION_GROUPS["risk_on_equity"]:
        return False
    if asset in CORRELATION_GROUPS["commodities_energy"] or asset in CORRELATION_GROUPS["commodities_metals"]:
        return False
    return "/" in asset


def check_correlation_filter(
    asset: str,
    side: str,
    positions: dict[str, Position],
    account: AccountSnapshot,
) -> CorrelationFilterResult:
    """Check correlation exposure rules before opening a new long position."""

    open_longs = {symbol: position for symbol, position in positions.items() if position.side == "buy"}

    if side != "buy":
        result = CorrelationFilterResult(
            triggered=False,
            blocked=False,
            size_multiplier=1.0,
            reason="New signal is not a long entry",
            action_taken="none",
            existing_positions=sorted(open_longs),
        )
        _log_correlation_decision(asset, side, result)
        return result

    size_multiplier = 1.0
    actions: list[str] = []
    reasons: list[str] = []
    blocked = False

    group_name = _correlation_group(asset)
    if group_name is not None:
        group_members = set(CORRELATION_GROUPS[group_name])
        group_positions = {symbol: position for symbol, position in open_longs.items() if symbol in group_members}
        if group_positions:
            group_exposure = sum(position.size * position.entry_price for position in group_positions.values())
            exposure_pct = (group_exposure / account.equity) if account.equity else 0.0
            if exposure_pct > CORRELATION_GROUP_EXPOSURE_LIMIT:
                blocked = True
                actions.append("correlation_filter_blocked")
                reasons.append(
                    f"{group_name} exposure {exposure_pct:.2%} exceeds {CORRELATION_GROUP_EXPOSURE_LIMIT:.0%} limit "
                    f"with open longs {sorted(group_positions)}"
                )
            else:
                size_multiplier *= 1.0 - CORRELATION_SAME_GROUP_SIZE_CUT
                actions.append("reduced_same_group_exposure")
                reasons.append(
                    f"{group_name} exposure {exposure_pct:.2%} within {CORRELATION_GROUP_EXPOSURE_LIMIT:.0%} limit; "
                    f"reduced size {CORRELATION_SAME_GROUP_SIZE_CUT:.0%} due to open longs {sorted(group_positions)}"
                )

    if not blocked and _is_crypto_asset(asset):
        equity_members = set(CORRELATION_GROUPS["risk_on_equity"])
        equity_longs = sorted(symbol for symbol in open_longs if symbol in equity_members)
        if len(equity_longs) >= CORRELATION_EQUITY_LONGS_THRESHOLD:
            size_multiplier *= 1.0 - CORRELATION_EQUITY_EXPOSURE_SIZE_CUT
            actions.append("reduced_equity_exposure")
            reasons.append(
                f"{len(equity_longs)} equity-index longs open {equity_longs}; "
                f"reduced crypto size {CORRELATION_EQUITY_EXPOSURE_SIZE_CUT:.0%}"
            )

    triggered = blocked or size_multiplier < 1.0
    result = CorrelationFilterResult(
        triggered=triggered,
        blocked=blocked,
        size_multiplier=round(size_multiplier, 4),
        reason="; ".join(reasons) if reasons else "No correlation conflicts detected",
        action_taken=", ".join(actions) if actions else "none",
        existing_positions=sorted(open_longs),
    )
    _log_correlation_decision(asset, side, result)
    return result


def _log_correlation_decision(asset: str, side: str, result: CorrelationFilterResult) -> None:
    """Log every correlation filter decision for audit purposes."""

    logger.bind(signal_log=True).info(
        f"Correlation filter | asset={asset} | new_signal={side} | "
        f"existing_positions={result.existing_positions} | action_taken={result.action_taken} | "
        f"reason={result.reason}"
    )


class RiskManager:
    """Apply risk controls before orders are sent."""

    def __init__(self, settings: Settings) -> None:
        """Create the risk manager."""

        self.settings = settings

    def can_open_position(
        self,
        *,
        signal: SignalDecision,
        technical_signal: TechnicalSignal,
        account: AccountSnapshot,
        positions: dict[str, Position],
        price: float,
    ) -> RiskCheck:
        """Return an approved order request or a blocking reason."""

        if signal.action not in {"buy", "strong_buy"}:
            return RiskCheck(False, f"Signal action {signal.action} is not an entry")
        if self._limits_breached(account):
            return RiskCheck(False, "Account loss limit or drawdown threshold has been breached")
        if len(positions) >= self.settings.max_positions:
            return RiskCheck(False, "Maximum concurrent positions reached")
        if signal.asset in positions:
            return RiskCheck(False, "Asset already has an open position")

        correlation_result = check_correlation_filter(signal.asset, "buy", positions, account)
        if correlation_result.blocked:
            return RiskCheck(False, f"correlation_filter_blocked: {correlation_result.reason}")

        stop_loss = self.calculate_stop_loss(price, technical_signal.atr, signal.market_regime)
        take_profit = self.calculate_take_profit(price, stop_loss)
        size = self.calculate_position_size(
            account_balance=account.equity,
            available_cash=account.available_cash,
            entry_price=price,
            stop_loss_price=stop_loss,
            modifier=float(signal.breakdown["consensus"].get("position_size_modifier", signal.position_fraction))
            * correlation_result.size_multiplier,
        )
        if size <= 0:
            return RiskCheck(False, "Calculated position size is zero")

        order_request = OrderRequest(
            asset=signal.asset,
            side="buy",
            price=price,
            size=size,
            stop_loss=round(stop_loss, 4),
            take_profit=round(take_profit, 4),
            signal_score=signal.score,
            metadata={
                "signal_action": signal.action,
                "market_regime": signal.market_regime,
                "atr": technical_signal.atr,
                "pattern_matches": signal.breakdown["consensus"].get("pattern_signals", []),
                "ai_reasoning": signal.breakdown["consensus"].get("reasoning", ""),
                "correlation_filter": {
                    "triggered": correlation_result.triggered,
                    "action_taken": correlation_result.action_taken,
                    "reason": correlation_result.reason,
                    "size_multiplier": correlation_result.size_multiplier,
                },
            },
        )
        return RiskCheck(True, "Approved", order_request)

    def should_halt_new_entries(self, account: AccountSnapshot) -> bool:
        """Return True if loss controls should block new entries."""

        return self._limits_breached(account)

    def calculate_position_size(
        self,
        *,
        account_balance: float,
        available_cash: float,
        entry_price: float,
        stop_loss_price: float,
        modifier: float,
    ) -> float:
        """Calculate risk-based position size."""

        risk_amount = account_balance * self.settings.risk_per_trade * max(modifier, 0.0)
        stop_distance = max(entry_price - stop_loss_price, entry_price * 0.005)
        position_size = risk_amount / stop_distance
        max_position_value = min(account_balance * 0.10, available_cash * 0.95)
        capped_size = min(position_size, max_position_value / max(entry_price, 0.0001))
        return round(max(capped_size, 0.0), 8)

    def calculate_stop_loss(self, entry_price: float, atr: float, regime: str) -> float:
        """Calculate ATR-based stop loss by regime."""

        regime_upper = regime.upper()
        if "VOLATILE" in regime_upper:
            stop = entry_price - (3.0 * atr)
        elif "RANGING" in regime_upper:
            stop = entry_price - (2.0 * atr)
        else:
            stop = entry_price - (1.5 * atr)
        minimum_distance = entry_price * 0.005
        return entry_price - max(entry_price - stop, minimum_distance)

    def calculate_take_profit(self, entry_price: float, stop_loss: float) -> float:
        """Calculate take-profit from reward/risk."""

        return entry_price + ((entry_price - stop_loss) * self.settings.min_reward_risk)

    def _limits_breached(self, account: AccountSnapshot) -> bool:
        """Return True if any account loss limit is exceeded."""

        if account.peak_equity <= 0:
            return False
        drawdown = max((account.peak_equity - account.equity) / account.peak_equity, 0.0)
        return (
            account.daily_pnl <= -(account.peak_equity * self.settings.daily_loss_limit)
            or account.weekly_pnl <= -(account.peak_equity * self.settings.weekly_loss_limit)
            or drawdown >= self.settings.max_drawdown
        )
