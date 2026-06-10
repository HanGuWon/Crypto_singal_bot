from __future__ import annotations

import pytest

from crypto_signal_bot.config import ConfigError, ExitGuardSettings, Settings


def test_default_config_is_research_only() -> None:
    settings = Settings()
    settings.validate_safety()
    assert settings.live_trading_enabled is False
    assert settings.private_api_enabled is False
    assert settings.require_manual_approval is True
    assert settings.notifications_enabled is False
    assert settings.telegram_enabled is False
    assert settings.discord_webhook_enabled is False
    assert settings.alert_safety_global_max_per_minute == 5
    assert settings.alert_safety_per_symbol_max_per_hour == 3
    assert settings.min_history_bars == 80
    assert settings.symbol_quarantine_minutes == 120
    assert settings.max_orderbook_symbols_per_collect == 10
    assert settings.orderbook_depth_limit == 20
    assert settings.display_timezone == "Asia/Seoul"
    assert settings.exit_guard.enabled is False
    assert settings.exit_guard.dry_run is True
    assert settings.exit_guard.private_read_enabled is False
    assert settings.exit_guard.live_exit_enabled is False
    assert settings.exit_guard.require_manual_approval is True
    assert settings.exit_guard.require_symbol_whitelist is True
    assert settings.exit_guard.discord_alerts_enabled is False
    assert settings.exit_guard.telegram_enabled is False


def test_unsafe_modes_fail_closed() -> None:
    with pytest.raises(ConfigError):
        Settings(live_trading_enabled=True).validate_safety()
    with pytest.raises(ConfigError):
        Settings(private_api_enabled=True).validate_safety()
    with pytest.raises(ConfigError):
        Settings(require_manual_approval=False).validate_safety()


def test_invalid_display_timezone_is_rejected() -> None:
    with pytest.raises(ConfigError):
        Settings(display_timezone="Not/A_Timezone").validate_safety()


def test_exit_guard_unsafe_modes_fail_closed() -> None:
    unsafe_configs = [
        ExitGuardSettings(private_read_enabled=True),
        ExitGuardSettings(live_exit_enabled=True),
        ExitGuardSettings(dry_run=False),
        ExitGuardSettings(require_manual_approval=False),
        ExitGuardSettings(require_symbol_whitelist=False),
        ExitGuardSettings(telegram_enabled=True),
        ExitGuardSettings(discord_alerts_enabled=True),
    ]
    for exit_guard in unsafe_configs:
        with pytest.raises(ConfigError):
            Settings(exit_guard=exit_guard).validate_safety()


def test_exit_guard_discord_alerts_require_global_discord_config() -> None:
    settings = Settings(
        notifications_enabled=True,
        discord_webhook_enabled=True,
        discord_webhook_url="https://discord.com/api/webhooks/example/redacted",
        exit_guard=ExitGuardSettings(discord_alerts_enabled=True),
    )

    settings.validate_safety()


def test_exit_guard_discord_alerts_require_webhook_url() -> None:
    with pytest.raises(ConfigError):
        Settings(
            notifications_enabled=True,
            discord_webhook_enabled=True,
            exit_guard=ExitGuardSettings(discord_alerts_enabled=True),
        ).validate_safety()
