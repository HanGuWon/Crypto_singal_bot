from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class AlertEvent:
    alert_event_id: str
    created_at_utc: datetime
    exchange: str
    symbol: str
    interval: str
    event_type: str
    severity: str
    score: float
    previous_score: float | None
    confidence: str
    current_price: float | None
    rank: int | None
    drivers: list[str]
    risk_flags: list[str]
    invalidation_condition: str
    data_timestamp_utc: str
    dedupe_key: str
    source_run_id: str
    data_freshness_seconds: float | None = None
    notification_status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_event_id": self.alert_event_id,
            "created_at_utc": self.created_at_utc.astimezone(UTC).isoformat(),
            "exchange": self.exchange,
            "symbol": self.symbol,
            "interval": self.interval,
            "event_type": self.event_type,
            "severity": self.severity,
            "score": self.score,
            "previous_score": self.previous_score,
            "confidence": self.confidence,
            "current_price": self.current_price,
            "rank": self.rank,
            "drivers": self.drivers,
            "risk_flags": self.risk_flags,
            "invalidation_condition": self.invalidation_condition,
            "data_timestamp_utc": self.data_timestamp_utc,
            "data_freshness_seconds": self.data_freshness_seconds,
            "dedupe_key": self.dedupe_key,
            "source_run_id": self.source_run_id,
            "notification_status": self.notification_status,
        }
