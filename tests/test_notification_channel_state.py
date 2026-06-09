from __future__ import annotations

from conftest import make_alert
from crypto_signal_bot.alerts.channel_state import SQLiteNotificationChannelStateStore
from crypto_signal_bot.alerts.dispatcher import NotificationDispatcher
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.notifications.base import NotificationResult
from crypto_signal_bot.notifications.destinations import destination_hash


class TerminalDiscordNotifier:
    channel = "discord"

    def __init__(self) -> None:
        self.send_count = 0

    def destination_key(self) -> str:
        return "https://discord.com/api/webhooks/1/broken"

    def send(self, event):  # type: ignore[no-untyped-def]
        self.send_count += 1
        return NotificationResult("discord", "failed", "discord_webhook", error_code="404")


class RateLimitedTelegramNotifier:
    channel = "telegram"

    def __init__(self) -> None:
        self.send_count = 0

    def destination_key(self) -> str:
        return "chat-1:token"

    def send(self, event):  # type: ignore[no-untyped-def]
        self.send_count += 1
        return NotificationResult(
            "telegram",
            "failed",
            "chat-1",
            error_code="429",
            provider_response={"parameters": {"retry_after": 60}},
        )


def test_terminal_destination_failure_quarantines_channel_across_dispatches(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "alerts.sqlite")
    channel_state = SQLiteNotificationChannelStateStore(store)
    notifier = TerminalDiscordNotifier()
    dispatcher = NotificationDispatcher(True, [notifier], channel_state_store=channel_state)

    first = dispatcher.dispatch([make_alert(alert_event_id="event-1")])
    second = dispatcher.dispatch([make_alert(alert_event_id="event-2")])

    assert first[0].status == "failed"
    assert first[0].error_code == "404"
    assert second[0].status == "suppressed_by_channel_state"
    assert second[0].error_code == "invalid_destination"
    assert notifier.send_count == 1

    state = store.get_notification_channel_state(
        "discord",
        destination_hash("discord", notifier.destination_key()),
    )
    assert state is not None
    assert state["status"] == "invalid_destination"
    assert bool(state["manual_reset_required"])


def test_temporary_429_channel_cooldown_suppresses_next_dispatch(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "alerts.sqlite")
    channel_state = SQLiteNotificationChannelStateStore(store)
    notifier = RateLimitedTelegramNotifier()
    dispatcher = NotificationDispatcher(True, [notifier], channel_state_store=channel_state)

    first = dispatcher.dispatch([make_alert(alert_event_id="event-1")])
    second = dispatcher.dispatch([make_alert(alert_event_id="event-2")])

    assert first[0].status == "failed"
    assert first[0].error_code == "429"
    assert second[0].status == "suppressed_by_channel_state"
    assert second[0].error_code == "channel_temporarily_rate_limited"
    assert notifier.send_count == 1
