from __future__ import annotations

import pytest

from crypto_signal_bot.config import ConfigError, Settings


def test_default_config_is_research_only() -> None:
    settings = Settings()
    settings.validate_safety()
    assert settings.live_trading_enabled is False
    assert settings.private_api_enabled is False
    assert settings.require_manual_approval is True
    assert settings.notifications_enabled is False
    assert settings.telegram_enabled is False
    assert settings.discord_webhook_enabled is False


def test_unsafe_modes_fail_closed() -> None:
    with pytest.raises(ConfigError):
        Settings(live_trading_enabled=True).validate_safety()
    with pytest.raises(ConfigError):
        Settings(private_api_enabled=True).validate_safety()
    with pytest.raises(ConfigError):
        Settings(require_manual_approval=False).validate_safety()
