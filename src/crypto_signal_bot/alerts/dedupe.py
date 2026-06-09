from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.signals.schemas import SignalCandidate


def make_dedupe_key(candidate: SignalCandidate, event_type: str) -> str:
    score_bucket = int(candidate.score // 5) * 5
    driver_text = "|".join(sorted(candidate.drivers[:5]))
    driver_hash = hashlib.sha256(driver_text.encode("utf-8")).hexdigest()[:12]
    return (
        f"{candidate.exchange}:{candidate.symbol}:{candidate.interval}:"
        f"{event_type}:{score_bucket}:{driver_hash}"
    )


class DedupeCache:
    def __init__(self, ttl_minutes: int = 60) -> None:
        self.ttl = timedelta(minutes=ttl_minutes)
        self._seen: dict[str, datetime] = {}

    def should_send(self, event: AlertEvent, now: datetime) -> bool:
        last = self._seen.get(event.dedupe_key)
        if last is not None and now - last < self.ttl:
            return False
        self._seen[event.dedupe_key] = now
        return True
