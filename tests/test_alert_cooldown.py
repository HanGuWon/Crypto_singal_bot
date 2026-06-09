from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conftest import make_alert
from crypto_signal_bot.alerts.cooldown import CooldownTracker


def test_cooldown_prevents_duplicate_symbol_event() -> None:
    tracker = CooldownTracker(cooldown_minutes=60)
    now = datetime.now(tz=UTC)
    event = make_alert()
    assert tracker.allow(event, now)
    assert not tracker.allow(event, now + timedelta(minutes=10))
    assert tracker.allow(event, now + timedelta(minutes=61))
