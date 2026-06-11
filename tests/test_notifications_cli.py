from __future__ import annotations

import json
from datetime import UTC, datetime

from conftest import make_alert, make_candidate
from crypto_signal_bot.cli import _previous_alert_policy_inputs, main
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.notifications.destinations import destination_hash


def test_notifications_status_outputs_counts(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "notifications.sqlite"))

    assert main(["notifications", "status"]) == 0

    output = capsys.readouterr().out
    assert "outbox" in output
    assert "channel_state" in output


def test_digest_preview_skips_when_digest_disabled(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "notifications.sqlite"))

    assert main(["notifications", "digest", "preview", "--exchange", "binance", "--quote", "USDT"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["digest_preview"] is None
    assert payload["notification_status"] == "skipped_disabled"
    assert payload["research_warning"].endswith("No order was placed.")


def test_digest_preview_force_builds_without_sending(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "notifications.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MIN_QUOTE_VOLUME_BINANCE_USDT", "0")

    assert (
        main([
            "notifications",
            "digest",
            "preview",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--top",
            "2",
            "--mock",
            "--force-preview",
        ])
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    digest = payload["digest_preview"]
    assert payload["preview_forced"] is True
    assert payload["notification_status"] == "preview_only_not_sent"
    assert digest["notification_status"] == "preview_only_not_sent"
    assert len(digest["top_candidates"]) <= 2
    assert digest["research_warning"].endswith("No order was placed.")
    assert SQLiteStore(db_path).notification_status_summary()["outbox"] == {}


def test_digest_schedule_status_reports_due_without_sending(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "notifications.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("ALERT_DIGEST_ENABLED", "true")
    monkeypatch.setenv("ALERT_DIGEST_INTERVAL_MINUTES", "60")

    assert (
        main([
            "notifications",
            "digest",
            "schedule-status",
            "--last-digest-at",
            "2026-01-01T00:00:00+00:00",
            "--now-utc",
            "2026-01-01T01:00:00+00:00",
        ])
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    schedule = payload["digest_schedule"]
    assert schedule["enabled"] is True
    assert schedule["due"] is True
    assert schedule["notification_status"] == "due"
    assert schedule["next_digest_at_utc"] == "2026-01-01T01:00:00+00:00"
    assert schedule["separate_policy_path"] is True
    assert schedule["scheduler_daemon_required"] is False
    assert schedule["no_notification_was_sent"] is True
    assert payload["research_warning"].endswith("No order was placed.")
    assert SQLiteStore(db_path).notification_status_summary()["outbox"] == {}


def test_digest_schedule_status_rejects_naive_timestamps(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "notifications.sqlite"))

    assert (
        main([
            "notifications",
            "digest",
            "schedule-status",
            "--last-digest-at",
            "2026-01-01T00:00:00",
        ])
        == 2
    )

    assert "--last-digest-at must include a timezone offset" in capsys.readouterr().err


def test_channel_state_list_uses_hashes_only(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "notifications.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    raw_destination = "https://discord.com/api/webhooks/123/secret"
    digest = destination_hash("discord", raw_destination)
    SQLiteStore(db_path).upsert_notification_channel_state(
        channel="discord",
        destination_hash=digest,
        status="invalid_destination",
        last_error_code="404",
        last_error_at_utc=datetime.now(tz=UTC).isoformat(),
        retry_after_until_utc=None,
        manual_reset_required=True,
    )

    assert main(["notifications", "channel-state", "list"]) == 0

    output = capsys.readouterr().out
    assert digest in output
    assert raw_destination not in output
    assert "secret" not in output


def test_channel_state_reset_requires_confirm(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "notifications.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    digest = destination_hash("telegram", "chat-1:token")
    store = SQLiteStore(db_path)
    store.upsert_notification_channel_state(
        channel="telegram",
        destination_hash=digest,
        status="invalid_credentials",
        last_error_code="401",
        last_error_at_utc=datetime.now(tz=UTC).isoformat(),
        retry_after_until_utc=None,
        manual_reset_required=True,
    )

    assert (
        main([
            "notifications",
            "channel-state",
            "reset",
            "--channel",
            "telegram",
            "--destination-hash",
            digest,
        ])
        == 2
    )
    assert store.get_notification_channel_state("telegram", digest) is not None

    assert (
        main([
            "notifications",
            "channel-state",
            "reset",
            "--channel",
            "telegram",
            "--destination-hash",
            digest,
            "--confirm",
        ])
        == 0
    )
    assert store.get_notification_channel_state("telegram", digest) is None


def test_outbox_list_and_drain_dry_run_exclude_terminal_rows(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "notifications.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    store = SQLiteStore(db_path)
    pending = make_alert(alert_event_id="pending-event")
    retryable = make_alert(alert_event_id="retryable-event")
    terminal = make_alert(alert_event_id="terminal-event")
    for event in [pending, retryable, terminal]:
        store.insert_alert_event(event)
    pending_id = store.insert_notification_outbox(
        alert_event_id=pending.alert_event_id,
        channel="telegram",
        destination_hash=destination_hash("telegram", "chat-1:token"),
        created_at_utc=datetime.now(tz=UTC).isoformat(),
    )
    retryable_id = store.insert_notification_outbox(
        alert_event_id=retryable.alert_event_id,
        channel="telegram",
        destination_hash=destination_hash("telegram", "chat-1:token"),
        created_at_utc=datetime.now(tz=UTC).isoformat(),
    )
    terminal_id = store.insert_notification_outbox(
        alert_event_id=terminal.alert_event_id,
        channel="discord",
        destination_hash=destination_hash("discord", "https://discord.com/api/webhooks/123/secret"),
        created_at_utc=datetime.now(tz=UTC).isoformat(),
    )
    store.complete_notification_outbox(
        outbox_id=retryable_id,
        status="failed_retryable",
        completed_at_utc=datetime.now(tz=UTC).isoformat(),
        retry_count=1,
        last_error_code="500",
        last_error_message="provider failed",
        provider_response={},
    )
    store.complete_notification_outbox(
        outbox_id=terminal_id,
        status="failed_terminal",
        completed_at_utc=datetime.now(tz=UTC).isoformat(),
        retry_count=0,
        last_error_code="404",
        last_error_message="invalid destination",
        provider_response={},
    )

    assert main(["notifications", "outbox", "list", "--status", "failed_retryable"]) == 0
    list_output = capsys.readouterr().out
    assert retryable_id in list_output
    assert terminal_id not in list_output

    assert main(["notifications", "outbox", "drain", "--dry-run"]) == 0
    dry_run_output = capsys.readouterr().out
    assert pending_id in dry_run_output
    assert retryable_id in dry_run_output
    assert terminal_id not in dry_run_output
    assert "secret" not in dry_run_output
    assert "No notification was sent" in dry_run_output


def test_outbox_drain_records_undeliverable_rows(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "notifications.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    store = SQLiteStore(db_path)
    existing_event = make_alert(alert_event_id="event-without-notifier")
    store.insert_alert_event(existing_event)
    missing_event_id = store.insert_notification_outbox(
        alert_event_id="missing-event",
        channel="telegram",
        destination_hash=destination_hash("telegram", "chat-1:token"),
        created_at_utc=datetime.now(tz=UTC).isoformat(),
    )
    no_notifier_id = store.insert_notification_outbox(
        alert_event_id=existing_event.alert_event_id,
        channel="discord",
        destination_hash=destination_hash("discord", "https://discord.com/api/webhooks/123/secret"),
        created_at_utc=datetime.now(tz=UTC).isoformat(),
    )

    assert main(["notifications", "outbox", "drain", "--max", "5"]) == 0
    output = capsys.readouterr().out
    assert "missing_alert_event" in output
    assert "notifier_unavailable" in output
    assert "secret" not in output

    rows = {row["id"]: row for row in store.list_notification_outbox()}
    assert rows[missing_event_id]["status"] == "failed_terminal"
    assert rows[missing_event_id]["last_error_code"] == "missing_alert_event"
    assert rows[missing_event_id]["retry_count"] == 1
    assert rows[no_notifier_id]["status"] == "failed_retryable"
    assert rows[no_notifier_id]["last_error_code"] == "notifier_unavailable"
    assert rows[no_notifier_id]["retry_count"] == 1


def test_outbox_drain_terminalizes_rows_at_retry_limit(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "notifications.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    store = SQLiteStore(db_path)
    event = make_alert(alert_event_id="retry-limit-event")
    store.insert_alert_event(event)
    outbox_id = store.insert_notification_outbox(
        alert_event_id=event.alert_event_id,
        channel="discord",
        destination_hash=destination_hash("discord", "https://discord.com/api/webhooks/123/secret"),
        created_at_utc=datetime.now(tz=UTC).isoformat(),
    )
    store.complete_notification_outbox(
        outbox_id=outbox_id,
        status="failed_retryable",
        completed_at_utc=datetime.now(tz=UTC).isoformat(),
        retry_count=3,
        last_error_code="notifier_unavailable",
        last_error_message="No configured notifier matches.",
        provider_response={},
    )

    assert main(["notifications", "outbox", "drain", "--max-retries", "3"]) == 0
    output = capsys.readouterr().out
    assert "outbox_retry_limit_exceeded" in output
    assert "secret" not in output

    rows = {row["id"]: row for row in store.list_notification_outbox()}
    assert rows[outbox_id]["status"] == "failed_terminal"
    assert rows[outbox_id]["last_error_code"] == "outbox_retry_limit_exceeded"
    assert rows[outbox_id]["retry_count"] == 3


def test_outbox_drain_requires_positive_max_and_respects_limit(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "notifications.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    store = SQLiteStore(db_path)
    first = make_alert(alert_event_id="first-event")
    second = make_alert(alert_event_id="second-event")
    for event in [first, second]:
        store.insert_alert_event(event)
        store.insert_notification_outbox(
            alert_event_id=event.alert_event_id,
            channel="telegram",
            destination_hash=destination_hash("telegram", "chat-1:token"),
            created_at_utc=datetime.now(tz=UTC).isoformat(),
        )

    assert main(["notifications", "outbox", "drain", "--max", "0", "--dry-run"]) == 2
    assert "must be positive" in capsys.readouterr().err
    assert main(["notifications", "outbox", "drain", "--max-retries", "0", "--dry-run"]) == 2
    assert "max-retries must be positive" in capsys.readouterr().err

    assert main(["notifications", "outbox", "drain", "--max", "1", "--dry-run"]) == 0
    payload = capsys.readouterr().out
    assert payload.count("alert_event_id") == 1


def test_previous_alert_policy_inputs_skip_current_saved_run(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "notifications.sqlite")
    _insert_research_run(store, "previous-run", "2026-01-01T00:00:00+00:00")
    _insert_research_run(store, "wrong-quote-run", "2026-01-01T00:04:00+00:00", quote="USDC")
    _insert_research_run(store, "current-run", "2026-01-01T00:05:00+00:00")
    store.insert_feature_snapshot(
        {
            "run_id": "previous-run",
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "interval": "15m",
            "data_timestamp_utc": "2026-01-01T00:00:00+00:00",
            "feature": {"ret_1h": 0.01},
            "component_scores": {"breakout": 70.0, "volume": 80.0},
            "penalties": {},
            "risk_flags": [],
            "score_explanation": {"score": 78.0, "rank": 12},
        }
    )
    store.insert_feature_snapshot(
        {
            "run_id": "wrong-quote-run",
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "interval": "15m",
            "data_timestamp_utc": "2026-01-01T00:04:00+00:00",
            "feature": {"ret_1h": 0.03},
            "component_scores": {"breakout": 99.0, "volume": 99.0},
            "penalties": {},
            "risk_flags": [],
            "score_explanation": {"score": 99.0, "rank": 1},
        }
    )
    store.insert_feature_snapshot(
        {
            "run_id": "current-run",
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "interval": "15m",
            "data_timestamp_utc": "2026-01-01T00:05:00+00:00",
            "feature": {"ret_1h": 0.02},
            "component_scores": {"breakout": 90.0, "volume": 90.0},
            "penalties": {},
            "risk_flags": [],
            "score_explanation": {"score": 90.0, "rank": 1},
        }
    )

    previous_scores, previous_ranks, previous_components = _previous_alert_policy_inputs(
        store,
        [make_candidate(source_run_id="current-run")],
        current_run_id="current-run",
        quote="USDT",
    )

    assert previous_scores == {"BTCUSDT": 78.0}
    assert previous_ranks == {"BTCUSDT": 12}
    assert previous_components == {"BTCUSDT": {"breakout": 70.0, "volume": 80.0}}


def _insert_research_run(
    store: SQLiteStore,
    run_id: str,
    created_at_utc: str,
    *,
    quote: str = "USDT",
) -> None:
    store.insert_research_run(
        {
            "run_id": run_id,
            "created_at_utc": created_at_utc,
            "commit_sha": "test",
            "config_hash": "hash",
            "exchange": "binance",
            "quote": quote,
            "interval": "15m",
            "data_window_start_utc": created_at_utc,
            "data_window_end_utc": created_at_utc,
            "mock_mode": True,
            "candidate_count": 1,
            "research_warning": "Research alert only. Not financial advice. No order was placed.",
        }
    )
