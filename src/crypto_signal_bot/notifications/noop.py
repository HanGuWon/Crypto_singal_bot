from __future__ import annotations

import logging

from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.notifications.base import NotificationResult

LOGGER = logging.getLogger(__name__)


class NoopNotifier:
    channel = "noop"

    def destination_key(self) -> str:
        return "noop"

    def send(self, event: AlertEvent) -> NotificationResult:
        LOGGER.info("Notification skipped or simulated for %s %s", event.exchange, event.symbol)
        return NotificationResult(channel=self.channel, status="skipped", destination="noop")
