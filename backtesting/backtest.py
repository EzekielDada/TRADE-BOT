"""Backtesting helpers using Backtrader when available."""

from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from config import Settings

try:
    import backtrader as bt
except ImportError:  # pragma: no cover - optional dependency.
    bt = None  # type: ignore[assignment]


@dataclass(slots=True)
class BacktestReport:
    """Structured backtest output."""

    total_return: float
    cagr: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    monte_carlo_p5: float
    monte_carlo_p50: float
    monte_carlo_p95: float

    def to_dict(self) -> dict[str, float]:
        """Return a JSON-serializable dictionary."""

        return self.__dict__.copy()


class BacktestRunner:
    """Run historical simulations and export a PDF report."""

    def __init__(self, settings: Settings) -> None:
        """Create a backtest runner."""

        self.settings = settings

    def run(self, frame: pd.DataFrame) -> BacktestReport:
        """Run a simplified backtest on historical candles."""

        trades = self._simulate_trades(frame)
        returns = [trade["return"] for trade in trades]
        equity_curve = self._equity_curve(returns)
        total_return = equity_curve[-1] - 1 if equity_curve else 0.0
        years = max(len(frame) / (24 * 365), 1 / 365)
        cagr = (equity_curve[-1] ** (1 / years) - 1) if equity_curve else 0.0
        wins = [item for item in returns if item > 0]
        losses = [item for item in returns if item <= 0]
        win_rate = len(wins) / len(returns) if returns else 0.0
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss else 0.0
        max_drawdown = self._max_drawdown(equity_curve)
        sharpe_ratio = self._sharpe_ratio(returns)
        sortino_ratio = self._sortino_ratio(returns)
        calmar_ratio = cagr / max_drawdown if max_drawdown else 0.0
        monte_carlo = self._monte_carlo(returns, iterations=1000)

        return BacktestReport(
            total_return=round(total_return, 4),
            cagr=round(cagr, 4),
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 4),
            max_drawdown=round(max_drawdown, 4),
            sharpe_ratio=round(sharpe_ratio, 4),
            sortino_ratio=round(sortino_ratio, 4),
            calmar_ratio=round(calmar_ratio, 4),
            monte_carlo_p5=round(monte_carlo[0], 4),
            monte_carlo_p50=round(monte_carlo[1], 4),
            monte_carlo_p95=round(monte_carlo[2], 4),
        )

    def export_pdf(self, report: BacktestReport, path: Path) -> Path:
        """Export a PDF summary report."""

        path.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(str(path), pagesize=letter)
        pdf.setTitle("Trading Bot Backtest Report")
        pdf.drawString(72, 750, "Trading Bot Backtest Report")
        y = 720
        for key, value in report.to_dict().items():
            pdf.drawString(72, y, f"{key}: {value}")
            y -= 20
        pdf.save()
        return path

    def _simulate_trades(self, frame: pd.DataFrame) -> list[dict[str, float]]:
        """Create proxy trades from momentum and fear/greed-like sentiment."""

        closes = frame["close"].reset_index(drop=True)
        returns = closes.pct_change().fillna(0.0)
        momentum = returns.rolling(5).mean().fillna(0.0)
        sentiment_proxy = (returns.rolling(20).mean().fillna(0.0) * 100).clip(-1, 1)
        trades: list[dict[str, float]] = []
        for index in range(20, len(frame) - 1):
            signal = momentum.iloc[index] + sentiment_proxy.iloc[index]
            trade_return = returns.iloc[index + 1]
            if signal > 0.002:
                trades.append({"return": trade_return * 2})
            elif signal < -0.002:
                trades.append({"return": -trade_return})
        return trades

    def _equity_curve(self, returns: list[float]) -> list[float]:
        """Build an equity curve from sequential returns."""

        equity = 1.0
        curve: list[float] = []
        for item in returns:
            equity *= 1 + item
            curve.append(equity)
        return curve

    def _max_drawdown(self, equity_curve: list[float]) -> float:
        """Calculate maximum drawdown."""

        peak = 1.0
        max_dd = 0.0
        for equity in equity_curve:
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak)
        return max_dd

    def _sharpe_ratio(self, returns: list[float]) -> float:
        """Calculate a simple Sharpe ratio."""

        if len(returns) < 2:
            return 0.0
        volatility = pstdev(returns)
        return (mean(returns) / volatility) * math.sqrt(252) if volatility else 0.0

    def _sortino_ratio(self, returns: list[float]) -> float:
        """Calculate a simple Sortino ratio."""

        if len(returns) < 2:
            return 0.0
        downside = [value for value in returns if value < 0]
        downside_dev = pstdev(downside) if len(downside) > 1 else 0.0
        return (mean(returns) / downside_dev) * math.sqrt(252) if downside_dev else 0.0

    def _monte_carlo(self, returns: list[float], iterations: int) -> tuple[float, float, float]:
        """Run Monte Carlo permutations of trade order."""

        if not returns:
            return (0.0, 0.0, 0.0)
        outcomes: list[float] = []
        for _ in range(iterations):
            shuffled = returns[:]
            random.shuffle(shuffled)
            equity = self._equity_curve(shuffled)
            outcomes.append(equity[-1] - 1 if equity else 0.0)
        outcomes.sort()
        return (
            outcomes[int(iterations * 0.05)],
            outcomes[int(iterations * 0.50)],
            outcomes[int(iterations * 0.95) - 1],
        )
