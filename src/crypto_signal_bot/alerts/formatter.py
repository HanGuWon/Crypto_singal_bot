from __future__ import annotations

from html import escape
from typing import Any

from crypto_signal_bot.alerts.schemas import AlertEvent

RESEARCH_WARNING = "Research alert only. Not financial advice. No order was placed."
EXIT_GUARD_WARNING = (
    "Protective exit guard alert. Risk-reduction only. Not financial advice. "
    "No new position was opened. No order was placed."
)
FORBIDDEN_ALERT_WORDS = [
    "buy now",
    "guaranteed",
    "sure profit",
    "pump",
    "moon",
    "entry signal",
    "take profit",
    "leverage",
    "all-in",
    "urgent buy",
]


def validate_safe_message(text: str) -> None:
    lowered = text.lower()
    for word in FORBIDDEN_ALERT_WORDS:
        if word in lowered:
            raise ValueError(f"Forbidden alert wording detected: {word}")


def format_telegram_event(event: AlertEvent, *, max_length: int = 4096) -> str:
    manual_approval_request_id = _manual_approval_request_id(event)
    text = _telegram_text(
        event,
        driver_limit=5,
        risk_limit=5,
        invalidation_limit=None,
    )
    if len(text) > max_length:
        text = _telegram_text(event, driver_limit=3, risk_limit=3, invalidation_limit=140)
    if len(text) > max_length:
        text = _telegram_text(event, driver_limit=1, risk_limit=1, invalidation_limit=80)
    text = _truncate_preserving_warning(
        text,
        max_length=max_length,
        manual_approval_request_id=manual_approval_request_id,
    )
    validate_safe_message(text)
    return text


def format_discord_payload(
    event: AlertEvent,
    *,
    username: str = "Crypto Signal Research Bot",
    allow_mentions: bool = False,
) -> dict[str, Any]:
    manual_approval_request_id = _manual_approval_request_id(event)
    fields: list[dict[str, object]] = [
        {"name": "Score", "value": f"{event.score:.1f} ({event.confidence})", "inline": True},
        {"name": "Rank", "value": f"#{event.rank}" if event.rank is not None else "n/a", "inline": True},
        {
            "name": "Price",
            "value": f"{event.current_price:.8g}" if event.current_price is not None else "n/a",
            "inline": True,
        },
        {"name": "Drivers", "value": ", ".join(event.drivers[:5]) or "mixed_evidence"},
        {"name": "Risk flags", "value": ", ".join(event.risk_flags[:5]) or "none"},
        {"name": "Invalidation", "value": event.invalidation_condition},
        {"name": "Data timestamp UTC", "value": event.data_timestamp_utc},
        {"name": "Data freshness", "value": _format_freshness(event.data_freshness_seconds), "inline": True},
        {"name": "Alert event id", "value": event.alert_event_id},
        {"name": "Source run id", "value": event.source_run_id},
    ]
    if manual_approval_request_id is not None:
        fields.append({"name": "Manual approval request id", "value": manual_approval_request_id})
    warning = _warning_text(event)
    description = warning
    validate_safe_message(description + " " + " ".join(str(field["value"]) for field in fields))
    payload: dict[str, Any] = {
        "username": username,
        "content": warning,
        "embeds": [
            {
                "title": f"{event.exchange.upper()} {event.symbol} {event.interval}",
                "description": description,
                "color": _severity_color(event.severity),
                "fields": fields,
            }
        ],
        "allowed_mentions": {"parse": ["users", "roles", "everyone"] if allow_mentions else []},
    }
    return payload


def _truncate_preserving_warning(
    text: str,
    *,
    max_length: int,
    manual_approval_request_id: str | None = None,
) -> str:
    if len(text) <= max_length:
        return text
    warning = EXIT_GUARD_WARNING if EXIT_GUARD_WARNING in text else RESEARCH_WARNING
    suffix_parts = []
    if manual_approval_request_id is not None:
        suffix_parts.append(f"Manual approval request id: {escape(manual_approval_request_id)}")
    suffix_parts.append(warning)
    suffix = "\n" + "\n".join(suffix_parts)
    available = max_length - len(suffix) - 3
    if available < 0:
        return suffix.strip()[:max_length]
    return text[:available].rstrip() + "..." + suffix


def _telegram_text(
    event: AlertEvent,
    *,
    driver_limit: int,
    risk_limit: int,
    invalidation_limit: int | None,
) -> str:
    drivers = ", ".join(event.drivers[:driver_limit]) or "mixed_evidence"
    risks = ", ".join(event.risk_flags[:risk_limit]) or "none"
    rank = f"#{event.rank}" if event.rank is not None else "n/a"
    price = f"{event.current_price:.8g}" if event.current_price is not None else "n/a"
    invalidation = _clip_text(event.invalidation_condition, invalidation_limit)
    manual_approval_request_id = _manual_approval_request_id(event)
    lines = [
        f"<b>{escape(event.exchange.upper())} {escape(event.symbol)}</b> {escape(event.interval)}",
        f"Event: {escape(event.event_type)} | Severity: {escape(event.severity)}",
        f"Score: {event.score:.1f} | Confidence: {escape(event.confidence)} | Rank: {rank}",
        f"Price: {price}",
        f"Data timestamp UTC: {escape(event.data_timestamp_utc)}",
        f"Data freshness: {_format_freshness(event.data_freshness_seconds)}",
        f"Alert id: {escape(event.alert_event_id)}",
        f"Source run id: {escape(event.source_run_id)}",
        f"Drivers: {escape(drivers)}",
        f"Risk flags: {escape(risks)}",
        f"Invalidation: {escape(invalidation)}",
        _warning_text(event),
    ]
    if manual_approval_request_id is not None:
        lines.insert(-1, f"Manual approval request id: {escape(manual_approval_request_id)}")
    return "\n".join(lines)


def _manual_approval_request_id(event: AlertEvent) -> str | None:
    prefix = "manual_approval_request:"
    for driver in event.drivers:
        if driver.startswith(prefix):
            value = driver[len(prefix) :].strip()
            return value or None
    return None


def _warning_text(event: AlertEvent) -> str:
    if event.event_type.startswith("PROTECTIVE_EXIT_"):
        return EXIT_GUARD_WARNING
    return RESEARCH_WARNING


def _clip_text(value: str, max_length: int | None) -> str:
    if max_length is None or len(value) <= max_length:
        return value
    if max_length <= 3:
        return value[:max_length]
    return value[: max_length - 3].rstrip() + "..."


def _format_freshness(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    return f"{minutes / 60:.1f}h"


def _severity_color(severity: str) -> int:
    return {
        "INFO": 0x3498DB,
        "WATCH": 0x2ECC71,
        "WARNING": 0xF1C40F,
        "CRITICAL": 0xE74C3C,
    }.get(severity.upper(), 0x95A5A6)
