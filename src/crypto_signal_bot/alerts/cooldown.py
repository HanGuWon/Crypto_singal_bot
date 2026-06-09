from __future__ import annotations

from datetime import datetime, timedelta

from crypto_signal_bot.alerts.schemas import AlertEvent


class CooldownTracker:
    def __init__(self, cooldown_minutes: int = 60) -> None:
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self._last_sent: dict[tuple[str, str, str, str], datetime] = {}

    def allow(self, event: AlertEvent, now: datetime) -> bool:
        key = (event.exchange, event.symbol, event.interval, event.event_type)
        last = self._last_sent.get(key)
        if last is not None and now - last < self.cooldown:
            return False
        self._last_sent[key] = now
        return True
