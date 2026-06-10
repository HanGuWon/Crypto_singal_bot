from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.cli import main
from crypto_signal_bot.data.models import Candle
from crypto_signal_bot.data.store import MIGRATIONS, Migration, SQLiteStore


def test_fresh_database_bootstraps_and_validates(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "fresh.sqlite")

    store.init_schema()

    status = store.schema_status()
    assert status["valid"] is True
    assert status["applied_migrations"] == [migration.id for migration in MIGRATIONS]


def test_migration_is_idempotent(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "idempotent.sqlite")

    first = store.run_migrations()
    second = store.run_migrations()

    assert first == [migration.id for migration in MIGRATIONS]
    assert second == []
    store.validate_schema()


def test_upgrade_from_pre_outbox_schema(tmp_path) -> None:
    db_path = tmp_path / "pre_outbox.sqlite"
    _create_pre_outbox_schema(db_path)
    store = SQLiteStore(db_path)

    applied = store.run_migrations()

    assert applied == [migration.id for migration in MIGRATIONS]
    store.validate_schema()
    assert _table_exists(db_path, "notification_outbox")
    assert _table_exists(db_path, "notification_channel_state")
    assert _table_exists(db_path, "symbol_health")
    assert _table_exists(db_path, "research_runs")
    assert _table_exists(db_path, "feature_snapshots")
    assert _table_exists(db_path, "entry_timing_snapshots")
    assert _table_exists(db_path, "manual_approval_requests")


def test_upgrade_from_pre_channel_state_schema(tmp_path) -> None:
    db_path = tmp_path / "pre_channel_state.sqlite"
    _create_pre_channel_state_schema(db_path)
    store = SQLiteStore(db_path)

    store.run_migrations()

    store.validate_schema()
    assert _table_exists(db_path, "notification_channel_state")
    assert _table_exists(db_path, "symbol_health")
    assert _table_exists(db_path, "research_runs")
    assert _table_exists(db_path, "feature_snapshots")
    assert _table_exists(db_path, "entry_timing_snapshots")
    assert _table_exists(db_path, "manual_approval_requests")


def test_upgrade_from_manual_approval_schema_without_binding_hash(tmp_path) -> None:
    db_path = tmp_path / "pre_manual_approval_binding.sqlite"
    store = SQLiteStore(db_path)

    first_applied = store.run_migrations(MIGRATIONS[:6])
    assert first_applied == [migration.id for migration in MIGRATIONS[:6]]
    assert not _column_exists(db_path, "manual_approval_requests", "binding_hash")

    applied = store.run_migrations()

    assert applied == [7]
    store.validate_schema()
    assert _column_exists(db_path, "manual_approval_requests", "binding_hash")
    assert _index_exists(db_path, "idx_manual_approval_binding")


def test_entry_timing_snapshot_insert_is_idempotent(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "entry_timing.sqlite")
    record = {
        "id": "run:binance:TESTUSDT:5m:three_tick_bottoming",
        "run_id": "run",
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "exchange": "binance",
        "symbol": "TESTUSDT",
        "interval": "5m",
        "strategy": "three_tick_bottoming",
        "status": "watch",
        "entry_timing_score": 72.0,
        "research_priority_score": 80.0,
        "upside_score": 84.0,
        "data_timestamp_utc": "2026-01-01T00:00:00+00:00",
        "reason_codes": ["entry_timing_watch"],
        "risk_flags": [],
        "payload": {"research_warning": "Research watchlist only. Not financial advice. No order was placed."},
    }

    store.insert_entry_timing_snapshot(record)
    updated = {**record, "status": "confirmed_candidate", "entry_timing_score": 88.0}
    store.insert_entry_timing_snapshot(updated)

    rows = store.get_entry_timing_snapshots("run")
    assert len(rows) == 1
    assert rows[0]["status"] == "confirmed_candidate"
    assert rows[0]["entry_timing_score"] == 88.0


def test_candle_retention_prune_dry_run_and_execute(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "retention.sqlite")
    now = datetime(2026, 1, 10, tzinfo=UTC)
    store.upsert_candles(
        [
            _retention_candle("old", "5m", now - timedelta(days=50)),
            _retention_candle("fresh", "5m", now - timedelta(days=10)),
            _retention_candle("old-15m", "15m", now - timedelta(days=100)),
        ]
    )

    dry_run = store.prune_candles_by_retention({"5m": 45, "15m": 90}, now_utc=now)

    assert sum(int(row["matched_candles"]) for row in dry_run) == 2
    assert sum(int(row["deleted_candles"]) for row in dry_run) == 0
    assert len(store.fetch_candles("binance", "BTCUSDT", "5m")) == 2

    executed = store.prune_candles_by_retention(
        {"5m": 45, "15m": 90},
        now_utc=now,
        dry_run=False,
    )

    assert sum(int(row["deleted_candles"]) for row in executed) == 2
    assert [candle.symbol for candle in store.fetch_candles("binance", "BTCUSDT", "5m")] == ["BTCUSDT"]
    assert store.fetch_candles("binance", "ETHUSDT", "15m") == []


def test_failed_migration_rolls_back(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "rollback.sqlite")
    bad_migration = Migration(
        99,
        "bad_migration",
        (
            "CREATE TABLE rollback_probe (id INTEGER PRIMARY KEY)",
            "INSERT INTO table_that_does_not_exist VALUES (1)",
        ),
    )

    try:
        store.run_migrations([bad_migration])
    except sqlite3.Error:
        pass
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Bad migration should fail.")

    assert 99 not in store.applied_migrations()
    assert not _table_exists(store.path, "rollback_probe")


def test_db_migrate_and_doctor_cli(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "cli.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    assert main(["db", "migrate"]) == 0
    assert main(["db", "doctor"]) == 0


def test_db_prune_retention_cli_dry_run_and_execute(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "cli-retention.sqlite"
    profile_path = tmp_path / "gcp_free_tier.yaml"
    profile_path.write_text("retention:\n  5m_days: 45\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    store = SQLiteStore(db_path)
    old_time = datetime.now(tz=UTC) - timedelta(days=50)
    fresh_time = datetime.now(tz=UTC) - timedelta(days=5)
    store.upsert_candles([
        _retention_candle("old", "5m", old_time),
        _retention_candle("fresh", "5m", fresh_time),
    ])

    assert main(["db", "prune-retention", "--profile", str(profile_path)]) == 0
    dry_payload = capsys.readouterr().out
    assert '"dry_run": true' in dry_payload
    assert '"matched_candles": 1' in dry_payload
    assert len(store.fetch_candles("binance", "BTCUSDT", "5m")) == 2

    assert main(["db", "prune-retention", "--profile", str(profile_path), "--execute"]) == 0
    executed_payload = capsys.readouterr().out
    assert '"dry_run": false' in executed_payload
    assert '"deleted_candles": 1' in executed_payload
    assert len(store.fetch_candles("binance", "BTCUSDT", "5m")) == 1


def test_db_prune_retention_rejects_invalid_policy(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "cli-retention.sqlite"))

    assert main(["db", "prune-retention", "--policy", "5m=-1"]) == 2

    assert "Retention days must be positive integers" in capsys.readouterr().err


def test_db_doctor_reports_invalid_database(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "missing.sqlite"))

    assert main(["db", "doctor"]) == 1


def _retention_candle(symbol_hint: str, interval: str, open_time: datetime) -> Candle:
    symbol = "ETHUSDT" if symbol_hint.endswith("15m") else "BTCUSDT"
    return Candle(
        exchange="binance",
        symbol=symbol,
        interval=interval,
        open_time_utc=open_time,
        close_time_utc=open_time + timedelta(minutes=5) - timedelta(milliseconds=1),
        open=100,
        high=101,
        low=99,
        close=100,
        base_volume=1,
        quote_volume=100,
        trade_count=1,
        is_closed=True,
    )


def _create_pre_outbox_schema(path) -> None:  # type: ignore[no-untyped-def]
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE candles (
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
            CREATE TABLE alert_events (
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
            CREATE TABLE notification_deliveries (
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
            CREATE TABLE alert_state (
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
        )


def _create_pre_channel_state_schema(path) -> None:  # type: ignore[no-untyped-def]
    _create_pre_outbox_schema(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE notification_outbox (
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
            )
            """
        )


def _table_exists(path, table: str) -> bool:  # type: ignore[no-untyped-def]
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    return row is not None


def _column_exists(path, table: str, column: str) -> bool:  # type: ignore[no-untyped-def]
    with sqlite3.connect(path) as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return column in {str(row[1]) for row in rows}


def _index_exists(path, index: str) -> bool:  # type: ignore[no-untyped-def]
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index,),
        ).fetchone()
    return row is not None
