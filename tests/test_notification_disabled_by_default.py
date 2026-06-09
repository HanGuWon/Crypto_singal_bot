from __future__ import annotations

from conftest import make_alert
from crypto_signal_bot.alerts.dispatcher import NotificationDispatcher
from crypto_signal_bot.config import Settings


def test_notifications_disabled_by_default() -> None:
    settings = Settings()
    assert not settings.notifications_enabled
    results = NotificationDispatcher(settings.notifications_enabled).dispatch([make_alert()])
    assert results[0].status == "skipped"
