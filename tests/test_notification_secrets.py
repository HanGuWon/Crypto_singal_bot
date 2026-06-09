from __future__ import annotations

from crypto_signal_bot.logging_config import redact_secrets
from crypto_signal_bot.notifications.base import NotificationResult


def test_redacts_telegram_and_discord_secrets() -> None:
    text = (
        "telegram_bot_token=secret-token "
        "TELEGRAM_BOT_TOKEN=secret-token "
        "Authorization: Bearer secret-token "
        "https://api.telegram.org/botsecret-token/sendMessage "
        "https://discord.com/api/webhooks/123/secret"
    )
    redacted = redact_secrets(text)
    assert "secret-token" not in redacted
    assert "/123/secret" not in redacted
    assert "[REDACTED]" in redacted


def test_notification_result_safe_dict_redacts_provider_response() -> None:
    result = NotificationResult(
        channel="discord",
        status="failed",
        destination="https://discord.com/api/webhooks/123/secret",
        error_message="failed https://discord.com/api/webhooks/123/secret",
        provider_response={"url": "https://api.telegram.org/botsecret-token/sendMessage"},
    )
    safe = result.to_safe_dict()
    assert "secret" not in str(safe)
    assert "secret-token" not in str(safe)
