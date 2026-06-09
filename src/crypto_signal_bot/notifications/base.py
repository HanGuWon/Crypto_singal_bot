from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.logging_config import redact_data, redact_secrets


@dataclass(frozen=True)
class NotificationResult:
    channel: str
    status: str
    destination: str
    error_code: str | None = None
    error_message: str | None = None
    provider_response: dict | None = None
    retry_count: int = 0

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "status": self.status,
            "destination": redact_secrets(self.destination),
            "error_code": self.error_code,
            "error_message": redact_secrets(self.error_message or "") if self.error_message else None,
            "provider_response": redact_data(self.provider_response),
            "retry_count": self.retry_count,
        }


class Notifier(Protocol):
    channel: str

    def send(self, event: AlertEvent) -> NotificationResult:
        ...
