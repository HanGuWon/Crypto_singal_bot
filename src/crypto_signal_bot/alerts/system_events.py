from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.logging_config import redact_secrets

SYSTEM_ERROR_INVALIDATION = (
    "System/data/API failure alert. Not a trading signal. Investigate and restore healthy "
    "data or notification operation before relying on research output."
)


def build_system_error_event(
    *,
    component: str,
    operation: str,
    error: BaseException | str,
    exchange: str = "system",
    symbol: str = "SYSTEM",
    interval: str = "n/a",
    error_code: str | None = None,
    now: datetime | None = None,
    source_run_id: str | None = None,
) -> AlertEvent:
    """Build an audit-only SYSTEM_ERROR event without exposing secrets."""

    now_utc = (now or datetime.now(tz=UTC)).astimezone(UTC)
    error_class = type(error).__name__ if isinstance(error, BaseException) else "SystemError"
    safe_error = _clip(redact_secrets(error), 160)
    drivers = [
        f"component:{_clip(component, 80)}",
        f"operation:{_clip(operation, 80)}",
        f"error_class:{_clip(error_class, 80)}",
        f"error_detail:{safe_error}",
    ]
    if error_code:
        drivers.append(f"error_code:{_clip(error_code, 40)}")
    risk_flags = ["system_error", "not_trading_signal"]
    if "rate" in error_class.lower() or error_code == "429":
        risk_flags.append("rate_limited")
    dedupe_key = _system_error_dedupe_key(
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        component=component,
        operation=operation,
        error_class=error_class,
        error_code=error_code,
        safe_error=safe_error,
    )
    return AlertEvent(
        alert_event_id=str(uuid4()),
        created_at_utc=now_utc,
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        event_type="SYSTEM_ERROR",
        severity="CRITICAL",
        score=0.0,
        previous_score=None,
        confidence="system",
        current_price=None,
        rank=None,
        drivers=drivers,
        risk_flags=risk_flags,
        invalidation_condition=SYSTEM_ERROR_INVALIDATION,
        data_timestamp_utc=now_utc.isoformat(),
        data_freshness_seconds=0.0,
        dedupe_key=dedupe_key,
        source_run_id=source_run_id or f"system_error:{uuid4()}",
    )


def _system_error_dedupe_key(
    *,
    exchange: str,
    symbol: str,
    interval: str,
    component: str,
    operation: str,
    error_class: str,
    error_code: str | None,
    safe_error: str,
) -> str:
    payload = "|".join([exchange, symbol, interval, component, operation, error_class, error_code or "", safe_error])
    digest = sha256(payload.encode()).hexdigest()[:16]
    return f"{exchange}:{symbol}:{interval}:SYSTEM_ERROR:{_clip(component, 32)}:{digest}"


def _clip(value: str, max_length: int) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return text[: max_length - 3].rstrip() + "..."
