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


def test_discord_payload_blocks_mentions_by_default() -> None:
    payload = format_discord_payload(make_alert())
    assert payload["allowed_mentions"] == {"parse": []}
    assert any(
        field["name"] == "Data freshness"
        for field in payload["embeds"][0]["fields"]
    )
    combined = str(payload).lower()
    assert all(word not in combined for word in FORBIDDEN_ALERT_WORDS)
