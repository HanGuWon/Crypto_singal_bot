from __future__ import annotations

from datetime import UTC, datetime

from conftest import make_alert
from crypto_signal_bot.cli import main
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.notifications.destinations import destination_hash


def test_notifications_status_outputs_counts(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "notifications.sqlite"))

    assert main(["notifications", "status"]) == 0

    output = capsys.readouterr().out
    assert "outbox" in output
    assert "channel_state" in output


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
