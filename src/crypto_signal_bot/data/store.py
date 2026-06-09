from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.data.models import Candle


class SchemaValidationError(RuntimeError):
    """Raised when a local database is missing required schema objects."""


@dataclass(frozen=True)
class Migration:
    id: int
    name: str
    statements: tuple[str, ...]


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

CREATE TABLE IF NOT EXISTS notification_outbox (
  id TEXT PRIMARY KEY,
  alert_event_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  destination_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  claimed_at_utc TEXT,
  completed_at_utc TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  last_error_code TEXT,
  last_error_message TEXT,
  provider_response_json TEXT,
  UNIQUE(alert_event_id, channel, destination_hash)
);

CREATE TABLE IF NOT EXISTS notification_channel_state (
  channel TEXT NOT NULL,
  destination_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  last_error_code TEXT,
  last_error_at_utc TEXT,
  retry_after_until_utc TEXT,
  manual_reset_required INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(channel, destination_hash)
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

INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_notification_deliveries_attempted_status
ON notification_deliveries(attempted_at_utc, status);

CREATE INDEX IF NOT EXISTS idx_alert_events_lookup
ON alert_events(id, exchange, symbol, interval, severity, event_type);

CREATE INDEX IF NOT EXISTS idx_notification_outbox_status_created
ON notification_outbox(status, created_at_utc);

CREATE INDEX IF NOT EXISTS idx_notification_channel_state_channel_hash
ON notification_channel_state(channel, destination_hash);
"""

SCHEMA_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at_utc TEXT NOT NULL
)
"""


def _split_sql_script(script: str) -> tuple[str, ...]:
    return tuple(statement.strip() for statement in script.split(";") if statement.strip())


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "baseline_schema", _split_sql_script(SCHEMA)),
    Migration(2, "audit_indexes", _split_sql_script(INDEX_SCHEMA)),
)

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "schema_migrations": {"id", "name", "applied_at_utc"},
    "candles": {
        "exchange",
        "symbol",
        "interval",
        "open_time_utc",
        "close_time_utc",
        "open",
        "high",
        "low",
        "close",
        "base_volume",
        "quote_volume",
        "trade_count",
        "is_closed",
    },
    "alert_events": {
        "id",
        "created_at_utc",
        "exchange",
        "symbol",
        "interval",
        "event_type",
        "severity",
        "score",
        "previous_score",
        "confidence",
        "drivers_json",
        "risk_flags_json",
        "invalidation",
        "payload_json",
        "dedupe_key",
        "source_run_id",
    },
    "notification_deliveries": {
        "id",
        "alert_event_id",
        "channel",
        "destination",
        "status",
        "attempted_at_utc",
        "delivered_at_utc",
        "error_code",
        "error_message",
        "retry_count",
        "provider_response_json",
    },
    "notification_outbox": {
        "id",
        "alert_event_id",
        "channel",
        "destination_hash",
        "status",
        "created_at_utc",
        "claimed_at_utc",
        "completed_at_utc",
        "retry_count",
        "last_error_code",
        "last_error_message",
        "provider_response_json",
    },
    "notification_channel_state": {
        "channel",
        "destination_hash",
        "status",
        "last_error_code",
        "last_error_at_utc",
        "retry_after_until_utc",
        "manual_reset_required",
    },
    "alert_state": {
        "exchange",
        "symbol",
        "interval",
        "event_type",
        "active",
        "entered_at_utc",
        "exited_at_utc",
        "last_alerted_at_utc",
        "last_score",
        "last_dedupe_key",
    },
}

REQUIRED_INDEXES = {
    "idx_notification_deliveries_attempted_status",
    "idx_alert_events_lookup",
    "idx_notification_outbox_status_created",
    "idx_notification_channel_state_channel_hash",
}


class SQLiteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        self.run_migrations()
        self.validate_schema()

    def run_migrations(self, migrations: Sequence[Migration] | None = None) -> list[int]:
        selected = tuple(migrations or MIGRATIONS)
        applied_now: list[int] = []
        with self.connect() as conn:
            conn.execute(SCHEMA_MIGRATIONS_TABLE)
            conn.commit()
            applied = {
                int(row["id"])
                for row in conn.execute("SELECT id FROM schema_migrations").fetchall()
            }
            for migration in selected:
                if migration.id in applied:
                    continue
                try:
                    conn.execute("BEGIN")
                    for statement in migration.statements:
                        conn.execute(statement)
                    conn.execute(
                        """
                        INSERT INTO schema_migrations(id, name, applied_at_utc)
                        VALUES (?, ?, ?)
                        """,
                        (migration.id, migration.name, datetime.now(tz=UTC).isoformat()),
                    )
                    conn.execute("COMMIT")
                    applied_now.append(migration.id)
                    applied.add(migration.id)
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        return applied_now

    def applied_migrations(self) -> list[int]:
        if not self.path.exists():
            return []
        with self.connect() as conn:
            if "schema_migrations" not in _table_names(conn):
                return []
            rows = conn.execute("SELECT id FROM schema_migrations ORDER BY id").fetchall()
        return [int(row["id"]) for row in rows]

    def validate_schema(self) -> None:
        if not self.path.exists():
            raise SchemaValidationError("Database file does not exist.")
        with self.connect() as conn:
            tables = _table_names(conn)
            missing_tables = sorted(set(REQUIRED_COLUMNS) - tables)
            if missing_tables:
                raise SchemaValidationError(f"Missing tables: {', '.join(missing_tables)}")
            missing_columns: list[str] = []
            for table, required_columns in REQUIRED_COLUMNS.items():
                columns = _table_columns(conn, table)
                for column in sorted(required_columns - columns):
                    missing_columns.append(f"{table}.{column}")
            if missing_columns:
                raise SchemaValidationError(f"Missing columns: {', '.join(missing_columns)}")
            indexes = _index_names(conn)
            missing_indexes = sorted(REQUIRED_INDEXES - indexes)
            if missing_indexes:
                raise SchemaValidationError(f"Missing indexes: {', '.join(missing_indexes)}")

    def schema_status(self) -> dict[str, object]:
        status: dict[str, object] = {
            "database_path": str(self.path),
            "exists": self.path.exists(),
            "latest_available_migration": max(migration.id for migration in MIGRATIONS),
            "applied_migrations": self.applied_migrations(),
            "valid": False,
            "error": None,
        }
        try:
            self.validate_schema()
        except SchemaValidationError as exc:
            status["error"] = str(exc)
        else:
            status["valid"] = True
        return status

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

    def count_recent_notification_events(self, since_utc: str) -> int:
        self.init_schema()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT alert_event_id) AS count
                FROM notification_deliveries d
                JOIN alert_events e ON e.id = d.alert_event_id
                WHERE d.attempted_at_utc >= ?
                  AND d.status != 'suppressed_by_rate_limit'
                """,
                (since_utc,),
            ).fetchone()
        return int(row["count"])

    def count_recent_notification_events_by_priority(self, since_utc: str, priority: str) -> int:
        self.init_schema()
        priority_sql = _priority_sql(priority)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(DISTINCT d.alert_event_id) AS count
                FROM notification_deliveries d
                JOIN alert_events e ON e.id = d.alert_event_id
                WHERE d.attempted_at_utc >= ?
                  AND d.status != 'suppressed_by_rate_limit'
                  AND {priority_sql}
                """,
                (since_utc,),
            ).fetchone()
        return int(row["count"])

    def count_recent_symbol_notification_events(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        since_utc: str,
    ) -> int:
        self.init_schema()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT d.alert_event_id) AS count
                FROM notification_deliveries d
                JOIN alert_events e ON e.id = d.alert_event_id
                WHERE d.attempted_at_utc >= ?
                  AND d.status != 'suppressed_by_rate_limit'
                  AND e.exchange = ?
                  AND e.symbol = ?
                  AND e.interval = ?
                """,
                (since_utc, exchange, symbol, interval),
            ).fetchone()
        return int(row["count"])

    def count_recent_symbol_notification_events_by_priority(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        since_utc: str,
        priority: str,
    ) -> int:
        self.init_schema()
        priority_sql = _priority_sql(priority)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(DISTINCT d.alert_event_id) AS count
                FROM notification_deliveries d
                JOIN alert_events e ON e.id = d.alert_event_id
                WHERE d.attempted_at_utc >= ?
                  AND d.status != 'suppressed_by_rate_limit'
                  AND e.exchange = ?
                  AND e.symbol = ?
                  AND e.interval = ?
                  AND {priority_sql}
                """,
                (since_utc, exchange, symbol, interval),
            ).fetchone()
        return int(row["count"])

    def insert_notification_outbox(
        self,
        *,
        alert_event_id: str,
        channel: str,
        destination_hash: str,
        created_at_utc: str,
    ) -> str:
        self.init_schema()
        outbox_id = f"{alert_event_id}:{channel}:{destination_hash[:16]}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO notification_outbox VALUES
                (?, ?, ?, ?, 'pending', ?, NULL, NULL, 0, NULL, NULL, NULL)
                """,
                (outbox_id, alert_event_id, channel, destination_hash, created_at_utc),
            )
        return outbox_id

    def claim_notification_outbox(
        self,
        *,
        alert_event_id: str,
        channel: str,
        destination_hash: str,
        claimed_at_utc: str,
    ) -> str | None:
        self.init_schema()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM notification_outbox
                WHERE alert_event_id=? AND channel=? AND destination_hash=?
                  AND status IN ('pending', 'failed_retryable')
                """,
                (alert_event_id, channel, destination_hash),
            ).fetchone()
            if row is None:
                return None
            outbox_id = str(row["id"])
            conn.execute(
                """
                UPDATE notification_outbox
                SET status='claimed', claimed_at_utc=?
                WHERE id=?
                """,
                (claimed_at_utc, outbox_id),
            )
        return outbox_id

    def list_notification_outbox(
        self,
        *,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        self.init_schema()
        sql = """
            SELECT * FROM notification_outbox
        """
        params: list[object] = []
        if status is not None:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY created_at_utc ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            return list(conn.execute(sql, params))

    def complete_notification_outbox(
        self,
        *,
        outbox_id: str,
        status: str,
        completed_at_utc: str,
        retry_count: int,
        last_error_code: str | None,
        last_error_message: str | None,
        provider_response: object,
    ) -> None:
        self.init_schema()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE notification_outbox
                SET status=?,
                    completed_at_utc=?,
                    retry_count=?,
                    last_error_code=?,
                    last_error_message=?,
                    provider_response_json=?
                WHERE id=?
                """,
                (
                    status,
                    completed_at_utc,
                    retry_count,
                    last_error_code,
                    last_error_message,
                    json.dumps(provider_response),
                    outbox_id,
                ),
            )

    def fetch_alert_event(self, alert_event_id: str) -> AlertEvent | None:
        self.init_schema()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM alert_events WHERE id=?",
                (alert_event_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_alert_event(json.loads(str(row["payload_json"])))

    def get_notification_channel_state(
        self,
        channel: str,
        destination_hash: str,
    ) -> sqlite3.Row | None:
        self.init_schema()
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM notification_channel_state
                WHERE channel=? AND destination_hash=?
                """,
                (channel, destination_hash),
            ).fetchone()

    def upsert_notification_channel_state(
        self,
        *,
        channel: str,
        destination_hash: str,
        status: str,
        last_error_code: str | None,
        last_error_at_utc: str | None,
        retry_after_until_utc: str | None,
        manual_reset_required: bool,
    ) -> None:
        self.init_schema()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notification_channel_state VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel, destination_hash) DO UPDATE SET
                  status=excluded.status,
                  last_error_code=excluded.last_error_code,
                  last_error_at_utc=excluded.last_error_at_utc,
                  retry_after_until_utc=excluded.retry_after_until_utc,
                  manual_reset_required=excluded.manual_reset_required
                """,
                (
                    channel,
                    destination_hash,
                    status,
                    last_error_code,
                    last_error_at_utc,
                    retry_after_until_utc,
                    int(manual_reset_required),
                ),
            )

    def list_notification_channel_states(self) -> list[sqlite3.Row]:
        self.init_schema()
        with self.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT * FROM notification_channel_state
                    ORDER BY channel, destination_hash
                    """
                )
            )

    def reset_notification_channel_state(self, channel: str, destination_hash: str) -> int:
        self.init_schema()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM notification_channel_state
                WHERE channel=? AND destination_hash=?
                """,
                (channel, destination_hash),
            )
            return int(cursor.rowcount)

    def notification_status_summary(self) -> dict[str, object]:
        self.init_schema()
        with self.connect() as conn:
            outbox_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM notification_outbox
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()
            channel_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM notification_channel_state
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()
        return {
            "outbox": {str(row["status"]): int(row["count"]) for row in outbox_rows},
            "channel_state": {str(row["status"]): int(row["count"]) for row in channel_rows},
        }


def _quote_like(exchange: str, quote: str) -> str:
    if exchange == "upbit":
        return f"{quote}-%"
    return f"%{quote}"


def _priority_sql(priority: str) -> str:
    safety_condition = (
        "(e.severity IN ('WARNING', 'CRITICAL') "
        "OR e.event_type IN ('RISK_WARNING', 'INVALIDATION', "
        "'DATA_QUALITY_WARNING', 'SYSTEM_ERROR'))"
    )
    if priority == "safety":
        return safety_condition
    if priority == "watch":
        return f"NOT {safety_condition}"
    raise ValueError(f"Unknown notification priority: {priority}")


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='table'
        """
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='index'
        """
    ).fetchall()
    return {str(row["name"]) for row in rows}


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


def _row_to_alert_event(payload: dict[str, Any]) -> AlertEvent:
    drivers_payload = payload.get("drivers", [])
    risk_flags_payload = payload.get("risk_flags", [])
    drivers = drivers_payload if isinstance(drivers_payload, list) else []
    risk_flags = risk_flags_payload if isinstance(risk_flags_payload, list) else []
    return AlertEvent(
        alert_event_id=str(payload["alert_event_id"]),
        created_at_utc=datetime.fromisoformat(str(payload["created_at_utc"])),
        exchange=str(payload["exchange"]),
        symbol=str(payload["symbol"]),
        interval=str(payload["interval"]),
        event_type=str(payload["event_type"]),
        severity=str(payload["severity"]),
        score=float(payload["score"]),
        previous_score=None if payload["previous_score"] is None else float(payload["previous_score"]),
        confidence=str(payload["confidence"]),
        current_price=None if payload["current_price"] is None else float(payload["current_price"]),
        rank=None if payload["rank"] is None else int(payload["rank"]),
        drivers=[str(item) for item in drivers],
        risk_flags=[str(item) for item in risk_flags],
        invalidation_condition=str(payload["invalidation_condition"]),
        data_timestamp_utc=str(payload["data_timestamp_utc"]),
        dedupe_key=str(payload["dedupe_key"]),
        source_run_id=str(payload["source_run_id"]),
        notification_status=str(payload.get("notification_status", "pending")),
    )
