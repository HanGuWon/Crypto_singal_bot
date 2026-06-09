from __future__ import annotations

import json

from conftest import make_alert
from crypto_signal_bot.alerts.delivery_log import delivery_record
from crypto_signal_bot.alerts.dispatcher import NotificationDispatcher
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.notifications.base import NotificationResult


class DeliveredNotifier:
    channel = "telegram"

    def send(self, event):  # type: ignore[no-untyped-def]
        return NotificationResult("telegram", "delivered", "chat-1", provider_response={"ok": True})


class FailedNotifier:
    channel = "discord"

    def send(self, event):  # type: ignore[no-untyped-def]
        return NotificationResult(
            "discord",
            "failed",
            "https://discord.com/api/webhooks/123/secret",
            error_message="failed https://discord.com/api/webhooks/123/secret",
            provider_response={"url": "https://discord.com/api/webhooks/123/secret"},
        )


def test_dispatcher_delivery_results_can_be_audited_in_sqlite(tmp_path) -> None:
    event = make_alert()
    store = SQLiteStore(tmp_path / "alerts.sqlite")
    pairs = NotificationDispatcher(True, [DeliveredNotifier(), FailedNotifier()]).dispatch_with_events([event])

    store.insert_alert_event(event)
    for pair_event, result in pairs:
        store.insert_notification_delivery(delivery_record(result, pair_event.alert_event_id))

    with store.connect() as conn:
        alert_rows = conn.execute("SELECT * FROM alert_events").fetchall()
        delivery_rows = conn.execute("SELECT * FROM notification_deliveries ORDER BY channel").fetchall()

    assert len(alert_rows) == 1
    assert len(delivery_rows) == 2
    assert {row["status"] for row in delivery_rows} == {"delivered", "failed"}
    assert "secret" not in delivery_rows[0]["destination"]
    assert "secret" not in delivery_rows[1]["destination"]
    provider_payloads = [json.loads(row["provider_response_json"]) for row in delivery_rows]
    assert "secret" not in str(provider_payloads)
