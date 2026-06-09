from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from crypto_signal_bot.notifications.base import NotificationResult


def delivery_record(result: NotificationResult, alert_event_id: str) -> dict[str, object]:
    return {
        "id": f"{alert_event_id}:{result.channel}:{datetime.now(tz=UTC).timestamp()}",
        "alert_event_id": alert_event_id,
        "channel": result.channel,
        "destination": result.destination,
        "status": result.status,
        "attempted_at_utc": datetime.now(tz=UTC).isoformat(),
        "delivered_at_utc": datetime.now(tz=UTC).isoformat() if result.status == "delivered" else None,
        **asdict(result),
    }
