"""Streamlit dashboard for the trading bot."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import Settings, configure_logging
from dashboard.control import ControlInterpreter
from main import TradingBot
from storage import Storage
from strategies.technical import get_asset_class


async def _run_bot() -> None:
    """Run the trading bot loop until the process exits."""

    configure_logging()
    settings = Settings.from_env()
    bot = TradingBot(settings)
    if not bot.storage.get_state("briefing_complete", False):
        await bot.run_premarket_briefing()
    await bot.run()


@st.cache_resource(show_spinner=False)
def _start_bot_loop() -> bool:
    """Start the trading bot loop in a background thread (once per process)."""

    threading.Thread(target=lambda: asyncio.run(_run_bot()), name="trading-bot-loop", daemon=True).start()
    return True


def _load_candles(storage: Storage, symbol: str, timeframe: str) -> pd.DataFrame:
    """Load recent candles from SQLite."""

    with storage.connect() as connection:
        rows = connection.execute(
            """
            SELECT timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol = ? AND timeframe = ?
            ORDER BY timestamp DESC
            LIMIT 200
            """,
            (symbol, timeframe),
        ).fetchall()
    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if frame.empty:
        return frame
    frame = frame.sort_values("timestamp")
    frame["datetime"] = pd.to_datetime(frame["timestamp"], unit="ms")
    frame["ema_9"] = frame["close"].ewm(span=9, adjust=False).mean()
    frame["ema_20"] = frame["close"].ewm(span=20, adjust=False).mean()
    frame["ema_50"] = frame["close"].ewm(span=50, adjust=False).mean()
    upper = frame["close"].rolling(20).mean() + (frame["close"].rolling(20).std(ddof=0) * 2)
    lower = frame["close"].rolling(20).mean() - (frame["close"].rolling(20).std(ddof=0) * 2)
    frame["bb_upper"] = upper
    frame["bb_lower"] = lower
    return frame


def _status_badge(settings: Settings) -> str:
    """Return a human-readable bot status."""

    if settings.bot_paused:
        return "PAUSED"
    return "PAPER" if settings.paper_trading else "LIVE"


def render_dashboard() -> None:
    """Render the Streamlit application."""

    settings = Settings.from_env()
    _start_bot_loop()
    storage = Storage(settings.sqlite_path)
    control = ControlInterpreter(settings, storage)

    st.set_page_config(page_title="Trading Bot Dashboard", layout="wide")
    st.title("Algorithmic Trading Bot")
    pages = st.tabs(["Live Overview", "Positions & Trades", "AI Insights", "Control Panel"])

    symbol = st.sidebar.selectbox("Symbol", settings.symbols)
    timeframe = st.sidebar.selectbox("Chart timeframe", [settings.entry_timeframe, settings.primary_timeframe, settings.trend_timeframe], index=1)
    frame = _load_candles(storage, symbol, timeframe)
    recent_signals = storage.fetch_signals(limit=20)
    latest_signal = recent_signals[0] if recent_signals else None
    open_positions = storage.load_positions()
    trade_history = storage.fetch_trades(limit=200)

    with pages[0]:
        st.subheader("Live Overview")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Bot Status", _status_badge(settings))
        col2.metric("Tracked Symbols", len(settings.symbols))
        col3.metric("Open Positions", len(open_positions))
        col4.metric("Current Score", latest_signal["score"] if latest_signal else 0)

        asset_class = get_asset_class(symbol)
        st.caption(f"Active strategy: **{asset_class['strategy'].replace('_', ' ').title()}** ({asset_class['name'].replace('_', ' ').title()})")

        if not frame.empty:
            chart = go.Figure()
            chart.add_trace(go.Candlestick(x=frame["datetime"], open=frame["open"], high=frame["high"], low=frame["low"], close=frame["close"], name="Price"))
            for line in ["ema_9", "ema_20", "ema_50"]:
                chart.add_trace(go.Scatter(x=frame["datetime"], y=frame[line], mode="lines", name=line.upper()))
            chart.add_trace(go.Scatter(x=frame["datetime"], y=frame["bb_upper"], mode="lines", name="BB Upper"))
            chart.add_trace(go.Scatter(x=frame["datetime"], y=frame["bb_lower"], mode="lines", name="BB Lower"))
            chart.update_layout(height=520, xaxis_rangeslider_visible=False)
            st.plotly_chart(chart, use_container_width=True)
            st.bar_chart(frame.set_index("datetime")["volume"])

        if latest_signal:
            breakdown = json.loads(latest_signal["breakdown"])
            col1, col2, col3 = st.columns(3)
            col1.metric("Technical Points", breakdown["technical_points"])
            col2.metric("AI Points", breakdown["ai_points"])
            col3.metric("Sentiment Points", breakdown["market_sentiment_points"])
            st.json(breakdown["consensus"])

    with pages[1]:
        st.subheader("Positions & Trades")
        st.write("Open positions")
        st.dataframe(pd.DataFrame(list(open_positions.values())))
        trades_df = pd.DataFrame(trade_history)
        st.write("Trade history")
        st.dataframe(trades_df)
        if not trades_df.empty and "pnl" in trades_df.columns:
            closed = trades_df[trades_df["pnl"].notna()].copy()
            if not closed.empty:
                wins = closed[closed["pnl"] > 0]
                losses = closed[closed["pnl"] <= 0]
                st.metric("Win Rate", f"{(len(wins) / len(closed)) * 100:.1f}%")
                st.metric("Average Win", round(wins["pnl"].mean(), 2) if not wins.empty else 0)
                st.metric("Average Loss", round(losses["pnl"].mean(), 2) if not losses.empty else 0)
                gross_profit = wins["pnl"].sum() if not wins.empty else 0.0
                gross_loss = abs(losses["pnl"].sum()) if not losses.empty else 0.0
                st.metric("Profit Factor", round(gross_profit / gross_loss, 2) if gross_loss else 0.0)
                closed["entry_time"] = pd.to_datetime(closed["entry_time"])
                daily_pnl = closed.groupby(closed["entry_time"].dt.date)["pnl"].sum()
                st.line_chart(daily_pnl)
                st.line_chart(closed["pnl"].cumsum())

    with pages[2]:
        st.subheader("AI Insights")
        if latest_signal:
            breakdown = json.loads(latest_signal["breakdown"])
            consensus = breakdown["consensus"]
            st.metric("Models Agree", consensus["models_agree"])
            st.metric("Trade Safe", consensus["trade_safe"])
            st.write("Risk Flags")
            st.write(consensus["risk_flags"])
            st.write("Reasoning")
            st.write(consensus["reasoning"])
        with storage.connect() as connection:
            headlines = connection.execute(
                "SELECT asset, title, source, published_at FROM headlines ORDER BY published_at DESC LIMIT 50"
            ).fetchall()
        st.dataframe(pd.DataFrame(headlines))
        if recent_signals:
            points = []
            for signal in recent_signals:
                breakdown = json.loads(signal["breakdown"])
                consensus = breakdown["consensus"]
                points.append(
                    {
                        "created_at": signal["created_at"],
                        "groq_score": consensus.get("groq_score"),
                        "gemini_score": consensus.get("gemini_score"),
                    }
                )
            comparison_df = pd.DataFrame(points)
            if not comparison_df.empty:
                comparison_df["created_at"] = pd.to_datetime(comparison_df["created_at"])
                st.line_chart(comparison_df.set_index("created_at")[["groq_score", "gemini_score"]])

    with pages[3]:
        st.subheader("Control Panel")
        command = st.text_input("Natural language command")
        if st.button("Run command") and command:
            result = control.interpret(command)
            st.write(result.message)
            if result.parameters:
                st.json(result.parameters)
            if result.requires_confirmation:
                st.warning(result.confirmation_message or "Confirmation required before applying this change.")
                if st.button("Confirm change"):
                    control.apply(result)
                    st.success("Config override stored.")
            else:
                control.apply(result)
                st.success("Config override stored.")

        st.write("Manual config editor")
        with st.form("config_editor"):
            risk_value = st.number_input("Risk per trade", min_value=0.0, max_value=0.05, value=float(settings.risk_per_trade), step=0.005)
            paused = st.checkbox("Pause bot", value=settings.bot_paused)
            paper = st.checkbox("Paper trading", value=settings.paper_trading)
            submitted = st.form_submit_button("Save settings")
            if submitted:
                storage.set_state("runtime_overrides", {"risk_per_trade": risk_value, "bot_paused": paused, "paper_trading": paper})
                st.success("Runtime overrides saved.")

        if st.button("Start bot"):
            storage.set_state("runtime_overrides", {"bot_paused": False})
            st.success("Bot marked as running.")
        if st.button("Pause bot"):
            storage.set_state("runtime_overrides", {"bot_paused": True})
            st.success("Bot marked as paused.")
        if st.button("Switch to paper trading"):
            storage.set_state("runtime_overrides", {"paper_trading": True})
            st.success("Paper trading enabled.")


if __name__ == "__main__":
    render_dashboard()
