"""SQLite persistence helpers for bot state."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


class Storage:
    """Simple SQLite storage wrapper."""

    def __init__(self, db_path: Path) -> None:
        """Create a storage wrapper."""

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured SQLite connection."""

        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        """Create required tables if missing."""

        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS candles (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    PRIMARY KEY (exchange, symbol, timeframe, timestamp)
                );
                CREATE TABLE IF NOT EXISTS headlines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    published_at TEXT NOT NULL,
                    sentiment_score REAL,
                    fetched_at TEXT NOT NULL,
                    metadata TEXT
                );
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    size REAL NOT NULL,
                    pnl REAL,
                    signal_score REAL NOT NULL,
                    status TEXT NOT NULL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    metadata TEXT
                );
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    score REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    breakdown TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS daily_pnl (
                    date TEXT PRIMARY KEY,
                    starting_balance REAL NOT NULL,
                    ending_balance REAL NOT NULL,
                    trades_taken INTEGER NOT NULL,
                    wins INTEGER NOT NULL,
                    losses INTEGER NOT NULL,
                    gross_pnl REAL NOT NULL,
                    fees_paid REAL NOT NULL,
                    net_pnl REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reports (
                    report_type TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (report_type, report_date)
                );
                """
            )
            self._ensure_column(connection, "headlines", "metadata", "TEXT")

    def _ensure_column(self, connection: sqlite3.Connection, table_name: str, column_name: str, sql_type: str) -> None:
        """Add a column when it is missing."""

        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing = {row["name"] for row in rows}
        if column_name not in existing:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}")

    def insert_candles(self, exchange: str, symbol: str, timeframe: str, candles: list[list[float]]) -> None:
        """Persist OHLCV candles."""

        with self.connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO candles
                (exchange, symbol, timeframe, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(exchange, symbol, timeframe, *candle[:6]) for candle in candles],
            )

    def find_recent_headline(self, asset: str, title: str, since_iso: str) -> list[dict[str, Any]]:
        """Return recent headlines for deduplication checks."""

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT source, asset, title, url, published_at, sentiment_score, fetched_at, metadata
                FROM headlines
                WHERE asset = ? AND published_at >= ?
                """,
                (asset, since_iso),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_headlines(self, asset: str, headlines: list[dict[str, Any]]) -> None:
        """Persist deduplicated headlines."""

        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO headlines (source, asset, title, url, published_at, sentiment_score, fetched_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.get("source", "unknown"),
                        asset,
                        item["headline"],
                        item.get("url"),
                        item.get("published_at", datetime.now(UTC).isoformat()),
                        item.get("score"),
                        datetime.now(UTC).isoformat(),
                        json.dumps(item.get("metadata", {})),
                    )
                    for item in headlines
                ],
            )

    def upsert_position(self, symbol: str, payload: dict[str, Any]) -> None:
        """Persist an open position."""

        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO positions (symbol, payload) VALUES (?, ?)",
                (symbol, json.dumps(payload)),
            )

    def remove_position(self, symbol: str) -> None:
        """Delete an open position."""

        with self.connect() as connection:
            connection.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))

    def load_positions(self) -> dict[str, dict[str, Any]]:
        """Load all open positions."""

        with self.connect() as connection:
            rows = connection.execute("SELECT symbol, payload FROM positions").fetchall()
        return {row["symbol"]: json.loads(row["payload"]) for row in rows}

    def save_trade(self, payload: dict[str, Any]) -> None:
        """Insert or replace a trade record."""

        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO trades
                (trade_id, symbol, side, entry_price, exit_price, size, pnl, signal_score, status, entry_time, exit_time, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["trade_id"],
                    payload["asset"],
                    payload["side"],
                    payload["entry_price"],
                    payload.get("exit_price"),
                    payload["size"],
                    payload.get("pnl"),
                    payload["signal_score"],
                    payload["status"],
                    payload["entry_time"],
                    payload.get("exit_time"),
                    json.dumps(payload.get("metadata", {})),
                ),
            )

    def save_signal(self, symbol: str, action: str, score: float, breakdown: dict[str, Any]) -> None:
        """Persist a signal decision."""

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO signals (symbol, action, score, created_at, breakdown)
                VALUES (?, ?, ?, ?, ?)
                """,
                (symbol, action, score, datetime.now(UTC).isoformat(), json.dumps(breakdown)),
            )

    def save_daily_pnl(self, payload: dict[str, Any]) -> None:
        """Persist a daily PnL summary."""

        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO daily_pnl
                (date, starting_balance, ending_balance, trades_taken, wins, losses, gross_pnl, fees_paid, net_pnl)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["date"],
                    payload["starting_balance"],
                    payload["ending_balance"],
                    payload["trades_taken"],
                    payload["wins"],
                    payload["losses"],
                    payload["gross_pnl"],
                    payload["fees_paid"],
                    payload["net_pnl"],
                ),
            )

    def save_report(self, report_type: str, report_date: str, payload: dict[str, Any]) -> None:
        """Persist a structured report."""

        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO reports (report_type, report_date, payload)
                VALUES (?, ?, ?)
                """,
                (report_type, report_date, json.dumps(payload)),
            )

    def fetch_report(self, report_type: str, report_date: str) -> dict[str, Any] | None:
        """Load a report by type and date."""

        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM reports WHERE report_type = ? AND report_date = ?",
                (report_type, report_date),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def set_state(self, key: str, value: Any) -> None:
        """Persist a bot state value."""

        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

    def get_state(self, key: str, default: Any = None) -> Any:
        """Read a stored bot state value."""

        with self.connect() as connection:
            row = connection.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def fetch_trades(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return recent trades."""

        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_signals(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return recent signals."""

        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_daily_pnl(self, limit: int = 30) -> list[dict[str, Any]]:
        """Return recent daily PnL summaries."""

        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM daily_pnl ORDER BY date DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
