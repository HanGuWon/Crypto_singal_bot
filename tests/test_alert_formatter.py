from __future__ import annotations

from conftest import make_alert
from crypto_signal_bot.alerts.formatter import (
    FORBIDDEN_ALERT_WORDS,
    RESEARCH_WARNING,
    format_discord_payload,
    format_telegram_event,
)


def test_telegram_formatter_preserves_research_warning_after_truncation() -> None:
    event = make_alert(drivers=["driver_" + str(i) for i in range(200)])
    text = format_telegram_event(event, max_length=300)
    assert len(text) <= 300
    assert RESEARCH_WARNING in text
    assert "Data freshness:" in text
    assert "Alert id:" in text


def test_telegram_formatter_includes_audit_ids() -> None:
    event = make_alert()
    text = format_telegram_event(event)
    assert event.alert_event_id in text
    assert event.source_run_id in text


def test_telegram_formatter_surfaces_exit_guard_manual_approval_id() -> None:
    event = make_alert(
        event_type="PROTECTIVE_EXIT_WATCH",
        drivers=[
            "driver_a",
            "driver_b",
            "driver_c",
            "driver_d",
            "driver_e",
            "manual_approval_request:exit-approval-123",
        ],
    )

    text = format_telegram_event(event, max_length=500)

    assert "Manual approval request id: exit-approval-123" in text


def test_discord_payload_blocks_mentions_by_default() -> None:
    event = make_alert()
    payload = format_discord_payload(event)
    assert payload["allowed_mentions"] == {"parse": []}
    assert any(
        field["name"] == "Data freshness"
        for field in payload["embeds"][0]["fields"]
    )
    assert any(
        field["name"] == "Alert event id" and field["value"] == event.alert_event_id
        for field in payload["embeds"][0]["fields"]
    )
    assert any(
        field["name"] == "Source run id" and field["value"] == event.source_run_id
        for field in payload["embeds"][0]["fields"]
    )
    combined = str(payload).lower()
    assert all(word not in combined for word in FORBIDDEN_ALERT_WORDS)


def test_discord_payload_surfaces_exit_guard_manual_approval_id() -> None:
    event = make_alert(
        event_type="PROTECTIVE_EXIT_WATCH",
        drivers=[
            "driver_a",
            "driver_b",
            "driver_c",
            "driver_d",
            "driver_e",
            "manual_approval_request:exit-approval-123",
        ],
    )

    payload = format_discord_payload(event)

    assert any(
        field["name"] == "Manual approval request id" and field["value"] == "exit-approval-123"
        for field in payload["embeds"][0]["fields"]
    )
