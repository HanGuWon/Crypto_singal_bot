from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.notifications.base import NotificationResult
from crypto_signal_bot.notifications.destinations import destination_hash


@dataclass(frozen=True)
class ChannelSuppression:
    status: str
    reason: str
    retry_after_until_utc: str | None = None


class SQLiteNotificationChannelStateStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def suppression_for(
        self,
        channel: str,
        destination: str,
        *,
        now: datetime | None = None,
    ) -> ChannelSuppression | None:
        now_utc = now or datetime.now(tz=UTC)
        state = self.store.get_notification_channel_state(
            channel,
            destination_hash(channel, destination),
        )
        if state is None:
            return None
        status = str(state["status"])
        retry_after = state["retry_after_until_utc"]
        if status == "temporarily_rate_limited" and retry_after:
            retry_after_utc = datetime.fromisoformat(str(retry_after))
            if retry_after_utc > now_utc:
                return ChannelSuppression(status, "channel_temporarily_rate_limited", str(retry_after))
            return None
        if bool(state["manual_reset_required"]):
            return ChannelSuppression(status, status, None)
        return None

    def record_result(
        self,
        channel: str,
        destination: str,
        result: NotificationResult,
        *,
        now: datetime | None = None,
    ) -> None:
        now_utc = now or datetime.now(tz=UTC)
        destination_digest = destination_hash(channel, destination)
        if result.status == "delivered":
            self.store.upsert_notification_channel_state(
                channel=channel,
                destination_hash=destination_digest,
                status="healthy",
                last_error_code=None,
                last_error_at_utc=None,
                retry_after_until_utc=None,
                manual_reset_required=False,
            )
            return

        if result.error_code in {"401", "403"}:
            self.store.upsert_notification_channel_state(
                channel=channel,
                destination_hash=destination_digest,
                status="invalid_credentials",
                last_error_code=result.error_code,
                last_error_at_utc=now_utc.isoformat(),
                retry_after_until_utc=None,
                manual_reset_required=True,
            )
            return
        if channel == "discord" and result.error_code == "404":
            self.store.upsert_notification_channel_state(
                channel=channel,
                destination_hash=destination_digest,
                status="invalid_destination",
                last_error_code=result.error_code,
                last_error_at_utc=now_utc.isoformat(),
                retry_after_until_utc=None,
                manual_reset_required=True,
            )
            return
        if result.error_code == "429":
            retry_after_seconds = _retry_after_seconds(result.provider_response) or 60.0
            self.store.upsert_notification_channel_state(
                channel=channel,
                destination_hash=destination_digest,
                status="temporarily_rate_limited",
                last_error_code=result.error_code,
                last_error_at_utc=now_utc.isoformat(),
                retry_after_until_utc=(now_utc + timedelta(seconds=retry_after_seconds)).isoformat(),
                manual_reset_required=False,
            )


def suppression_result(
    channel: str,
    suppression: ChannelSuppression,
) -> NotificationResult:
    return NotificationResult(
        channel,
        "suppressed_by_channel_state",
        "suppressed",
        error_code=suppression.reason,
        error_message=f"Suppressed by notification channel state: {suppression.status}.",
    )


def _retry_after_seconds(provider_response: dict | None) -> float | None:
    if not provider_response:
        return None
    retry_after = provider_response.get("retry_after")
    if retry_after is None:
        parameters = provider_response.get("parameters")
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
    try:
        return float(retry_after) if retry_after is not None else None
    except (TypeError, ValueError):
        return None
