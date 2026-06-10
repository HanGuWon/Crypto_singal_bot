from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(ValueError):
    """Raised when configuration is invalid or unsafe."""


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class ExitGuardSettings:
    enabled: bool = False
    dry_run: bool = True
    private_read_enabled: bool = False
    live_exit_enabled: bool = False
    require_manual_approval: bool = True
    require_symbol_whitelist: bool = True
    discord_alerts_enabled: bool = False
    telegram_enabled: bool = False
    symbol_allowlist: tuple[str, ...] = ()
    max_orderbook_age_seconds: int = 30
    max_slippage_pct: float = 1.0


@dataclass(frozen=True)
class Settings:
    app_env: str = "local"
    log_level: str = "INFO"
    database_path: Path = Path("data/crypto_signal_bot.sqlite")
    display_timezone: str = "Asia/Seoul"

    live_trading_enabled: bool = False
    private_api_enabled: bool = False
    require_manual_approval: bool = True

    upbit_base_url: str = "https://api.upbit.com"
    binance_base_url: str = "https://data-api.binance.vision"
    default_request_timeout_seconds: float = 10.0
    max_symbols_per_collect: int = 20
    max_orderbook_symbols_per_collect: int = 10
    orderbook_depth_limit: int = 20
    polling_interval_seconds: int = 300

    min_quote_volume_upbit_krw: float = 2_000_000_000.0
    min_quote_volume_binance_usdt: float = 2_000_000.0
    max_spread_bps: float = 30.0
    max_staleness_seconds: int = 1200
    min_history_bars: int = 80
    symbol_quarantine_minutes: int = 120

    notifications_enabled: bool = False
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_parse_mode: str = "HTML"
    telegram_disable_notification: bool = False
    discord_webhook_enabled: bool = False
    discord_webhook_url: str = ""
    discord_username: str = "Crypto Signal Research Bot"
    discord_thread_id: str = ""
    discord_allow_mentions: bool = False

    alert_score_threshold: float = 80.0
    alert_exit_threshold: float = 65.0
    alert_score_delta_threshold: float = 15.0
    alert_cooldown_minutes: int = 60
    alert_top_n: int = 10
    alert_digest_enabled: bool = False
    alert_digest_interval_minutes: int = 60
    alert_global_max_per_minute: int = 10
    alert_per_symbol_max_per_hour: int = 1
    alert_safety_global_max_per_minute: int = 5
    alert_safety_per_symbol_max_per_hour: int = 3
    exit_guard: ExitGuardSettings = field(default_factory=ExitGuardSettings)

    def validate_safety(self) -> None:
        try:
            ZoneInfo(self.display_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError("DISPLAY_TIMEZONE must be a valid IANA timezone.") from exc
        if self.live_trading_enabled:
            raise ConfigError("LIVE_TRADING_ENABLED must remain false in this MVP.")
        if self.private_api_enabled:
            raise ConfigError("PRIVATE_API_ENABLED must remain false in this MVP.")
        if not self.require_manual_approval:
            raise ConfigError("REQUIRE_MANUAL_APPROVAL must remain true in this MVP.")
        if self.telegram_enabled and not self.notifications_enabled:
            raise ConfigError("TELEGRAM_ENABLED requires NOTIFICATIONS_ENABLED=true.")
        if self.discord_webhook_enabled and not self.notifications_enabled:
            raise ConfigError("DISCORD_WEBHOOK_ENABLED requires NOTIFICATIONS_ENABLED=true.")
        if self.exit_guard.private_read_enabled:
            raise ConfigError("EXIT_GUARD_PRIVATE_READ_ENABLED must remain false in this MVP.")
        if self.exit_guard.live_exit_enabled:
            raise ConfigError("EXIT_GUARD_LIVE_EXIT_ENABLED must remain false in this MVP.")
        if not self.exit_guard.dry_run:
            raise ConfigError("EXIT_GUARD_DRY_RUN must remain true in this MVP.")
        if not self.exit_guard.require_manual_approval:
            raise ConfigError("EXIT_GUARD_REQUIRE_MANUAL_APPROVAL must remain true in this MVP.")
        if not self.exit_guard.require_symbol_whitelist:
            raise ConfigError("EXIT_GUARD_REQUIRE_SYMBOL_WHITELIST must remain true in this MVP.")
        if self.exit_guard.telegram_enabled:
            raise ConfigError("Exit guard uses Discord-only alerts; Telegram is not allowed.")
        if self.exit_guard.max_orderbook_age_seconds <= 0:
            raise ConfigError("EXIT_GUARD_MAX_ORDERBOOK_AGE_SECONDS must be positive.")
        if self.exit_guard.max_slippage_pct <= 0:
            raise ConfigError("EXIT_GUARD_MAX_SLIPPAGE_PCT must be positive.")
        if self.exit_guard.discord_alerts_enabled and (
            not self.notifications_enabled or not self.discord_webhook_enabled
        ):
            raise ConfigError(
                "EXIT_GUARD_DISCORD_ALERTS_ENABLED requires NOTIFICATIONS_ENABLED=true "
                "and DISCORD_WEBHOOK_ENABLED=true."
            )
        if self.exit_guard.discord_alerts_enabled and not self.discord_webhook_url:
            raise ConfigError("EXIT_GUARD_DISCORD_ALERTS_ENABLED requires DISCORD_WEBHOOK_URL.")

    def validate_notification_channel(self, channel: str) -> None:
        if channel == "telegram":
            if not self.telegram_enabled:
                raise ConfigError("Telegram notifications are disabled.")
            if not self.telegram_bot_token or not self.telegram_chat_id:
                raise ConfigError("Telegram token and chat id are required when Telegram is enabled.")
        if channel == "discord":
            if not self.discord_webhook_enabled:
                raise ConfigError("Discord webhook notifications are disabled.")
            if not self.discord_webhook_url:
                raise ConfigError("Discord webhook URL is required when Discord is enabled.")


def load_settings() -> Settings:
    settings = Settings(
        app_env=_env("APP_ENV", "local"),
        log_level=_env("LOG_LEVEL", "INFO"),
        database_path=Path(_env("DATABASE_PATH", "data/crypto_signal_bot.sqlite")),
        display_timezone=_env("DISPLAY_TIMEZONE", "Asia/Seoul"),
        live_trading_enabled=_parse_bool(_env("LIVE_TRADING_ENABLED", "false")),
        private_api_enabled=_parse_bool(_env("PRIVATE_API_ENABLED", "false")),
        require_manual_approval=_parse_bool(_env("REQUIRE_MANUAL_APPROVAL", "true"), default=True),
        upbit_base_url=_env("UPBIT_BASE_URL", "https://api.upbit.com"),
        binance_base_url=_env("BINANCE_BASE_URL", "https://data-api.binance.vision"),
        default_request_timeout_seconds=float(_env("DEFAULT_REQUEST_TIMEOUT_SECONDS", "10")),
        max_symbols_per_collect=int(_env("MAX_SYMBOLS_PER_COLLECT", "20")),
        max_orderbook_symbols_per_collect=int(_env("MAX_ORDERBOOK_SYMBOLS_PER_COLLECT", "10")),
        orderbook_depth_limit=int(_env("ORDERBOOK_DEPTH_LIMIT", "20")),
        polling_interval_seconds=int(_env("POLLING_INTERVAL_SECONDS", "300")),
        min_quote_volume_upbit_krw=float(_env("MIN_QUOTE_VOLUME_UPBIT_KRW", "2000000000")),
        min_quote_volume_binance_usdt=float(_env("MIN_QUOTE_VOLUME_BINANCE_USDT", "2000000")),
        max_spread_bps=float(_env("MAX_SPREAD_BPS", "30")),
        max_staleness_seconds=int(_env("MAX_STALENESS_SECONDS", "1200")),
        min_history_bars=int(_env("MIN_HISTORY_BARS", "80")),
        symbol_quarantine_minutes=int(_env("SYMBOL_QUARANTINE_MINUTES", "120")),
        notifications_enabled=_parse_bool(_env("NOTIFICATIONS_ENABLED", "false")),
        telegram_enabled=_parse_bool(_env("TELEGRAM_ENABLED", "false")),
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID", ""),
        telegram_parse_mode=_env("TELEGRAM_PARSE_MODE", "HTML"),
        telegram_disable_notification=_parse_bool(_env("TELEGRAM_DISABLE_NOTIFICATION", "false")),
        discord_webhook_enabled=_parse_bool(_env("DISCORD_WEBHOOK_ENABLED", "false")),
        discord_webhook_url=_env("DISCORD_WEBHOOK_URL", ""),
        discord_username=_env("DISCORD_USERNAME", "Crypto Signal Research Bot"),
        discord_thread_id=_env("DISCORD_THREAD_ID", ""),
        discord_allow_mentions=_parse_bool(_env("DISCORD_ALLOW_MENTIONS", "false")),
        alert_score_threshold=float(_env("ALERT_SCORE_THRESHOLD", "80")),
        alert_exit_threshold=float(_env("ALERT_EXIT_THRESHOLD", "65")),
        alert_score_delta_threshold=float(_env("ALERT_SCORE_DELTA_THRESHOLD", "15")),
        alert_cooldown_minutes=int(_env("ALERT_COOLDOWN_MINUTES", "60")),
        alert_top_n=int(_env("ALERT_TOP_N", "10")),
        alert_digest_enabled=_parse_bool(_env("ALERT_DIGEST_ENABLED", "false")),
        alert_digest_interval_minutes=int(_env("ALERT_DIGEST_INTERVAL_MINUTES", "60")),
        alert_global_max_per_minute=int(_env("ALERT_GLOBAL_MAX_PER_MINUTE", "10")),
        alert_per_symbol_max_per_hour=int(_env("ALERT_PER_SYMBOL_MAX_PER_HOUR", "1")),
        alert_safety_global_max_per_minute=int(_env("ALERT_SAFETY_GLOBAL_MAX_PER_MINUTE", "5")),
        alert_safety_per_symbol_max_per_hour=int(_env("ALERT_SAFETY_PER_SYMBOL_MAX_PER_HOUR", "3")),
        exit_guard=ExitGuardSettings(
            enabled=_parse_bool(_env("EXIT_GUARD_ENABLED", "false")),
            dry_run=_parse_bool(_env("EXIT_GUARD_DRY_RUN", "true"), default=True),
            private_read_enabled=_parse_bool(_env("EXIT_GUARD_PRIVATE_READ_ENABLED", "false")),
            live_exit_enabled=_parse_bool(_env("EXIT_GUARD_LIVE_EXIT_ENABLED", "false")),
            require_manual_approval=_parse_bool(
                _env("EXIT_GUARD_REQUIRE_MANUAL_APPROVAL", "true"),
                default=True,
            ),
            require_symbol_whitelist=_parse_bool(
                _env("EXIT_GUARD_REQUIRE_SYMBOL_WHITELIST", "true"),
                default=True,
            ),
            discord_alerts_enabled=_parse_bool(_env("EXIT_GUARD_DISCORD_ALERTS_ENABLED", "false")),
            telegram_enabled=_parse_bool(_env("EXIT_GUARD_TELEGRAM_ENABLED", "false")),
            symbol_allowlist=_parse_csv(_env("EXIT_GUARD_SYMBOL_ALLOWLIST", "")),
            max_orderbook_age_seconds=int(_env("EXIT_GUARD_MAX_ORDERBOOK_AGE_SECONDS", "30")),
            max_slippage_pct=float(_env("EXIT_GUARD_MAX_SLIPPAGE_PCT", "1.0")),
        ),
    )
    settings.validate_safety()
    return settings
