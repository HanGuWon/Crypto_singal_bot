from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from crypto_signal_bot.data.models import Candle

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
  exchange TEXT NOT NULL,
  symbol TEXT NOT NULL,
  interval TEXT NOT NULL,
  open_time_utc TEXT NOT NULL,
  close_time_utc TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  base_volume REAL,
  quote_volume REAL,
  trade_count INTEGER,
  is_closed INTEGER NOT NULL,
  PRIMARY KEY(exchange, symbol, interval, open_time_utc)
);

CREATE TABLE IF NOT EXISTS tickers (
  exchange TEXT NOT NULL,
  symbol TEXT NOT NULL,
  event_time_utc TEXT NOT NULL,
  price REAL NOT NULL,
  quote_volume_24h REAL,
  base_volume_24h REAL,
  price_change_pct_24h REAL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(exchange, symbol, event_time_utc)
);

CREATE TABLE IF NOT EXISTS orderbooks (
  exchange TEXT NOT NULL,
  symbol TEXT NOT NULL,
  event_time_utc TEXT NOT NULL,
  best_bid REAL,
  best_ask REAL,
  spread_bps REAL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(exchange, symbol, event_time_utc)
);

CREATE TABLE IF NOT EXISTS alert_events (
  id TEXT PRIMARY KEY,
  created_at_utc TEXT NOT NULL,
  exchange TEXT NOT NULL,
  symbol TEXT NOT NULL,
  interval TEXT NOT NULL,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  score REAL NOT NULL,
  previous_score REAL,
  confidence TEXT NOT NULL,
  drivers_json TEXT NOT NULL,
  risk_flags_json TEXT NOT NULL,
  invalidation TEXT,
  payload_json TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  source_run_id TEXT
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
  id TEXT PRIMARY KEY,
  alert_event_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  destination TEXT NOT NULL,
  status TEXT NOT NULL,
  attempted_at_utc TEXT NOT NULL,
  delivered_at_utc TEXT,
  error_code TEXT,
  error_message TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  provider_response_json TEXT
);

CREATE TABLE IF NOT EXISTS alert_state (
  exchange TEXT NOT NULL,
  symbol TEXT NOT NULL,
  interval TEXT NOT NULL,
  event_type TEXT NOT NULL,
  active INTEGER NOT NULL,
  entered_at_utc TEXT,
  exited_at_utc TEXT,
  last_alerted_at_utc TEXT,
  last_score REAL,
  last_dedupe_key TEXT,
  PRIMARY KEY(exchange, symbol, interval, event_type)
);
"""


class SQLiteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def upsert_candles(self, candles: Iterable[Candle]) -> int:
        rows = [candle.to_row() for candle in candles]
        if not rows:
            return 0
        self.init_schema()
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, symbol, interval, open_time_utc) DO UPDATE SET
                  close_time_utc=excluded.close_time_utc,
                  open=excluded.open,
                  high=excluded.high,
                  low=excluded.low,
                  close=excluded.close,
                  base_volume=excluded.base_volume,
                  quote_volume=excluded.quote_volume,
                  trade_count=excluded.trade_count,
                  is_closed=excluded.is_closed
                """,
                rows,
            )
        return len(rows)

    def fetch_candles(
        self, exchange: str, symbol: str, interval: str, limit: int | None = None
    ) -> list[Candle]:
        self.init_schema()
        sql = """
            SELECT * FROM candles
            WHERE exchange=? AND symbol=? AND interval=?
            ORDER BY open_time_utc ASC
        """
        params: list[object] = [exchange, symbol, interval]
        if limit is not None:
            sql = f"SELECT * FROM ({sql}) ORDER BY open_time_utc DESC LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = list(conn.execute(sql, params))
        if limit is not None:
            rows = list(reversed(rows))
        return [_row_to_candle(row) for row in rows]

    def list_symbols(self, exchange: str, quote: str, interval: str) -> list[str]:
        self.init_schema()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT symbol FROM candles
                WHERE exchange=? AND interval=? AND symbol LIKE ?
                ORDER BY symbol
                """,
                (exchange, interval, _quote_like(exchange, quote)),
            ).fetchall()
        return [str(row["symbol"]) for row in rows]

    def insert_alert_event(self, event: object) -> None:
        self.init_schema()
        payload = event.to_dict()  # type: ignore[attr-defined]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO alert_events VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["alert_event_id"],
                    payload["created_at_utc"],
                    payload["exchange"],
                    payload["symbol"],
                    payload["interval"],
                    payload["event_type"],
                    payload["severity"],
                    payload["score"],
                    payload["previous_score"],
                    payload["confidence"],
                    json.dumps(payload["drivers"]),
                    json.dumps(payload["risk_flags"]),
                    payload["invalidation_condition"],
                    json.dumps(payload),
                    payload["dedupe_key"],
                    payload["source_run_id"],
                ),
            )

    def insert_notification_delivery(self, record: dict[str, object]) -> None:
        self.init_schema()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notification_deliveries VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["alert_event_id"],
                    record["channel"],
                    record["destination"],
                    record["status"],
                    record["attempted_at_utc"],
                    record["delivered_at_utc"],
                    record["error_code"],
                    record["error_message"],
                    record["retry_count"],
                    json.dumps(record["provider_response"]),
                ),
            )


def _quote_like(exchange: str, quote: str) -> str:
    if exchange == "upbit":
        return f"{quote}-%"
    return f"%{quote}"


def _row_to_candle(row: sqlite3.Row) -> Candle:
    return Candle(
        exchange=row["exchange"],
        symbol=row["symbol"],
        interval=row["interval"],
        open_time_utc=datetime.fromisoformat(row["open_time_utc"]),
        close_time_utc=datetime.fromisoformat(row["close_time_utc"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        base_volume=None if row["base_volume"] is None else float(row["base_volume"]),
        quote_volume=None if row["quote_volume"] is None else float(row["quote_volume"]),
        trade_count=None if row["trade_count"] is None else int(row["trade_count"]),
        is_closed=bool(row["is_closed"]),
    )
