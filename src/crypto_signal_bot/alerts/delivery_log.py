from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from crypto_signal_bot.notifications.base import NotificationResult


def delivery_record(result: NotificationResult, alert_event_id: str) -> dict[str, object]:
    safe_result = result.to_safe_dict()
    attempted_at = datetime.now(tz=UTC)
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
