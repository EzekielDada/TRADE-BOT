"""Streamlit dashboard for real-time bot monitoring and control."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from loguru import logger

from config import Settings, configure_logging
from storage import Storage
from utils import wat_now, utc_now


# Page configuration
st.set_page_config(
    page_title="Trading Bot Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        padding: 20px;
        border-radius: 10px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        margin: 10px 0;
    }
    .status-running { color: #00ff00; }
    .status-paused { color: #ff9900; }
    .status-error { color: #ff0000; }
</style>
""", unsafe_allow_html=True)


def load_settings() -> Settings:
    """Load trading bot settings."""
    return Settings.from_env()


def load_storage() -> Storage:
    """Load storage connection."""
    settings = load_settings()
    return Storage(settings.sqlite_path)


@st.cache_resource
def initialize_app():
    """Initialize app resources."""
    configure_logging()
    settings = load_settings()
    storage = Storage(settings.sqlite_path)
    return settings, storage


def get_bot_status() -> dict:
    """Get current bot status from storage."""
    _, storage = initialize_app()
    
    with storage.connect() as conn:
        # Get bot state
        cursor = conn.execute("SELECT key, value FROM bot_state WHERE key IN ('BOT_PAUSED', 'PAPER_TRADING', 'briefing_complete')")
        state = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Get last trade
        cursor = conn.execute("""
            SELECT * FROM trades ORDER BY entry_time DESC LIMIT 1
        """)
        last_trade = cursor.fetchone()
        
        # Get today's PnL
        today = wat_now().date().isoformat()
        cursor = conn.execute("""
            SELECT * FROM daily_pnl WHERE date = ?
        """, (today,))
        daily_stats = cursor.fetchone()
    
    return {
        "paused": state.get("BOT_PAUSED", "false").lower() == "true",
        "paper_trading": state.get("PAPER_TRADING", "true").lower() == "true",
        "briefing_complete": state.get("briefing_complete", "false").lower() == "true",
        "last_trade": last_trade,
        "daily_stats": daily_stats,
    }


def get_recent_trades(limit: int = 20) -> pd.DataFrame:
    """Get recent trades from database."""
    _, storage = initialize_app()
    
    with storage.connect() as conn:
        query = """
            SELECT trade_id, symbol, side, entry_price, exit_price, size, pnl, 
                   signal_score, status, entry_time, exit_time
            FROM trades
            ORDER BY entry_time DESC
            LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(limit,))
        if not df.empty:
            df['entry_time'] = pd.to_datetime(df['entry_time'])
            df['exit_time'] = pd.to_datetime(df['exit_time'])
        return df


def get_daily_pnl_data(days: int = 30) -> pd.DataFrame:
    """Get daily PnL data for chart."""
    _, storage = initialize_app()
    
    with storage.connect() as conn:
        query = """
            SELECT date, starting_balance, ending_balance, trades_taken, 
                   wins, losses, net_pnl
            FROM daily_pnl
            ORDER BY date DESC
            LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(days,))
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
        return df


def page_overview():
    """Live Overview page."""
    st.title("📊 Live Trading Overview")
    
    status = get_bot_status()
    
    # Status indicators
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        mode = "PAPER" if status["paper_trading"] else "LIVE"
        st.metric("Mode", mode, delta=None)
    
    with col2:
        bot_status = "⏸ PAUSED" if status["paused"] else "▶ RUNNING"
        st.metric("Bot Status", bot_status, delta=None)
    
    with col3:
        brief = "✓" if status["briefing_complete"] else "✗"
        st.metric("Briefing", brief, delta=None)
    
    with col4:
        if status["daily_stats"]:
            daily_pnl = status["daily_stats"][6]  # net_pnl column
            st.metric("Daily PnL", f"${daily_pnl:.2f}", delta=daily_pnl)
        else:
            st.metric("Daily PnL", "$0.00", delta=None)
    
    st.divider()
    
    # Market data
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.subheader("24h Price Change")
        # This would fetch from market data
        st.info("Real-time chart would display here with Plotly")
    
    with col_chart2:
        st.subheader("Fear & Greed Index")
        # This would fetch from fear/greed API
        st.info("Fear & Greed gauge would display here")
    
    st.divider()
    
    # Signals and alerts
    col_signals, col_alerts = st.columns(2)
    
    with col_signals:
        st.subheader("Latest Signals")
        st.info("Recent trading signals would display here")
    
    with col_alerts:
        st.subheader("Active Alerts")
        st.warning("⚠ No critical alerts")


def page_positions():
    """Positions & Trades page."""
    st.title("💼 Positions & Trades")
    
    tab1, tab2, tab3 = st.tabs(["Open Positions", "Trade History", "Performance"])
    
    with tab1:
        st.subheader("Open Positions")
        st.info("No open positions currently")
    
    with tab2:
        st.subheader("Recent Trades")
        trades_df = get_recent_trades(20)
        if not trades_df.empty:
            st.dataframe(trades_df, use_container_width=True)
        else:
            st.info("No trades yet")
    
    with tab3:
        st.subheader("Trade Performance Metrics")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Win Rate", "0%", delta=None)
        with col2:
            st.metric("Profit Factor", "0.0", delta=None)
        with col3:
            st.metric("Max Drawdown", "0.0%", delta=None)


def page_briefing():
    """Daily Briefing page."""
    st.title("📋 Daily Briefing")
    
    st.subheader("Morning Report")
    st.info("Today's premarket briefing would display here")
    
    tab1, tab2, tab3 = st.tabs(["Asset Selection", "Event Analysis", "Predictions"])
    
    with tab1:
        st.subheader("Selected Assets for Today")
        st.info("Selected trading assets and opportunity scores")
    
    with tab2:
        st.subheader("Historical Pattern Analysis")
        st.info("Active event patterns and their influence")
    
    with tab3:
        st.subheader("Prediction Accuracy")
        st.info("Morning predictions vs actual outcomes")


def page_insights():
    """AI Insights page."""
    st.title("🤖 AI Insights")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Model Consensus")
        st.info("Groq vs Gemini scores over time")
    
    with col2:
        st.subheader("Score Distribution")
        st.metric("Avg Groq Score", "0.50", delta=None)
        st.metric("Avg Gemini Score", "0.50", delta=None)
    
    st.divider()
    
    st.subheader("News Sentiment")
    st.info("Latest headlines with sentiment analysis")
    
    st.divider()
    
    st.subheader("Risk Flags")
    st.warning("⚠ Monitoring for critical patterns")


def page_control():
    """Control Panel page."""
    st.title("⚙️ Control Panel")
    
    tab1, tab2, tab3 = st.tabs(["Commands", "Settings", "System"])
    
    with tab1:
        st.subheader("Natural Language Commands")
        command = st.text_input("Enter command:", placeholder="e.g., 'Pause trading', 'Show today's briefing'")
        if st.button("Execute"):
            st.info(f"Command received: {command}")
    
    with tab2:
        st.subheader("Trading Parameters")
        
        col1, col2 = st.columns(2)
        with col1:
            risk = st.slider("Risk Per Trade (%)", 0.5, 5.0, 2.0)
            paper = st.toggle("Paper Trading", value=True)
        
        with col2:
            daily_limit = st.slider("Daily Loss Limit (%)", 1.0, 10.0, 5.0)
            max_pos = st.slider("Max Positions", 1, 10, 3)
        
        if st.button("Apply Settings"):
            st.success("Settings updated!")
    
    with tab3:
        st.subheader("System Status")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("▶ Start Bot"):
                st.success("Bot started")
        
        with col2:
            if st.button("⏸ Pause Bot"):
                st.warning("Bot paused")
        
        with col3:
            if st.button("🔴 Stop Bot"):
                st.error("Bot stopped")


def main():
    """Main dashboard app."""
    st.sidebar.title("🤖 Trading Bot")
    
    # Navigation
    page = st.sidebar.radio(
        "Navigate to:",
        [
            "📊 Overview",
            "💼 Positions",
            "📋 Briefing",
            "🤖 Insights",
            "⚙️ Control",
        ],
    )
    
    st.sidebar.divider()
    
    # Status sidebar
    status = get_bot_status()
    st.sidebar.write("### Status")
    st.sidebar.write(f"**Mode:** {'PAPER' if status['paper_trading'] else 'LIVE'}")
    st.sidebar.write(f"**Running:** {'Yes ▶' if not status['paused'] else 'No ⏸'}")
    st.sidebar.write(f"**Briefing:** {'Ready ✓' if status['briefing_complete'] else 'Pending...'}")
    
    st.sidebar.divider()
    st.sidebar.write("**Last Updated:** " + wat_now().strftime("%H:%M:%S WAT"))
    
    # Route to page
    if page == "📊 Overview":
        page_overview()
    elif page == "💼 Positions":
        page_positions()
    elif page == "📋 Briefing":
        page_briefing()
    elif page == "🤖 Insights":
        page_insights()
    elif page == "⚙️ Control":
        page_control()
    
    # Auto-refresh
    st.sidebar.divider()
    st.markdown("---")
    st.markdown(
        "<small>Dashboard auto-refreshes every 30 seconds. Last refresh: "
        + wat_now().strftime("%H:%M:%S WAT") + "</small>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
