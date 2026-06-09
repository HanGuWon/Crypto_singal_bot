from __future__ import annotations

from datetime import UTC, datetime

from conftest import make_alert
from crypto_signal_bot.alerts.dispatcher import NotificationDispatcher
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.notifications.base import NotificationResult
from crypto_signal_bot.notifications.destinations import destination_hash


class DeliveredNotifier:
    channel = "telegram"

    def destination_key(self) -> str:
        return "chat-1:token"

    def send(self, event):  # type: ignore[no-untyped-def]
        return NotificationResult("telegram", "delivered", "chat-1", provider_response={"ok": True})


class TerminalFailureNotifier:
    channel = "discord"

    def destination_key(self) -> str:
        return "https://discord.com/api/webhooks/1/broken"

    def send(self, event):  # type: ignore[no-untyped-def]
        return NotificationResult("discord", "failed", "discord_webhook", error_code="404")


def test_dispatcher_claims_and_completes_outbox_rows(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "alerts.sqlite")
    event = make_alert(alert_event_id="event-1")
    notifier = DeliveredNotifier()
    store.insert_alert_event(event)
    store.insert_notification_outbox(
        alert_event_id=event.alert_event_id,
        channel=notifier.channel,
        destination_hash=destination_hash(notifier.channel, notifier.destination_key()),
        created_at_utc=datetime.now(tz=UTC).isoformat(),
    )

    pairs = NotificationDispatcher(True, [notifier], outbox_store=store).dispatch_with_events([event])

    assert pairs[0][1].status == "delivered"
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM notification_outbox").fetchone()
    assert row["status"] == "delivered"
    assert row["claimed_at_utc"] is not None
    assert row["completed_at_utc"] is not None


def test_terminal_failure_completes_outbox_as_failed_terminal(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "alerts.sqlite")
    event = make_alert(alert_event_id="event-1")
    notifier = TerminalFailureNotifier()
    store.insert_alert_event(event)
    store.insert_notification_outbox(
        alert_event_id=event.alert_event_id,
        channel=notifier.channel,
        destination_hash=destination_hash(notifier.channel, notifier.destination_key()),
        created_at_utc=datetime.now(tz=UTC).isoformat(),
    )

    NotificationDispatcher(True, [notifier], outbox_store=store).dispatch_with_events([event])

    with store.connect() as conn:
        row = conn.execute("SELECT status, last_error_code FROM notification_outbox").fetchone()
    assert row["status"] == "failed_terminal"
    assert row["last_error_code"] == "404"
