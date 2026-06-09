from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.data.store import SQLiteStore


@dataclass(frozen=True)
class NotificationRateLimitDecision:
    event: AlertEvent
    allowed: bool
    reason: str | None = None


class SQLiteNotificationRateLimiter:
    """Persistent event-level limiter for outbound research notifications."""

    def __init__(
        self,
        store: SQLiteStore,
        *,
        global_max_per_minute: int,
        per_symbol_max_per_hour: int,
        safety_global_max_per_minute: int = 5,
        safety_per_symbol_max_per_hour: int = 3,
    ) -> None:
        self.store = store
        self.global_max_per_minute = global_max_per_minute
        self.per_symbol_max_per_hour = per_symbol_max_per_hour
        self.safety_global_max_per_minute = safety_global_max_per_minute
        self.safety_per_symbol_max_per_hour = safety_per_symbol_max_per_hour

    def filter_events(
        self,
        events: list[AlertEvent],
        *,
        now: datetime | None = None,
    ) -> tuple[list[AlertEvent], list[NotificationRateLimitDecision]]:
        if not events:
            return [], []

        now_utc = now or datetime.now(tz=UTC)
        minute_since = (now_utc - timedelta(minutes=1)).isoformat()
        hour_since = (now_utc - timedelta(hours=1)).isoformat()
        global_used = {
            "watch": self.store.count_recent_notification_events_by_priority(minute_since, "watch"),
            "safety": self.store.count_recent_notification_events_by_priority(minute_since, "safety"),
        }
        symbol_used: dict[tuple[str, str, str, str], int] = {}
        allowed: list[AlertEvent] = []
        suppressed: list[NotificationRateLimitDecision] = []

        for event in sorted(enumerate(events), key=_priority_sort_key):
            alert = event[1]
            priority = _priority_class(alert)
            symbol_key = (alert.exchange, alert.symbol, alert.interval, priority)
            if symbol_key not in symbol_used:
                symbol_used[symbol_key] = self.store.count_recent_symbol_notification_events_by_priority(
                    alert.exchange,
                    alert.symbol,
                    alert.interval,
                    hour_since,
                    priority,
                )
            global_limit = (
                self.safety_global_max_per_minute
                if priority == "safety"
                else self.global_max_per_minute
            )
            symbol_limit = (
                self.safety_per_symbol_max_per_hour
                if priority == "safety"
                else self.per_symbol_max_per_hour
            )

            if global_limit <= 0 or global_used[priority] >= global_limit:
                suppressed.append(
                    NotificationRateLimitDecision(alert, False, f"{priority}_global_max_per_minute")
                )
                continue
            if symbol_limit <= 0 or symbol_used[symbol_key] >= symbol_limit:
                suppressed.append(
                    NotificationRateLimitDecision(alert, False, f"{priority}_per_symbol_max_per_hour")
                )
                continue

            allowed.append(alert)
            global_used[priority] += 1
            symbol_used[symbol_key] += 1

        return allowed, suppressed


def _priority_sort_key(indexed_event: tuple[int, AlertEvent]) -> tuple[int, int, int]:
    index, event = indexed_event
    severity_priority = {"CRITICAL": 0, "WARNING": 1, "WATCH": 2, "INFO": 3}
    event_priority = {
        "SYSTEM_ERROR": 0,
        "DATA_QUALITY_WARNING": 1,
        "RISK_WARNING": 1,
        "INVALIDATION": 1,
        "SCORE_THRESHOLD_CROSSED": 2,
        "TOP_N_ENTRY": 3,
        "SCORE_ACCELERATION": 3,
        "BREAKOUT_WATCH": 3,
    }
    return (
        severity_priority.get(event.severity, 4),
        event_priority.get(event.event_type, 4),
        index,
    )


def _priority_class(event: AlertEvent) -> str:
    if event.severity in {"WARNING", "CRITICAL"}:
        return "safety"
    if event.event_type in {"RISK_WARNING", "INVALIDATION", "DATA_QUALITY_WARNING", "SYSTEM_ERROR"}:
        return "safety"
    return "watch"
