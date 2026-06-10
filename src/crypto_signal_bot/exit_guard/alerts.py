from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.data.models import ensure_utc
from crypto_signal_bot.exit_guard.models import (
    OrderBookSlippageAssessment,
    ProtectiveExitSignal,
    RiskReducingOrderIntent,
)

EXIT_GUARD_INVALIDATION = (
    "Protective exit review invalidates if data quality fails, the closed-candle guard fails, "
    "manual approval is missing, or the public orderbook preflight is blocked."
)


def build_protective_exit_alert_event(
    signal: ProtectiveExitSignal,
    *,
    intent: RiskReducingOrderIntent | None = None,
    slippage: OrderBookSlippageAssessment | None = None,
    now: datetime | None = None,
) -> AlertEvent:
    created_at = ensure_utc(now or datetime.now(tz=UTC))
    drivers = _drivers(signal, intent, slippage)
    risk_flags = _risk_flags(signal, slippage)
    is_blocked = signal.state in {"BLOCKED", "SAFETY_BLOCKED"} or (
        slippage is not None and not slippage.passed
    )
    event_type = "PROTECTIVE_EXIT_BLOCKED" if is_blocked else "PROTECTIVE_EXIT_WATCH"
    severity = "WARNING" if event_type == "PROTECTIVE_EXIT_BLOCKED" or risk_flags else "WATCH"
    data_freshness = (created_at - signal.created_at_utc).total_seconds()
    if data_freshness < 0:
        risk_flags = _unique([*risk_flags, "exit_guard_timestamp_drift"])
        data_freshness = 0.0
    return AlertEvent(
        alert_event_id=str(uuid4()),
        created_at_utc=created_at,
        exchange=signal.exchange,
        symbol=signal.symbol,
        interval=signal.interval,
        event_type=event_type,
        severity=severity,
        score=_bounded_score(signal.exit_score),
        previous_score=None,
        confidence="research_only",
        current_price=slippage.reference_price if slippage is not None else None,
        rank=None,
        drivers=drivers,
        risk_flags=risk_flags,
        invalidation_condition=EXIT_GUARD_INVALIDATION,
        data_timestamp_utc=signal.created_at_utc.isoformat(),
        data_freshness_seconds=round(data_freshness, 3),
        dedupe_key=_dedupe_key(signal, event_type, drivers, risk_flags),
        source_run_id=signal.signal_id,
    )


def _drivers(
    signal: ProtectiveExitSignal,
    intent: RiskReducingOrderIntent | None,
    slippage: OrderBookSlippageAssessment | None,
) -> list[str]:
    values = [
        "protective_exit_guard_alert",
        "risk_reduction_only",
        "dry_run_only",
        "manual_approval_required",
        f"state:{signal.state}",
        *signal.drivers,
    ]
    if intent is not None:
        values.extend(
            [
                f"intent:{intent.action}",
                f"market_side:{intent.side}",
            ]
        )
    if slippage is not None:
        values.extend(
            [
                f"orderbook_preflight:{slippage.status}",
                f"filled_quantity:{slippage.filled_quantity:.8g}",
            ]
        )
        if slippage.estimated_slippage_pct is not None:
            values.append(f"estimated_slippage_pct:{slippage.estimated_slippage_pct:.6g}")
    return _unique(values)[:12]


def _risk_flags(
    signal: ProtectiveExitSignal,
    slippage: OrderBookSlippageAssessment | None,
) -> list[str]:
    values = list(signal.risk_flags)
    if slippage is not None and not slippage.passed:
        values.extend(slippage.risk_flags)
    return _unique(values)[:12]


def _dedupe_key(
    signal: ProtectiveExitSignal,
    event_type: str,
    drivers: list[str],
    risk_flags: list[str],
) -> str:
    score_bucket = int(_bounded_score(signal.exit_score) // 5) * 5
    material = "|".join(sorted([*drivers[:6], *(f"risk:{flag}" for flag in risk_flags[:6])]))
    material_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    return f"{signal.exchange}:{signal.symbol}:{signal.interval}:{event_type}:{score_bucket}:{material_hash}"


def _bounded_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
