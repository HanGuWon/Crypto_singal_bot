from __future__ import annotations

from conftest import make_alert
from crypto_signal_bot.alerts.dispatcher import NotificationDispatcher


class FailingNotifier:
    channel = "failing"

    def send(self, event):  # type: ignore[no-untyped-def]
        raise RuntimeError("adapter failed")


def test_notification_failure_does_not_crash_dispatcher() -> None:
    results = NotificationDispatcher(True, [FailingNotifier()]).dispatch([make_alert()])
    assert results[0].status == "failed"
    assert "adapter failed" in (results[0].error_message or "")


class SecretFailingNotifier:
    channel = "telegram"

    def send(self, event):  # type: ignore[no-untyped-def]
        raise RuntimeError("failed https://api.telegram.org/bot123:ABC/sendMessage")


def test_notification_exception_result_is_redacted() -> None:
    results = NotificationDispatcher(True, [SecretFailingNotifier()]).dispatch([make_alert()])
    assert "123:ABC" not in (results[0].error_message or "")
    assert "123:ABC" not in str(results[0].to_safe_dict())
