"""Order execution, persistence, and portfolio tracking."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from config import Settings
from models import AccountSnapshot, OrderRequest, Position, TradeRecord
from storage import Storage
from utils import with_retry

try:
    import ccxt.async_support as ccxt_async
except ImportError:  # pragma: no cover - optional dependency.
    ccxt_async = None  # type: ignore[assignment]


class OrderManager:
    """Manage paper and live order execution."""

    def __init__(self, settings: Settings, storage: Storage) -> None:
        """Create the order manager."""

        self.settings = settings
        self.storage = storage
        self.positions = self._load_positions()
        self.realized_pnl = float(self.storage.get_state("realized_pnl", 0.0))
        self.weekly_realized_pnl = float(self.storage.get_state("weekly_realized_pnl", 0.0))
        self.available_cash = float(self.storage.get_state("available_cash", settings.initial_cash))
        self.peak_equity = float(self.storage.get_state("peak_equity", settings.initial_cash))
        self.exchange = self._build_exchange() if not settings.paper_trading else None

    def account_snapshot(self, latest_prices: dict[str, float]) -> AccountSnapshot:
        """Return the current account snapshot."""

        unrealized = 0.0
        for symbol, position in self.positions.items():
            current_price = latest_prices.get(symbol, position.entry_price)
            unrealized += (current_price - position.entry_price) * position.size
        equity = self.available_cash + sum(position.entry_price * position.size for position in self.positions.values()) + unrealized
        self.peak_equity = max(self.peak_equity, equity)
        self._persist_state()
        return AccountSnapshot(
            equity=round(equity, 2),
            available_cash=round(self.available_cash, 2),
            daily_pnl=round(self._period_pnl(days=1), 2),
            weekly_pnl=round(self._period_pnl(days=7), 2),
            peak_equity=round(self.peak_equity, 2),
            open_positions=len(self.positions),
        )

    async def execute_entry(self, order: OrderRequest) -> Position:
        """Execute an entry order in paper or live mode."""

        return await (self._paper_entry(order) if self.settings.paper_trading else self._live_entry(order))

    async def manage_open_positions(self, latest_prices: dict[str, float]) -> list[TradeRecord]:
        """Update trailing stops and exit positions if stops or targets are hit."""

        closed_trades: list[TradeRecord] = []
        for symbol, position in list(self.positions.items()):
            price = latest_prices.get(symbol, position.entry_price)
            self._update_trailing_stop(position, price)
            should_exit = price <= position.stop_loss or price >= position.take_profit
            if should_exit:
                record = await self.close_position(symbol, price)
                closed_trades.append(record)
        return closed_trades

    async def close_position(self, symbol: str, exit_price: float) -> TradeRecord:
        """Close an existing position."""

        position = self.positions[symbol]
        if self.settings.paper_trading:
            fill_price = exit_price * (1 - 0.001)
        else:
            fill_price = await self._live_close(position, exit_price)

        proceeds = fill_price * position.size
        entry_value = position.entry_price * position.size
        fees = proceeds * 0.001
        pnl = proceeds - entry_value - fees
        self.available_cash += proceeds - fees
        self.realized_pnl += pnl
        self.weekly_realized_pnl += pnl

        record = TradeRecord(
            trade_id=position.trade_id,
            asset=position.asset,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=round(fill_price, 4),
            size=position.size,
            pnl=round(pnl, 4),
            signal_score=position.signal_score,
            status="closed",
            entry_time=position.opened_at,
            exit_time=datetime.now(UTC),
        )
        self.storage.save_trade(
            {
                "trade_id": record.trade_id,
                "asset": record.asset,
                "side": record.side,
                "entry_price": record.entry_price,
                "exit_price": record.exit_price,
                "size": record.size,
                "pnl": record.pnl,
                "signal_score": record.signal_score,
                "status": record.status,
                "entry_time": record.entry_time.isoformat(),
                "exit_time": record.exit_time.isoformat() if record.exit_time else None,
                "metadata": {},
            }
        )
        del self.positions[symbol]
        self.storage.remove_position(symbol)
        self._persist_state()
        logger.bind(trade_log=True).info(f"Closed {symbol} at {fill_price:.4f} PnL={pnl:.2f}")
        return record

    async def close(self) -> None:
        """Close any live exchange resources."""

        if self.exchange:
            await self.exchange.close()

    async def refresh_settings(self, settings: Settings) -> None:
        """Apply runtime setting overrides."""

        mode_changed = self.settings.paper_trading != settings.paper_trading or self.settings.exchange != settings.exchange
        self.settings = settings
        if mode_changed:
            if self.exchange:
                await self.exchange.close()
            self.exchange = self._build_exchange() if not settings.paper_trading else None

    def recent_trades(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent trade history."""

        return self.storage.fetch_trades(limit=limit)

    def recent_positions(self) -> list[dict[str, Any]]:
        """Return current open positions."""

        return [position.to_dict() for position in self.positions.values()]

    def _load_positions(self) -> dict[str, Position]:
        """Load persisted open positions."""

        raw_positions = self.storage.load_positions()
        positions: dict[str, Position] = {}
        for symbol, payload in raw_positions.items():
            positions[symbol] = Position(
                asset=payload["asset"],
                side=payload["side"],
                size=payload["size"],
                entry_price=payload["entry_price"],
                stop_loss=payload["stop_loss"],
                take_profit=payload["take_profit"],
                signal_score=payload["signal_score"],
                trade_id=payload["trade_id"],
                pattern_matches=payload.get("pattern_matches", []),
                ai_reasoning=payload.get("ai_reasoning", ""),
                opened_at=datetime.fromisoformat(payload["opened_at"]),
                trailing_active=payload.get("trailing_active", False),
                trail_price=payload.get("trail_price"),
                trail_distance=payload.get("trail_distance"),
            )
        return positions

    async def _paper_entry(self, order: OrderRequest) -> Position:
        """Simulate a paper trade with slippage and fees."""

        fill_price = order.price * 1.001
        trade_value = fill_price * order.size
        fees = trade_value * 0.001
        self.available_cash -= trade_value + fees
        trade_id = f"paper-{uuid.uuid4().hex[:12]}"
        position = Position(
            asset=order.asset,
            side=order.side,
            size=order.size,
            entry_price=round(fill_price, 4),
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            signal_score=order.signal_score,
            trade_id=trade_id,
            pattern_matches=list(order.metadata.get("pattern_matches", [])),
            ai_reasoning=str(order.metadata.get("ai_reasoning", "")),
            trail_distance=float(order.metadata.get("atr", 0.0)),
        )
        self.positions[order.asset] = position
        self.storage.upsert_position(order.asset, position.to_dict())
        self.storage.save_trade(
            {
                "trade_id": trade_id,
                "asset": order.asset,
                "side": order.side,
                "entry_price": position.entry_price,
                "exit_price": None,
                "size": position.size,
                "pnl": None,
                "signal_score": position.signal_score,
                "status": "open",
                "entry_time": position.opened_at.isoformat(),
                "exit_time": None,
                "metadata": order.metadata,
            }
        )
        self._persist_state()
        logger.bind(trade_log=True).info(f"Opened paper trade {order.asset} at {fill_price:.4f} size={order.size}")
        return position

    async def _live_entry(self, order: OrderRequest) -> Position:
        """Submit a live entry order via CCXT."""

        if not self.exchange:
            raise RuntimeError("Live exchange client is unavailable")

        async def _submit() -> Any:
            return await self.exchange.create_order(
                symbol=order.asset,
                type="market",
                side=order.side,
                amount=order.size,
            )

        response = await with_retry(_submit, attempts=3, base_delay=5.0)
        filled_size = float(response.get("filled") or order.size)
        average_price = float(response.get("average") or order.price)
        trade_id = str(response.get("id") or f"live-{uuid.uuid4().hex[:12]}")

        position = Position(
            asset=order.asset,
            side=order.side,
            size=filled_size,
            entry_price=round(average_price, 4),
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            signal_score=order.signal_score,
            trade_id=trade_id,
            pattern_matches=list(order.metadata.get("pattern_matches", [])),
            ai_reasoning=str(order.metadata.get("ai_reasoning", "")),
            trail_distance=float(order.metadata.get("atr", 0.0)),
        )
        self.positions[order.asset] = position
        self.storage.upsert_position(order.asset, position.to_dict())
        self.storage.save_trade(
            {
                "trade_id": trade_id,
                "asset": order.asset,
                "side": order.side,
                "entry_price": position.entry_price,
                "exit_price": None,
                "size": position.size,
                "pnl": None,
                "signal_score": position.signal_score,
                "status": "open",
                "entry_time": position.opened_at.isoformat(),
                "exit_time": None,
                "metadata": {**order.metadata, "exchange_response": response},
            }
        )
        return position

    async def _live_close(self, position: Position, fallback_price: float) -> float:
        """Close a live position via CCXT."""

        if not self.exchange:
            return fallback_price

        async def _submit() -> Any:
            return await self.exchange.create_order(
                symbol=position.asset,
                type="market",
                side="sell",
                amount=position.size,
            )

        try:
            response = await with_retry(_submit, attempts=3, base_delay=5.0)
            return float(response.get("average") or fallback_price)
        except Exception:
            return fallback_price

    def _update_trailing_stop(self, position: Position, current_price: float) -> None:
        """Advance trailing stop once a trade is sufficiently profitable."""

        profit_pct = ((current_price - position.entry_price) / position.entry_price) * 100 if position.entry_price else 0.0
        if profit_pct >= 1.5:
            position.trailing_active = True
            trail_distance = position.trail_distance or abs(position.entry_price - position.stop_loss)
            trail_price = current_price - trail_distance
            position.stop_loss = max(position.stop_loss, round(trail_price, 4))
            position.trail_price = current_price
            self.storage.upsert_position(position.asset, position.to_dict())

    def _build_exchange(self) -> Any:
        """Create the live Bybit exchange client."""

        if ccxt_async is None or not hasattr(ccxt_async, self.settings.exchange):
            return None
        exchange_class = getattr(ccxt_async, self.settings.exchange)
        return exchange_class(
            {
                "apiKey": self.settings.bybit_api_key,
                "secret": self.settings.bybit_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
                **(
                    {"urls": {"api": {"public": "https://api-testnet.bybit.com", "private": "https://api-testnet.bybit.com"}}}
                    if self.settings.exchange == "bybit" and self.settings.bybit_testnet
                    else {}
                ),
            }
        )

    def _period_pnl(self, days: int) -> float:
        """Calculate realized PnL over the last N days."""

        trades = self.storage.fetch_trades(limit=500)
        cutoff = datetime.now(UTC) - timedelta(days=days)
        pnl_total = 0.0
        for trade in trades:
            if trade.get("pnl") is None or not trade.get("exit_time"):
                continue
            exit_time = datetime.fromisoformat(str(trade["exit_time"]))
            if exit_time >= cutoff:
                pnl_total += float(trade["pnl"])
        return pnl_total

    def _persist_state(self) -> None:
        """Persist portfolio summary state."""

        self.storage.set_state("available_cash", self.available_cash)
        self.storage.set_state("realized_pnl", self.realized_pnl)
        self.storage.set_state("weekly_realized_pnl", self.weekly_realized_pnl)
        self.storage.set_state("peak_equity", self.peak_equity)
        today = datetime.now(UTC).date().isoformat()
        trades = self.storage.fetch_trades(limit=500)
        closed_today = [
            trade for trade in trades
            if trade.get("exit_time") and datetime.fromisoformat(str(trade["exit_time"])).date().isoformat() == today
        ]
        wins = len([trade for trade in closed_today if trade.get("pnl", 0) and float(trade["pnl"]) > 0])
        losses = len([trade for trade in closed_today if trade.get("pnl", 0) and float(trade["pnl"]) <= 0])
        gross_pnl = sum(float(trade.get("pnl") or 0.0) for trade in closed_today)
        self.storage.save_daily_pnl(
            {
                "date": today,
                "starting_balance": self.settings.initial_cash,
                "ending_balance": round(self.available_cash, 2),
                "trades_taken": len(closed_today),
                "wins": wins,
                "losses": losses,
                "gross_pnl": round(gross_pnl, 2),
                "fees_paid": round(sum(abs(float(trade.get("entry_price") or 0.0) * float(trade.get("size") or 0.0) * 0.001) for trade in closed_today), 2),
                "net_pnl": round(gross_pnl, 2),
            }
        )
