from __future__ import annotations

import sqlite3

from crypto_signal_bot.cli import main
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


def test_db_doctor_reports_invalid_database(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "missing.sqlite"))

    assert main(["db", "doctor"]) == 1


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
