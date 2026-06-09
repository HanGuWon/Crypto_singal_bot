from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from crypto_signal_bot.alerts.rate_limit import NotificationRateLimitDecision
from crypto_signal_bot.notifications.base import NotificationResult


def delivery_record(
    result: NotificationResult,
    alert_event_id: str,
    *,
    attempted_at: datetime | None = None,
) -> dict[str, object]:
    safe_result = result.to_safe_dict()
    attempted_at = attempted_at or datetime.now(tz=UTC)
    return {
        "id": str(uuid4()),
        "alert_event_id": alert_event_id,
        "channel": safe_result["channel"],
        "destination": safe_result["destination"],
        "status": safe_result["status"],
        "attempted_at_utc": attempted_at.isoformat(),
        "delivered_at_utc": attempted_at.isoformat() if result.status == "delivered" else None,
        "error_code": safe_result["error_code"],
        "error_message": safe_result["error_message"],
        "retry_count": safe_result["retry_count"],
        "provider_response": safe_result["provider_response"],
    }


def suppressed_delivery_record(
    decision: NotificationRateLimitDecision,
    *,
    attempted_at: datetime | None = None,
) -> dict[str, object]:
    reason = decision.reason or "rate_limited"
    return delivery_record(
        NotificationResult(
            "rate_limiter",
            "suppressed_by_rate_limit",
            "suppressed",
            error_code=reason,
            error_message=f"Suppressed by notification rate limiter: {reason}.",
        ),
        decision.event.alert_event_id,
        attempted_at=attempted_at,
    )
