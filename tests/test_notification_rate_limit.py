from __future__ import annotations

from datetime import UTC, datetime

from conftest import make_alert
from crypto_signal_bot.alerts.delivery_log import delivery_record, suppressed_delivery_record
from crypto_signal_bot.alerts.rate_limit import SQLiteNotificationRateLimiter
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.notifications.base import NotificationResult


def test_global_notification_limiter_suppresses_excess_events(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "alerts.sqlite")
    now = datetime.now(tz=UTC)
    events = [
        make_alert(symbol="BTCUSDT", alert_event_id="event-1"),
        make_alert(symbol="ETHUSDT", alert_event_id="event-2"),
    ]
    limiter = SQLiteNotificationRateLimiter(
        store,
        global_max_per_minute=1,
        per_symbol_max_per_hour=10,
    )

    allowed, suppressed = limiter.filter_events(events, now=now)

    assert [event.alert_event_id for event in allowed] == ["event-1"]
    assert len(suppressed) == 1
    assert suppressed[0].event.alert_event_id == "event-2"
    assert suppressed[0].reason == "global_max_per_minute"

    for event in events:
        store.insert_alert_event(event)
    store.insert_notification_delivery(suppressed_delivery_record(suppressed[0], attempted_at=now))

    with store.connect() as conn:
        row = conn.execute("SELECT status, error_code FROM notification_deliveries").fetchone()
    assert row["status"] == "suppressed_by_rate_limit"
    assert row["error_code"] == "global_max_per_minute"


def test_per_symbol_notification_limiter_uses_persisted_history(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "alerts.sqlite")
    now = datetime.now(tz=UTC)
    first = make_alert(alert_event_id="event-1")
    second = make_alert(alert_event_id="event-2")
    store.insert_alert_event(first)
    store.insert_notification_delivery(
        delivery_record(
            NotificationResult("telegram", "delivered", "chat-1"),
            first.alert_event_id,
            attempted_at=now,
        )
    )
    limiter = SQLiteNotificationRateLimiter(
        store,
        global_max_per_minute=10,
        per_symbol_max_per_hour=1,
    )

    allowed, suppressed = limiter.filter_events([second], now=now)

    assert allowed == []
    assert len(suppressed) == 1
    assert suppressed[0].reason == "per_symbol_max_per_hour"


def test_rate_limiter_prioritizes_warnings_before_watch_events(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "alerts.sqlite")
    watch = make_alert(alert_event_id="watch", event_type="SCORE_THRESHOLD_CROSSED", severity="WATCH")
    warning = make_alert(alert_event_id="warning", event_type="RISK_WARNING", severity="WARNING")
    limiter = SQLiteNotificationRateLimiter(
        store,
        global_max_per_minute=1,
        per_symbol_max_per_hour=10,
    )

    allowed, suppressed = limiter.filter_events([watch, warning])

    assert [event.alert_event_id for event in allowed] == ["warning"]
    assert [decision.event.alert_event_id for decision in suppressed] == ["watch"]
