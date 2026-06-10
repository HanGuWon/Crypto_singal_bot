from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_signal_bot.alerts.channel_state import SQLiteNotificationChannelStateStore, suppression_result
from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.logging_config import redact_secrets
from crypto_signal_bot.notifications.base import NotificationResult, Notifier
from crypto_signal_bot.notifications.destinations import destination_hash, notifier_destination
from crypto_signal_bot.notifications.noop import NoopNotifier

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimedOutboxRow:
    id: str
    retry_count: int


@dataclass
class NotificationDispatcher:
    notifications_enabled: bool = False
    notifiers: list[Notifier] = field(default_factory=lambda: [NoopNotifier()])
    channel_state_store: SQLiteNotificationChannelStateStore | None = None
    outbox_store: SQLiteStore | None = None

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
                channel = getattr(notifier, "channel", "unknown")
                destination = notifier_destination(notifier)
                outbox_row = self._claim_outbox(event, channel, destination)
                try:
                    suppression = (
                        self.channel_state_store.suppression_for(channel, destination)
                        if self.channel_state_store is not None
                        else None
                    )
                    if suppression is not None:
                        result = suppression_result(channel, suppression)
                    else:
                        result = notifier.send(event)
                        if self.channel_state_store is not None:
                            self.channel_state_store.record_result(channel, destination, result)
                    self._complete_outbox(outbox_row, result)
                    results.append((event, result))
                except Exception as exc:  # Notification failures must remain isolated.
                    safe_error = redact_secrets(exc)
                    LOGGER.warning("Notification adapter failed: %s", safe_error)
                    result = NotificationResult(
                        channel,
                        "failed",
                        "unknown",
                        error_message=safe_error,
                    )
                    self._complete_outbox(outbox_row, result)
                    results.append((event, result))
        return results

    def _claim_outbox(self, event: AlertEvent, channel: str, destination: str) -> ClaimedOutboxRow | None:
        if self.outbox_store is None:
            return None
        claimed = self.outbox_store.claim_notification_outbox(
            alert_event_id=event.alert_event_id,
            channel=channel,
            destination_hash=destination_hash(channel, destination),
            claimed_at_utc=datetime.now(tz=UTC).isoformat(),
        )
        if claimed is None:
            return None
        outbox_id, retry_count = claimed
        return ClaimedOutboxRow(id=outbox_id, retry_count=retry_count)

    def _complete_outbox(self, outbox_row: ClaimedOutboxRow | None, result: NotificationResult) -> None:
        if self.outbox_store is None or outbox_row is None:
            return
        safe_result = result.to_safe_dict()
        retry_count = outbox_row.retry_count
        if _outbox_status(result) in {"failed_retryable", "failed_terminal"}:
            retry_count += 1
        self.outbox_store.complete_notification_outbox(
            outbox_id=outbox_row.id,
            status=_outbox_status(result),
            completed_at_utc=datetime.now(tz=UTC).isoformat(),
            retry_count=retry_count,
            last_error_code=result.error_code,
            last_error_message=(
                str(safe_result["error_message"]) if safe_result["error_message"] else None
            ),
            provider_response=safe_result["provider_response"],
        )


def _outbox_status(result: NotificationResult) -> str:
    if result.status == "delivered":
        return "delivered"
    if result.status.startswith("suppressed"):
        return "suppressed"
    if result.error_code in {"401", "403", "404"}:
        return "failed_terminal"
    return "failed_retryable"
