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


def _profile_value(profile: dict[str, str], name: str, default: str) -> str:
    return os.environ.get(name, profile.get(name, default))


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_int(name: str, default: str) -> int:
    raw = _env(name, default)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


def _env_float(name: str, default: str) -> float:
    raw = _env(name, default)
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number.") from exc


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
    primary_exchange: str = "binance"
    default_quote: str = "USDT"
    upbit_enabled: bool = True
    binance_enabled: bool = True
    public_data_only: bool = True
    default_intervals: tuple[str, ...] = ("5m", "15m", "30m")

    live_trading_enabled: bool = False
    private_api_enabled: bool = False
    require_manual_approval: bool = True

    upbit_base_url: str = "https://api.upbit.com"
    binance_base_url: str = "https://data-api.binance.vision"
    default_request_timeout_seconds: float = 10.0
    max_symbols_per_collect: int = 20
    max_orderbook_symbols_per_collect: int = 10
    orderbook_depth_limit: int = 20
    max_orderbook_age_seconds: int = 60
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
        if self.primary_exchange not in {"binance", "upbit"}:
            raise ConfigError("PRIMARY_EXCHANGE must be binance or upbit.")
        if self.primary_exchange == "binance" and not self.binance_enabled:
            raise ConfigError("PRIMARY_EXCHANGE=binance requires BINANCE_ENABLED=true.")
        if self.primary_exchange == "upbit" and not self.upbit_enabled:
            raise ConfigError("PRIMARY_EXCHANGE=upbit requires UPBIT_ENABLED=true.")
        if not self.public_data_only:
            raise ConfigError("PUBLIC_DATA_ONLY must remain true in this MVP.")
        if not self.default_intervals:
            raise ConfigError("DEFAULT_INTERVALS must contain at least one interval.")
        if self.telegram_enabled and not self.notifications_enabled:
            raise ConfigError("TELEGRAM_ENABLED requires NOTIFICATIONS_ENABLED=true.")
        if self.discord_webhook_enabled and not self.notifications_enabled:
            raise ConfigError("DISCORD_WEBHOOK_ENABLED requires NOTIFICATIONS_ENABLED=true.")
        _require_positive("DEFAULT_REQUEST_TIMEOUT_SECONDS", self.default_request_timeout_seconds)
        _require_positive("MAX_SYMBOLS_PER_COLLECT", self.max_symbols_per_collect)
        _require_non_negative("MAX_ORDERBOOK_SYMBOLS_PER_COLLECT", self.max_orderbook_symbols_per_collect)
        _require_positive("ORDERBOOK_DEPTH_LIMIT", self.orderbook_depth_limit)
        _require_positive("MAX_ORDERBOOK_AGE_SECONDS", self.max_orderbook_age_seconds)
        _require_positive("POLLING_INTERVAL_SECONDS", self.polling_interval_seconds)
        _require_non_negative("MIN_QUOTE_VOLUME_UPBIT_KRW", self.min_quote_volume_upbit_krw)
        _require_non_negative("MIN_QUOTE_VOLUME_BINANCE_USDT", self.min_quote_volume_binance_usdt)
        _require_positive("MAX_SPREAD_BPS", self.max_spread_bps)
        _require_positive("MAX_STALENESS_SECONDS", self.max_staleness_seconds)
        _require_positive("MIN_HISTORY_BARS", self.min_history_bars)
        _require_positive("SYMBOL_QUARANTINE_MINUTES", self.symbol_quarantine_minutes)
        _require_score_threshold("ALERT_SCORE_THRESHOLD", self.alert_score_threshold)
        _require_score_threshold("ALERT_EXIT_THRESHOLD", self.alert_exit_threshold)
        if self.alert_exit_threshold >= self.alert_score_threshold:
            raise ConfigError("ALERT_EXIT_THRESHOLD must be lower than ALERT_SCORE_THRESHOLD.")
        _require_positive("ALERT_SCORE_DELTA_THRESHOLD", self.alert_score_delta_threshold)
        _require_positive("ALERT_COOLDOWN_MINUTES", self.alert_cooldown_minutes)
        _require_positive("ALERT_TOP_N", self.alert_top_n)
        _require_positive("ALERT_DIGEST_INTERVAL_MINUTES", self.alert_digest_interval_minutes)
        _require_positive("ALERT_GLOBAL_MAX_PER_MINUTE", self.alert_global_max_per_minute)
        _require_positive("ALERT_PER_SYMBOL_MAX_PER_HOUR", self.alert_per_symbol_max_per_hour)
        _require_positive("ALERT_SAFETY_GLOBAL_MAX_PER_MINUTE", self.alert_safety_global_max_per_minute)
        _require_positive("ALERT_SAFETY_PER_SYMBOL_MAX_PER_HOUR", self.alert_safety_per_symbol_max_per_hour)
        if self.exit_guard.enabled and self.primary_exchange == "binance":
            raise ConfigError("EXIT_GUARD_ENABLED must remain false in the Binance spot public-data profile.")
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


def load_settings(profile_path: str | Path | None = None) -> Settings:
    profile = _load_profile_values(profile_path)

    def value(name: str, default: str) -> str:
        return _profile_value(profile, name, default)

    settings = Settings(
        app_env=value("APP_ENV", "local"),
        log_level=value("LOG_LEVEL", "INFO"),
        database_path=Path(value("DATABASE_PATH", "data/crypto_signal_bot.sqlite")),
        display_timezone=value("DISPLAY_TIMEZONE", "Asia/Seoul"),
        primary_exchange=value("PRIMARY_EXCHANGE", "binance"),
        default_quote=value("QUOTE", "USDT"),
        upbit_enabled=_parse_bool(value("UPBIT_ENABLED", "true"), default=True),
        binance_enabled=_parse_bool(value("BINANCE_ENABLED", "true"), default=True),
        public_data_only=_parse_bool(value("PUBLIC_DATA_ONLY", "true"), default=True),
        default_intervals=_parse_csv(value("DEFAULT_INTERVALS", "5m,15m,30m")),
        live_trading_enabled=_parse_bool(value("LIVE_TRADING_ENABLED", "false")),
        private_api_enabled=_parse_bool(value("PRIVATE_API_ENABLED", "false")),
        require_manual_approval=_parse_bool(value("REQUIRE_MANUAL_APPROVAL", "true"), default=True),
        upbit_base_url=value("UPBIT_BASE_URL", "https://api.upbit.com"),
        binance_base_url=value("BINANCE_BASE_URL", "https://data-api.binance.vision"),
        default_request_timeout_seconds=_parse_float(
            value("DEFAULT_REQUEST_TIMEOUT_SECONDS", "10"),
            "DEFAULT_REQUEST_TIMEOUT_SECONDS",
        ),
        max_symbols_per_collect=_parse_int(value("MAX_SYMBOLS_PER_COLLECT", "20"), "MAX_SYMBOLS_PER_COLLECT"),
        max_orderbook_symbols_per_collect=_parse_int(
            value("MAX_ORDERBOOK_SYMBOLS_PER_COLLECT", "10"),
            "MAX_ORDERBOOK_SYMBOLS_PER_COLLECT",
        ),
        orderbook_depth_limit=_parse_int(value("ORDERBOOK_DEPTH_LIMIT", "20"), "ORDERBOOK_DEPTH_LIMIT"),
        max_orderbook_age_seconds=_parse_int(value("MAX_ORDERBOOK_AGE_SECONDS", "60"), "MAX_ORDERBOOK_AGE_SECONDS"),
        polling_interval_seconds=_parse_int(value("POLLING_INTERVAL_SECONDS", "300"), "POLLING_INTERVAL_SECONDS"),
        min_quote_volume_upbit_krw=_parse_float(
            value("MIN_QUOTE_VOLUME_UPBIT_KRW", "2000000000"),
            "MIN_QUOTE_VOLUME_UPBIT_KRW",
        ),
        min_quote_volume_binance_usdt=_parse_float(
            value("MIN_QUOTE_VOLUME_BINANCE_USDT", "2000000"),
            "MIN_QUOTE_VOLUME_BINANCE_USDT",
        ),
        max_spread_bps=_parse_float(value("MAX_SPREAD_BPS", "30"), "MAX_SPREAD_BPS"),
        max_staleness_seconds=_parse_int(value("MAX_STALENESS_SECONDS", "1200"), "MAX_STALENESS_SECONDS"),
        min_history_bars=_parse_int(value("MIN_HISTORY_BARS", "80"), "MIN_HISTORY_BARS"),
        symbol_quarantine_minutes=_parse_int(value("SYMBOL_QUARANTINE_MINUTES", "120"), "SYMBOL_QUARANTINE_MINUTES"),
        notifications_enabled=_parse_bool(value("NOTIFICATIONS_ENABLED", "false")),
        telegram_enabled=_parse_bool(value("TELEGRAM_ENABLED", "false")),
        telegram_bot_token=value("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=value("TELEGRAM_CHAT_ID", ""),
        telegram_parse_mode=value("TELEGRAM_PARSE_MODE", "HTML"),
        telegram_disable_notification=_parse_bool(value("TELEGRAM_DISABLE_NOTIFICATION", "false")),
        discord_webhook_enabled=_parse_bool(value("DISCORD_WEBHOOK_ENABLED", "false")),
        discord_webhook_url=value("DISCORD_WEBHOOK_URL", ""),
        discord_username=value("DISCORD_USERNAME", "Crypto Signal Research Bot"),
        discord_thread_id=value("DISCORD_THREAD_ID", ""),
        discord_allow_mentions=_parse_bool(value("DISCORD_ALLOW_MENTIONS", "false")),
        alert_score_threshold=_parse_float(value("ALERT_SCORE_THRESHOLD", "80"), "ALERT_SCORE_THRESHOLD"),
        alert_exit_threshold=_parse_float(value("ALERT_EXIT_THRESHOLD", "65"), "ALERT_EXIT_THRESHOLD"),
        alert_score_delta_threshold=_parse_float(
            value("ALERT_SCORE_DELTA_THRESHOLD", "15"),
            "ALERT_SCORE_DELTA_THRESHOLD",
        ),
        alert_cooldown_minutes=_parse_int(value("ALERT_COOLDOWN_MINUTES", "60"), "ALERT_COOLDOWN_MINUTES"),
        alert_top_n=_parse_int(value("ALERT_TOP_N", "10"), "ALERT_TOP_N"),
        alert_digest_enabled=_parse_bool(value("ALERT_DIGEST_ENABLED", "false")),
        alert_digest_interval_minutes=_parse_int(
            value("ALERT_DIGEST_INTERVAL_MINUTES", "60"),
            "ALERT_DIGEST_INTERVAL_MINUTES",
        ),
        alert_global_max_per_minute=_parse_int(
            value("ALERT_GLOBAL_MAX_PER_MINUTE", "10"),
            "ALERT_GLOBAL_MAX_PER_MINUTE",
        ),
        alert_per_symbol_max_per_hour=_parse_int(
            value("ALERT_PER_SYMBOL_MAX_PER_HOUR", "1"),
            "ALERT_PER_SYMBOL_MAX_PER_HOUR",
        ),
        alert_safety_global_max_per_minute=_parse_int(
            value("ALERT_SAFETY_GLOBAL_MAX_PER_MINUTE", "5"),
            "ALERT_SAFETY_GLOBAL_MAX_PER_MINUTE",
        ),
        alert_safety_per_symbol_max_per_hour=_parse_int(
            value("ALERT_SAFETY_PER_SYMBOL_MAX_PER_HOUR", "3"),
            "ALERT_SAFETY_PER_SYMBOL_MAX_PER_HOUR",
        ),
        exit_guard=ExitGuardSettings(
            enabled=_parse_bool(value("EXIT_GUARD_ENABLED", "false")),
            dry_run=_parse_bool(value("EXIT_GUARD_DRY_RUN", "true"), default=True),
            private_read_enabled=_parse_bool(value("EXIT_GUARD_PRIVATE_READ_ENABLED", "false")),
            live_exit_enabled=_parse_bool(value("EXIT_GUARD_LIVE_EXIT_ENABLED", "false")),
            require_manual_approval=_parse_bool(
                value("EXIT_GUARD_REQUIRE_MANUAL_APPROVAL", "true"),
                default=True,
            ),
            require_symbol_whitelist=_parse_bool(
                value("EXIT_GUARD_REQUIRE_SYMBOL_WHITELIST", "true"),
                default=True,
            ),
            discord_alerts_enabled=_parse_bool(value("EXIT_GUARD_DISCORD_ALERTS_ENABLED", "false")),
            telegram_enabled=_parse_bool(value("EXIT_GUARD_TELEGRAM_ENABLED", "false")),
            symbol_allowlist=_parse_csv(value("EXIT_GUARD_SYMBOL_ALLOWLIST", "")),
            max_orderbook_age_seconds=_parse_int(
                value("EXIT_GUARD_MAX_ORDERBOOK_AGE_SECONDS", "30"),
                "EXIT_GUARD_MAX_ORDERBOOK_AGE_SECONDS",
            ),
            max_slippage_pct=_parse_float(
                value("EXIT_GUARD_MAX_SLIPPAGE_PCT", "1.0"),
                "EXIT_GUARD_MAX_SLIPPAGE_PCT",
            ),
        ),
    )
    settings.validate_safety()
    return settings


def _parse_int(raw: str, name: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


def _parse_float(raw: str, name: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number.") from exc


def _load_profile_values(profile_path: str | Path | None) -> dict[str, str]:
    if profile_path is None:
        return {}
    path = Path(profile_path)
    if not path.exists():
        raise ConfigError(f"Profile not found: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped and ":" not in stripped.split("=", 1)[0]:
            key, raw_value = stripped.split("=", 1)
        elif ":" in stripped and not line.startswith((" ", "\t")):
            key, raw_value = stripped.split(":", 1)
        else:
            continue
        key = key.strip()
        if not key.isupper():
            continue
        values[key] = raw_value.strip().strip('"').strip("'")
    return values


def _require_positive(name: str, value: int | float) -> None:
    if value <= 0:
        raise ConfigError(f"{name} must be positive.")


def _require_non_negative(name: str, value: int | float) -> None:
    if value < 0:
        raise ConfigError(f"{name} must be zero or positive.")


def _require_score_threshold(name: str, value: float) -> None:
    if value < 0 or value > 100:
        raise ConfigError(f"{name} must be between 0 and 100.")
