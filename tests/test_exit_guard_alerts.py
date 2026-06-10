from __future__ import annotations

from datetime import UTC, datetime

from crypto_signal_bot.alerts.dispatcher import NotificationDispatcher
from crypto_signal_bot.alerts.formatter import EXIT_GUARD_WARNING, FORBIDDEN_ALERT_WORDS, format_discord_payload
from crypto_signal_bot.data.models import OrderBook, PriceLevel
from crypto_signal_bot.exit_guard.alerts import build_protective_exit_alert_event, make_protective_exit_dedupe_key
from crypto_signal_bot.exit_guard.models import (
    ProtectiveExitSignal,
    RiskReducingOrderIntent,
    assess_orderbook_slippage,
)


def test_protective_exit_blocked_preflight_builds_discord_safe_alert_event() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    signal = ProtectiveExitSignal(
        signal_id="exit-signal-1",
        created_at_utc=now,
        exchange="binance_usdm_futures",
        symbol="BTCUSDT",
        interval="5m",
        state="WATCHING",
        exit_score=72.4,
        drivers=["ema20_lost", "stochastic_cross_down"],
    )
    intent = RiskReducingOrderIntent(
        exchange="binance_usdm_futures",
        symbol="BTCUSDT",
        action="close_long",
        side="SELL",
        quantity=3.0,
        position_mode="one_way",
        position_side="BOTH",
        reduce_only=True,
    )
    slippage = assess_orderbook_slippage(
        intent,
        OrderBook(
            exchange="binance",
            symbol="BTCUSDT",
            event_time_utc=now,
            bids=[PriceLevel(100.0, 1.0), PriceLevel(94.0, 1.0)],
            asks=[PriceLevel(100.2, 3.0)],
        ),
        observed_at_utc=now,
        max_slippage_pct=1.0,
    )

    event = build_protective_exit_alert_event(signal, intent=intent, slippage=slippage, now=now)
    payload = format_discord_payload(event)

    assert event.event_type == "PROTECTIVE_EXIT_BLOCKED"
    assert event.severity == "WARNING"
    assert event.score == 72.4
    assert event.confidence == "research_only"
    assert event.source_run_id == "exit-signal-1"
    assert event.dedupe_key.startswith("binance_usdm_futures:BTCUSDT:5m:PROTECTIVE_EXIT_BLOCKED:70:")
    assert "orderbook_depth_exhausted" in event.risk_flags
    assert "excessive_slippage" in event.risk_flags
    assert "dry_run_only" in event.drivers
    assert payload["content"] == EXIT_GUARD_WARNING
    assert payload["allowed_mentions"] == {"parse": []}
    assert any(
        field["name"] == "Alert event id" and field["value"] == event.alert_event_id
        for field in payload["embeds"][0]["fields"]
    )
    assert any(
        field["name"] == "Source run id" and field["value"] == "exit-signal-1"
        for field in payload["embeds"][0]["fields"]
    )
    assert all(word not in str(payload).lower() for word in FORBIDDEN_ALERT_WORDS)


def test_protective_exit_alert_dispatch_is_skipped_when_notifications_disabled() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    signal = ProtectiveExitSignal(
        signal_id="exit-signal-2",
        created_at_utc=now,
        exchange="upbit_spot",
        symbol="KRW-BTC",
        interval="5m",
        state="WATCHING",
        exit_score=25.0,
    )
    event = build_protective_exit_alert_event(signal, now=now)

    results = NotificationDispatcher(notifications_enabled=False).dispatch([event])

    assert event.event_type == "PROTECTIVE_EXIT_WATCH"
    assert results[0].status == "skipped"
    assert results[0].error_message == "Notifications disabled."


def test_protective_exit_dedupe_key_reflects_full_driver_material() -> None:
    base = make_protective_exit_dedupe_key(
        exchange="binance_usdm_futures",
        symbol="BTCUSDT",
        interval="5m",
        event_type="PROTECTIVE_EXIT_WATCH",
        score=35.0,
        drivers=["dry_run_only", "manual_approval_required"],
        risk_flags=[],
    )
    with_approval = make_protective_exit_dedupe_key(
        exchange="binance_usdm_futures",
        symbol="BTCUSDT",
        interval="5m",
        event_type="PROTECTIVE_EXIT_WATCH",
        score=35.0,
        drivers=[
            "dry_run_only",
            "manual_approval_required",
            "manual_approval_request:exit-approval-1",
        ],
        risk_flags=[],
    )

    assert base != with_approval
