from __future__ import annotations

import json
from datetime import UTC, datetime

from conftest import make_alert
from crypto_signal_bot.alerts.formatter import RESEARCH_WARNING, format_telegram_event
from crypto_signal_bot.alerts.rate_limit import SQLiteNotificationRateLimiter
from crypto_signal_bot.alerts.system_events import build_system_error_event
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.exchanges.base import ExchangeRateLimitError


def test_system_error_event_redacts_secrets_and_is_not_a_trading_signal() -> None:
    event = build_system_error_event(
        component="collector",
        operation="binance_klines",
        error=RuntimeError(
            "failed https://discord.com/api/webhooks/123/secret "
            "and https://api.telegram.org/bot123:ABC/sendMessage"
        ),
        exchange="binance",
        symbol="BTCUSDT",
        interval="5m",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    payload = json.dumps(event.to_dict())

    assert event.event_type == "SYSTEM_ERROR"
    assert event.severity == "CRITICAL"
    assert event.score == 0.0
    assert event.confidence == "system"
    assert "not_trading_signal" in event.risk_flags
    assert "Not a trading signal" in event.invalidation_condition
    assert "123:ABC" not in payload
    assert "secret" not in payload


def test_system_error_event_can_be_persisted_formatted_and_prioritized(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "alerts.sqlite")
    system_event = build_system_error_event(
        component="upbit_client",
        operation="market_universe",
        error=ExchangeRateLimitError("HTTP 429 retry window"),
        error_code="429",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.insert_alert_event(system_event)

    fetched = store.fetch_alert_event(system_event.alert_event_id)
    text = format_telegram_event(system_event)
    limiter = SQLiteNotificationRateLimiter(
        store,
        global_max_per_minute=0,
        per_symbol_max_per_hour=1,
        safety_global_max_per_minute=1,
        safety_per_symbol_max_per_hour=1,
    )
    allowed, suppressed = limiter.filter_events([make_alert(), system_event])

    assert fetched is not None
    assert fetched.event_type == "SYSTEM_ERROR"
    assert RESEARCH_WARNING in text
    assert "rate_limited" in system_event.risk_flags
    assert [event.event_type for event in allowed] == ["SYSTEM_ERROR"]
    assert suppressed[0].reason == "watch_global_max_per_minute"
