"""Technical indicator calculation and signal scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from config import Settings
from models import TechnicalSignal
from utils import clamp


def _ema(series: pd.Series, period: int) -> pd.Series:
    """Return an exponential moving average."""

    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int) -> pd.Series:
    """Return the relative strength index."""

    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False).mean().replace(0, np.nan)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
    """Return MACD lines."""

    fast_ema = _ema(series, fast)
    slow_ema = _ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "histogram": histogram})


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    """Return the average true range."""

    high_low = frame["high"] - frame["low"]
    high_close = (frame["high"] - frame["close"].shift()).abs()
    low_close = (frame["low"] - frame["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def _adx(frame: pd.DataFrame, period: int) -> pd.Series:
    """Return the average directional index."""

    up_move = frame["high"].diff()
    down_move = -frame["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = _atr(frame, period).replace(0, np.nan)
    plus_di = 100 * pd.Series(plus_dm, index=frame.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=frame.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0)


def _bollinger(series: pd.Series, period: int = 20, std_mult: float = 2.0) -> pd.DataFrame:
    """Return Bollinger band values."""

    middle = series.rolling(period).mean()
    std = series.rolling(period).std(ddof=0)
    upper = middle + std * std_mult
    lower = middle - std * std_mult
    return pd.DataFrame({"upper": upper, "middle": middle, "lower": lower})


def _stoch_rsi(series: pd.Series, period: int = 14, smooth_k: int = 3) -> pd.Series:
    """Return Stochastic RSI."""

    rsi = _rsi(series, period)
    min_rsi = rsi.rolling(period).min()
    max_rsi = rsi.rolling(period).max()
    stoch = (rsi - min_rsi) / (max_rsi - min_rsi).replace(0, np.nan)
    return stoch.rolling(smooth_k).mean() * 100


def _williams_r(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Return Williams %R."""

    highest_high = frame["high"].rolling(period).max()
    lowest_low = frame["low"].rolling(period).min()
    return -100 * (highest_high - frame["close"]) / (highest_high - lowest_low).replace(0, np.nan)


def _obv(frame: pd.DataFrame) -> pd.Series:
    """Return On-Balance Volume."""

    direction = np.sign(frame["close"].diff()).fillna(0)
    return (direction * frame["volume"]).cumsum()


def _vwap(frame: pd.DataFrame) -> pd.Series:
    """Return VWAP."""

    typical_price = (frame["high"] + frame["low"] + frame["close"]) / 3
    cumulative_value = (typical_price * frame["volume"]).cumsum()
    cumulative_volume = frame["volume"].cumsum().replace(0, np.nan)
    return cumulative_value / cumulative_volume


def _keltner(frame: pd.DataFrame, ema_period: int = 20, atr_period: int = 14) -> pd.DataFrame:
    """Return Keltner channel values."""

    middle = _ema(frame["close"], ema_period)
    atr = _atr(frame, atr_period)
    upper = middle + (2 * atr)
    lower = middle - (2 * atr)
    return pd.DataFrame({"upper": upper, "middle": middle, "lower": lower})


def _support_resistance(series: pd.Series, window: int = 20) -> tuple[float, float]:
    """Estimate support and resistance from rolling extremes."""

    support = float(series.tail(window).min())
    resistance = float(series.tail(window).max())
    return support, resistance


def _prior_resistance(frame: pd.DataFrame, window: int = 20) -> float:
    """Return the highest close over the window preceding the latest candle."""

    if len(frame) <= 1:
        return float(frame["close"].iloc[-1])
    return float(frame["close"].iloc[:-1].tail(window).max())


def _bb_position(price: float, upper: float, middle: float, lower: float) -> str:
    """Return relative price position inside the Bollinger bands."""

    if price > upper:
        return "above_upper"
    if price >= middle + (upper - middle) * 0.5:
        return "near_upper"
    if price < lower:
        return "below_lower"
    if price <= middle - (middle - lower) * 0.5:
        return "near_lower"
    return "middle"


def _trend_strength(adx_value: float) -> str:
    """Convert ADX value into a label."""

    if adx_value > 30:
        return "strong"
    if adx_value > 20:
        return "moderate"
    return "weak"


ASSET_CLASS_CONFIG: dict[str, dict[str, Any]] = {
    "crypto": {
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"],
        "strategy": "momentum_breakout",
        "primary_timeframe": "1h",
        "entry_timeframe": "15m",
        "trend_timeframe": "4h",
    },
    "equity_indices": {
        "symbols": ["SPY", "QQQ", "US30", "NAS100"],
        "strategy": "mean_reversion",
        "primary_timeframe": "15m",
        "entry_timeframe": "5m",
        "trend_timeframe": "1h",
    },
    "commodities": {
        "symbols": ["GOLD/USDT", "XAU/USDT", "OIL/USDT"],
        "strategy": "trend_following",
        "primary_timeframe": "4h",
        "entry_timeframe": "1h",
        "trend_timeframe": "1d",
    },
    "forex": {
        "symbols": ["EUR/USDT", "GBP/USDT"],
        "strategy": "trend_following",
        "primary_timeframe": "1h",
        "entry_timeframe": "15m",
        "trend_timeframe": "4h",
    },
}


def get_asset_class(symbol: str) -> dict[str, Any]:
    """Return the asset class configuration for symbol, defaulting to crypto."""

    for class_name, class_config in ASSET_CLASS_CONFIG.items():
        if symbol in class_config["symbols"]:
            return {**class_config, "name": class_name}
    return {**ASSET_CLASS_CONFIG["crypto"], "name": "crypto"}


class TechnicalStrategy:
    """Compute technical indicators and score aligned setups."""

    def __init__(self, settings: Settings) -> None:
        """Create a strategy calculator."""

        self.settings = settings

    def calculate(self, frames: dict[str, pd.DataFrame], strategy_type: str = "momentum_breakout") -> TechnicalSignal:
        """Calculate a multi-timeframe technical signal, weighted for strategy_type."""

        prepared = self._prepare(frames)
        return self._build_signal(prepared, strategy_type=strategy_type)

    def route_strategy(self, symbol: str, frames: dict[str, pd.DataFrame]) -> TechnicalSignal:
        """Route symbol to its asset-class strategy and attach entry/stop/target details."""

        asset_class = get_asset_class(symbol)
        strategy_type = asset_class["strategy"]
        prepared = self._prepare(frames)
        signal = self._build_signal(prepared, strategy_type=strategy_type)

        if strategy_type == "mean_reversion":
            routing = self._mean_reversion_signal(prepared["primary_frame"], signal)
        elif strategy_type == "trend_following":
            routing = self._trend_following_signal(prepared["primary_frame"], signal)
        else:
            routing = self._momentum_breakout_signal(prepared["primary_frame"])

        signal.metadata["asset_class"] = asset_class["name"]
        signal.metadata["strategy"] = strategy_type
        signal.metadata["strategy_routing"] = routing
        return signal

    def _prepare(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Enrich all timeframes and classify trend direction and alignment."""

        enriched = {timeframe: self._enrich(frame.copy()) for timeframe, frame in frames.items()}
        trend_frame = enriched[self.settings.trend_timeframe]
        primary_frame = enriched[self.settings.primary_timeframe]
        entry_frame = enriched[self.settings.entry_timeframe]

        trend_direction = self._trend_label(trend_frame)
        primary_direction = self._trend_label(primary_frame)
        entry_direction = self._trend_label(entry_frame)
        alignment = self._alignment([trend_direction, primary_direction, entry_direction])

        return {
            "enriched": enriched,
            "trend_frame": trend_frame,
            "primary_frame": primary_frame,
            "entry_frame": entry_frame,
            "trend_direction": trend_direction,
            "primary_direction": primary_direction,
            "entry_direction": entry_direction,
            "alignment": alignment,
        }

    def _build_signal(self, prepared: dict[str, Any], *, strategy_type: str) -> TechnicalSignal:
        """Build a TechnicalSignal from prepared frames, scored for strategy_type."""

        primary_frame = prepared["primary_frame"]
        trend_direction = prepared["trend_direction"]
        primary_direction = prepared["primary_direction"]
        entry_direction = prepared["entry_direction"]
        alignment = prepared["alignment"]

        latest = primary_frame.iloc[-1]
        previous = primary_frame.iloc[-2]
        support, resistance = _support_resistance(primary_frame["close"])
        ema_signal = self._ema_signal(primary_frame)
        macd_signal = self._macd_signal(primary_frame)
        rsi_signal = self._rsi_signal(float(latest["rsi"]))
        volume_signal = self._volume_signal(primary_frame)
        bb_position = _bb_position(
            float(latest["close"]),
            float(latest["bb_upper"]),
            float(latest["bb_middle"]),
            float(latest["bb_lower"]),
        )

        volume_ratio = float(latest["volume_ratio"]) if pd.notna(latest["volume_ratio"]) else 1.0
        ema_stack_up = bool(latest["ema_9"] > latest["ema_20"] > latest["ema_50"] and latest["ema_50"] >= previous["ema_50"])
        ema_stack_down = bool(latest["ema_9"] < latest["ema_20"] < latest["ema_50"] and latest["ema_50"] <= previous["ema_50"])
        macd_histogram_increasing = bool(latest["macd_histogram"] > previous["macd_histogram"])
        breakout_above_resistance = bool(float(latest["close"]) > _prior_resistance(primary_frame) and volume_ratio > 1.5)

        technical_score = self._score_signal(
            strategy_type=strategy_type,
            trend_direction=primary_direction,
            ema_signal=ema_signal,
            macd_signal=macd_signal,
            rsi_signal=rsi_signal,
            rsi_value=float(latest["rsi"]),
            stoch_rsi_value=float(latest["stoch_rsi"]),
            bb_position=bb_position,
            volume_signal=volume_signal,
            alignment=alignment,
            adx_value=float(latest["adx"]),
            ema_stack_up=ema_stack_up,
            ema_stack_down=ema_stack_down,
            macd_histogram_increasing=macd_histogram_increasing,
            breakout_above_resistance=breakout_above_resistance,
        )

        return TechnicalSignal(
            trend=primary_direction,
            ema_signal=ema_signal,
            macd_signal=macd_signal,
            rsi=float(latest["rsi"]),
            rsi_signal=rsi_signal,
            stoch_rsi=float(latest["stoch_rsi"]),
            bb_position=bb_position,
            adx=float(latest["adx"]),
            trend_strength=_trend_strength(float(latest["adx"])),
            volume_signal=volume_signal,
            support=support,
            resistance=resistance,
            atr=float(latest["atr"]),
            timeframe_alignment=alignment,
            technical_score=technical_score,
            primary_timeframe=self.settings.primary_timeframe,
            entry_timeframe=self.settings.entry_timeframe,
            trend_timeframe=self.settings.trend_timeframe,
            metadata={
                "trend_direction": trend_direction,
                "entry_direction": entry_direction,
                "price": float(latest["close"]),
                "ema_9": float(latest["ema_9"]),
                "ema_20": float(latest["ema_20"]),
                "ema_50": float(latest["ema_50"]),
                "ema_200": float(latest["ema_200"]),
                "atr_average": float(primary_frame["atr"].tail(14).mean()),
                "atr_latest": float(latest["atr"]),
                "volatility_spike": float(latest["atr"]) > float(primary_frame["atr"].tail(14).mean()) * 2,
                "obv": float(latest["obv"]),
                "vwap": float(latest["vwap"]),
                "williams_r": float(latest["williams_r"]),
                "rsi_divergence": self._rsi_divergence(primary_frame),
            },
        )

    def _enrich(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Add indicator columns to an OHLCV frame."""

        frame = frame.sort_values("timestamp").reset_index(drop=True)
        for period in self.settings.ema_periods:
            frame[f"ema_{period}"] = _ema(frame["close"], period)

        macd_frame = _macd(frame["close"], self.settings.macd_fast, self.settings.macd_slow, self.settings.macd_signal)
        frame["macd"] = macd_frame["macd"]
        frame["macd_signal_line"] = macd_frame["signal"]
        frame["macd_histogram"] = macd_frame["histogram"]
        frame["rsi"] = _rsi(frame["close"], self.settings.rsi_period).fillna(50.0)
        frame["stoch_rsi"] = _stoch_rsi(frame["close"], self.settings.rsi_period).fillna(50.0)
        frame["adx"] = _adx(frame, 14).fillna(0.0)
        frame["atr"] = _atr(frame, self.settings.atr_period).bfill().fillna(0.0)

        bbands = _bollinger(frame["close"])
        frame["bb_upper"] = bbands["upper"].bfill()
        frame["bb_middle"] = bbands["middle"].bfill()
        frame["bb_lower"] = bbands["lower"].bfill()

        keltner = _keltner(frame)
        frame["kc_upper"] = keltner["upper"].bfill()
        frame["kc_middle"] = keltner["middle"].bfill()
        frame["kc_lower"] = keltner["lower"].bfill()

        frame["obv"] = _obv(frame).fillna(0.0)
        frame["volume_ratio"] = frame["volume"] / frame["volume"].rolling(20).mean().replace(0, np.nan)
        frame["vwap"] = _vwap(frame).bfill()
        frame["williams_r"] = _williams_r(frame).fillna(-50.0)
        return frame

    def _trend_label(self, frame: pd.DataFrame) -> str:
        """Classify price trend from EMAs and price position."""

        latest = frame.iloc[-1]
        if latest["close"] > latest["ema_20"] > latest["ema_50"] > latest["ema_200"]:
            return "up"
        if latest["close"] < latest["ema_20"] < latest["ema_50"] < latest["ema_200"]:
            return "down"
        return "neutral"

    def _alignment(self, directions: list[str]) -> str:
        """Measure whether timeframes align."""

        unique = set(directions)
        if len(unique) == 1 and "neutral" not in unique:
            return "all"
        if len(unique) <= 2 and not all(direction == "neutral" for direction in directions):
            return "partial"
        return "none"

    def _ema_signal(self, frame: pd.DataFrame) -> str:
        """Detect fast/slow EMA crossover."""

        latest = frame.iloc[-1]
        previous = frame.iloc[-2]
        if previous["ema_9"] <= previous["ema_20"] and latest["ema_9"] > latest["ema_20"]:
            return "bullish_cross"
        if previous["ema_9"] >= previous["ema_20"] and latest["ema_9"] < latest["ema_20"]:
            return "bearish_cross"
        return "none"

    def _macd_signal(self, frame: pd.DataFrame) -> str:
        """Classify MACD signal."""

        latest = frame.iloc[-1]
        if latest["macd"] > latest["macd_signal_line"] and latest["macd_histogram"] > 0:
            return "bullish"
        if latest["macd"] < latest["macd_signal_line"] and latest["macd_histogram"] < 0:
            return "bearish"
        return "neutral"

    def _rsi_signal(self, value: float) -> str:
        """Classify RSI level."""

        if value <= self.settings.rsi_oversold:
            return "oversold"
        if value >= self.settings.rsi_overbought:
            return "overbought"
        return "neutral"

    def _volume_signal(self, frame: pd.DataFrame) -> str:
        """Classify relative volume."""

        ratio = float(frame.iloc[-1]["volume_ratio"]) if pd.notna(frame.iloc[-1]["volume_ratio"]) else 1.0
        if ratio >= 1.5:
            return "high"
        if ratio <= 0.75:
            return "low"
        return "normal"

    def _rsi_divergence(self, frame: pd.DataFrame) -> str:
        """Return a coarse RSI divergence label."""

        recent = frame.tail(5)
        price_change = recent["close"].iloc[-1] - recent["close"].iloc[0]
        rsi_change = recent["rsi"].iloc[-1] - recent["rsi"].iloc[0]
        if price_change > 0 and rsi_change < 0:
            return "bearish_divergence"
        if price_change < 0 and rsi_change > 0:
            return "bullish_divergence"
        return "none"

    def _score_signal(
        self,
        *,
        strategy_type: str,
        trend_direction: str,
        ema_signal: str,
        macd_signal: str,
        rsi_signal: str,
        rsi_value: float,
        stoch_rsi_value: float,
        bb_position: str,
        volume_signal: str,
        alignment: str,
        adx_value: float,
        ema_stack_up: bool,
        ema_stack_down: bool,
        macd_histogram_increasing: bool,
        breakout_above_resistance: bool,
    ) -> float:
        """Score the technical setup from 0.0 to 1.0, weighted by strategy_type."""

        trend_component = self._trend_component(trend_direction=trend_direction, alignment=alignment, adx_value=adx_value)

        if strategy_type == "mean_reversion":
            primary_component = self._mean_reversion_component(
                rsi_value=rsi_value, stoch_rsi_value=stoch_rsi_value, bb_position=bb_position
            )
            score = (primary_component * 0.6) + (trend_component * 0.4)
        elif strategy_type == "trend_following":
            ema_adx_component = self._ema_adx_component(
                ema_stack_up=ema_stack_up, ema_stack_down=ema_stack_down, adx_value=adx_value, trend_direction=trend_direction
            )
            momentum_component = self._momentum_component(macd_signal=macd_signal, rsi_value=rsi_value, rsi_signal=rsi_signal)
            score = (ema_adx_component * 0.6) + (momentum_component * 0.4)
        else:
            breakout_component = self._breakout_volume_component(
                ema_signal=ema_signal,
                macd_histogram_increasing=macd_histogram_increasing,
                rsi_value=rsi_value,
                rsi_signal=rsi_signal,
                volume_signal=volume_signal,
                ema_stack_up=ema_stack_up,
                breakout_above_resistance=breakout_above_resistance,
            )
            score = (breakout_component * 0.6) + (trend_component * 0.4)

        return round(clamp(score, 0.0, 1.0), 4)

    def _trend_component(self, *, trend_direction: str, alignment: str, adx_value: float) -> float:
        """Score higher-timeframe trend strength and alignment from 0.0 to 1.0."""

        score = 0.5
        score += {"up": 0.20, "down": -0.20, "neutral": 0.0}[trend_direction]
        score += {"all": 0.20, "partial": 0.08, "none": -0.15}[alignment]
        if adx_value > 25:
            score += 0.10
        elif adx_value < 15:
            score -= 0.05
        return clamp(score, 0.0, 1.0)

    def _breakout_volume_component(
        self,
        *,
        ema_signal: str,
        macd_histogram_increasing: bool,
        rsi_value: float,
        rsi_signal: str,
        volume_signal: str,
        ema_stack_up: bool,
        breakout_above_resistance: bool,
    ) -> float:
        """Score breakout/volume conditions for momentum_breakout from 0.0 to 1.0."""

        score = 0.5
        if ema_stack_up:
            score += 0.15
        score += {"bullish_cross": 0.10, "bearish_cross": -0.15, "none": 0.0}[ema_signal]
        score += 0.10 if macd_histogram_increasing else -0.05
        score += {"high": 0.15, "normal": 0.0, "low": -0.10}[volume_signal]
        if 50 <= rsi_value <= 70:
            score += 0.10
        elif rsi_signal == "overbought":
            score -= 0.05
        elif rsi_signal == "oversold":
            score -= 0.10
        if breakout_above_resistance:
            score += 0.10
        return clamp(score, 0.0, 1.0)

    def _mean_reversion_component(self, *, rsi_value: float, stoch_rsi_value: float, bb_position: str) -> float:
        """Score RSI/Bollinger/Stochastic extremes for mean_reversion from 0.0 to 1.0."""

        score = 0.5
        if rsi_value < 30:
            score += 0.20
        elif rsi_value > 70:
            score -= 0.20
        if stoch_rsi_value < 20:
            score += 0.15
        elif stoch_rsi_value > 80:
            score -= 0.15
        score += {
            "below_lower": 0.20,
            "near_lower": 0.08,
            "middle": 0.0,
            "near_upper": -0.08,
            "above_upper": -0.20,
        }[bb_position]
        return clamp(score, 0.0, 1.0)

    def _ema_adx_component(self, *, ema_stack_up: bool, ema_stack_down: bool, adx_value: float, trend_direction: str) -> float:
        """Score EMA alignment and ADX trend strength for trend_following from 0.0 to 1.0."""

        score = 0.5
        if ema_stack_up:
            score += 0.20
        elif ema_stack_down:
            score -= 0.20
        if adx_value > 25:
            score += 0.20
        elif adx_value < 15:
            score -= 0.10
        score += {"up": 0.10, "down": -0.10, "neutral": 0.0}[trend_direction]
        return clamp(score, 0.0, 1.0)

    def _momentum_component(self, *, macd_signal: str, rsi_value: float, rsi_signal: str) -> float:
        """Score MACD/RSI momentum continuation for trend_following from 0.0 to 1.0."""

        score = 0.5
        score += {"bullish": 0.20, "bearish": -0.20, "neutral": 0.0}[macd_signal]
        if 50 <= rsi_value <= 70:
            score += 0.15
        elif rsi_signal == "overbought":
            score -= 0.10
        elif rsi_signal == "oversold":
            score += 0.05
        return clamp(score, 0.0, 1.0)

    def _momentum_breakout_signal(self, frame: pd.DataFrame) -> dict[str, Any]:
        """Evaluate the momentum breakout entry/stop/target rules on the primary frame."""

        latest = frame.iloc[-1]
        previous = frame.iloc[-2]
        close = float(latest["close"])
        low = float(latest["low"])
        volume_ratio = float(latest["volume_ratio"]) if pd.notna(latest["volume_ratio"]) else 1.0
        ema_stack_up = bool(latest["ema_9"] > latest["ema_20"] > latest["ema_50"] and latest["ema_50"] >= previous["ema_50"])
        macd_increasing = bool(latest["macd_histogram"] > previous["macd_histogram"])
        rsi_value = float(latest["rsi"])
        rsi_in_zone = 50 <= rsi_value <= 70
        prior_resistance = _prior_resistance(frame)
        breakout = close > prior_resistance and volume_ratio > 1.5

        entry_signal = "none"
        entry_trigger: float | None = None
        stop_price: float | None = None
        target_price: float | None = None
        if breakout and ema_stack_up and macd_increasing and rsi_in_zone:
            entry_signal = "long"
            entry_trigger = round(prior_resistance, 4)
            stop_price = round(low, 4)
            stop_distance = max(close - stop_price, close * 0.001)
            target_price = round(close + (stop_distance * self.settings.min_reward_risk), 4)

        return {
            "strategy": "momentum_breakout",
            "entry_signal": entry_signal,
            "entry_trigger": entry_trigger,
            "stop_price": stop_price,
            "target_price": target_price,
            "conditions": {
                "breakout_above_resistance": breakout,
                "ema_stack_aligned_up": ema_stack_up,
                "macd_histogram_increasing": macd_increasing,
                "rsi_in_zone": rsi_in_zone,
                "volume_ratio": round(volume_ratio, 4),
            },
        }

    def _mean_reversion_signal(self, frame: pd.DataFrame, signal: TechnicalSignal) -> dict[str, Any]:
        """Evaluate the mean reversion entry/stop/target rules on the primary frame."""

        latest = frame.iloc[-1]
        previous = frame.iloc[-2]
        close = float(latest["close"])
        vwap = float(latest["vwap"])
        atr = float(latest["atr"])
        rsi_value = float(latest["rsi"])
        stoch_rsi_value = float(latest["stoch_rsi"])
        bb_upper, bb_middle, bb_lower = float(latest["bb_upper"]), float(latest["bb_middle"]), float(latest["bb_lower"])
        prev_bb_upper, prev_bb_lower = float(previous["bb_upper"]), float(previous["bb_lower"])
        prev_close = float(previous["close"])

        stretch = abs(close - vwap) / atr if atr else 0.0
        stretched = stretch > 1.5
        adx_ok = signal.adx < 25
        bb_reentry_long = prev_close <= prev_bb_lower and close > bb_lower
        bb_reentry_short = prev_close >= prev_bb_upper and close < bb_upper

        entry_signal = "none"
        entry_trigger: float | None = None
        stop_price: float | None = None
        target_price: float | None = None

        if stretched and adx_ok and rsi_value < 30 and stoch_rsi_value < 20 and bb_reentry_long:
            entry_signal = "long"
            entry_trigger = round(close, 4)
            stop_price = round(float(previous["low"]), 4)
            target_price = round((vwap + bb_middle) / 2, 4)
        elif stretched and adx_ok and rsi_value > 70 and bb_reentry_short:
            entry_signal = "short"
            entry_trigger = round(close, 4)
            stop_price = round(float(previous["high"]), 4)
            target_price = round((vwap + bb_middle) / 2, 4)

        return {
            "strategy": "mean_reversion",
            "entry_signal": entry_signal,
            "entry_trigger": entry_trigger,
            "stop_price": stop_price,
            "target_price": target_price,
            "conditions": {
                "vwap_stretch_atr": round(stretch, 4),
                "stretched": stretched,
                "rsi": rsi_value,
                "stoch_rsi": stoch_rsi_value,
                "adx_below_25": adx_ok,
                "bb_reentry_long": bb_reentry_long,
                "bb_reentry_short": bb_reentry_short,
            },
        }

    def _trend_following_signal(self, frame: pd.DataFrame, signal: TechnicalSignal) -> dict[str, Any]:
        """Evaluate the trend following entry/stop/target rules on the primary frame."""

        latest = frame.iloc[-1]
        previous = frame.iloc[-2]
        close = float(latest["close"])
        ema_20 = float(latest["ema_20"])
        ema_50 = float(latest["ema_50"])
        ema_200 = float(latest["ema_200"])
        atr = float(latest["atr"])
        atr_average = float(frame["atr"].tail(14).mean())
        volume_ratio = float(latest["volume_ratio"]) if pd.notna(latest["volume_ratio"]) else 1.0
        prev_volume_ratio = float(previous["volume_ratio"]) if pd.notna(previous["volume_ratio"]) else 1.0

        trend_up = (
            close > ema_50
            and close > ema_200
            and ema_50 >= float(previous["ema_50"])
            and ema_200 >= float(previous["ema_200"])
        )
        adx_ok = signal.adx > 25
        macd_above_signal = bool(latest["macd"] > latest["macd_signal_line"])
        atr_spike = atr > (atr_average * 2) if atr_average else False
        pullback_holding = (
            float(previous["low"]) <= float(previous["ema_20"])
            and close > ema_20
            and prev_volume_ratio < 1.0
            and volume_ratio >= 1.0
        )

        entry_signal = "none"
        entry_trigger: float | None = None
        stop_price: float | None = None
        target_price: float | None = None

        if trend_up and adx_ok and macd_above_signal and pullback_holding and not atr_spike:
            entry_signal = "long"
            entry_trigger = round(close, 4)
            stop_price = round(max(ema_50, close - (1.5 * atr)), 4)
            stop_distance = max(close - stop_price, close * 0.001)
            target_price = round(close + (stop_distance * self.settings.min_reward_risk), 4)

        return {
            "strategy": "trend_following",
            "entry_signal": entry_signal,
            "entry_trigger": entry_trigger,
            "stop_price": stop_price,
            "target_price": target_price,
            "conditions": {
                "trend_up": trend_up,
                "adx_above_25": adx_ok,
                "macd_above_signal": macd_above_signal,
                "pullback_to_ema20_holding": pullback_holding,
                "atr_spike_skip": atr_spike,
                "atr_average": round(atr_average, 6),
            },
        }
