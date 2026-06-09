from __future__ import annotations

import logging
from dataclasses import dataclass, field

from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.logging_config import redact_secrets
from crypto_signal_bot.notifications.base import NotificationResult, Notifier
from crypto_signal_bot.notifications.noop import NoopNotifier

LOGGER = logging.getLogger(__name__)


@dataclass
class NotificationDispatcher:
    notifications_enabled: bool = False
    notifiers: list[Notifier] = field(default_factory=lambda: [NoopNotifier()])

    def dispatch(self, events: list[AlertEvent]) -> list[NotificationResult]:
        return [result for _, result in self.dispatch_with_events(events)]

    def dispatch_with_events(self, events: list[AlertEvent]) -> list[tuple[AlertEvent, NotificationResult]]:
        if not events:
            return []
        if not self.notifications_enabled:
            return [
                (
                    event,
                    NotificationResult(
                        "noop",
                        "skipped",
                        "disabled",
                        error_message="Notifications disabled.",
                    ),
                )
                for event in events
            ]
        results: list[tuple[AlertEvent, NotificationResult]] = []
        for event in events:
            for notifier in self.notifiers:
                try:
                    results.append((event, notifier.send(event)))
                except Exception as exc:  # Notification failures must remain isolated.
                    safe_error = redact_secrets(exc)
                    LOGGER.warning("Notification adapter failed: %s", safe_error)
                    results.append(
                        (
                            event,
                            NotificationResult(
                                getattr(notifier, "channel", "unknown"),
                                "failed",
                                "unknown",
                                error_message=safe_error,
                            ),
                        )
                    )
        return results
