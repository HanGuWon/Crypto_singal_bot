from __future__ import annotations

from crypto_signal_bot.logging_config import redact_secrets


def test_redacts_telegram_and_discord_secrets() -> None:
    text = (
        "telegram_bot_token=secret-token "
        "https://api.telegram.org/botsecret-token/sendMessage "
        "https://discord.com/api/webhooks/123/secret"
    )
    redacted = redact_secrets(text)
    assert "secret-token" not in redacted
    assert "/123/secret" not in redacted
    assert "[REDACTED]" in redacted
