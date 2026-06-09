from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from crypto_signal_bot.alerts.schemas import AlertEvent


@dataclass(frozen=True)
class NotificationResult:
    channel: str
    status: str
    destination: str
    error_code: str | None = None
    error_message: str | None = None
    provider_response: dict | None = None
    retry_count: int = 0


class Notifier(Protocol):
    channel: str

    def send(self, event: AlertEvent) -> NotificationResult:
        ...
