from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from crypto_signal_bot.signals.risk_filters import has_critical_risk
from crypto_signal_bot.signals.schemas import SignalCandidate


@dataclass(frozen=True)
class DigestPolicyConfig:
    enabled: bool = False
    top_n: int = 10
    interval_minutes: int = 60
    major_score_delta: float = 10.0


@dataclass(frozen=True)
class AlertDigest:
    digest_id: str
    created_at_utc: datetime
    interval_minutes: int
    top_candidates: list[dict[str, Any]]
    major_changes: list[dict[str, Any]]
    research_warning: str = "Research digest only. Not financial advice. No order was placed."
    notification_status: str = "not_scheduled"

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest_id": self.digest_id,
            "created_at_utc": self.created_at_utc.astimezone(UTC).isoformat(),
            "interval_minutes": self.interval_minutes,
            "top_candidates": self.top_candidates,
            "major_changes": self.major_changes,
            "research_warning": self.research_warning,
            "notification_status": self.notification_status,
        }


@dataclass(frozen=True)
class DigestScheduleStatus:
    checked_at_utc: datetime
    enabled: bool
    interval_minutes: int
    last_digest_at_utc: datetime | None
    next_digest_at_utc: datetime | None
    due: bool
    notification_status: str
    separate_policy_path: bool = True
    scheduler_daemon_required: bool = False
    no_notification_was_sent: bool = True
    research_warning: str = "Research digest schedule status only. Not financial advice. No order was placed."

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at_utc": self.checked_at_utc.astimezone(UTC).isoformat(),
            "enabled": self.enabled,
            "interval_minutes": self.interval_minutes,
            "last_digest_at_utc": (
                None if self.last_digest_at_utc is None else self.last_digest_at_utc.astimezone(UTC).isoformat()
            ),
            "next_digest_at_utc": (
                None if self.next_digest_at_utc is None else self.next_digest_at_utc.astimezone(UTC).isoformat()
            ),
            "due": self.due,
            "notification_status": self.notification_status,
            "separate_policy_path": self.separate_policy_path,
            "scheduler_daemon_required": self.scheduler_daemon_required,
            "no_notification_was_sent": self.no_notification_was_sent,
            "research_warning": self.research_warning,
        }


class DigestPolicy:
    def __init__(self, config: DigestPolicyConfig | None = None) -> None:
        self.config = config or DigestPolicyConfig()

    def schedule_status(
        self,
        *,
        last_digest_at: datetime | None = None,
        now: datetime | None = None,
    ) -> DigestScheduleStatus:
        now_utc = _as_utc(now or datetime.now(tz=UTC))
        last_utc = None if last_digest_at is None else _as_utc(last_digest_at)
        if not self.config.enabled:
            return DigestScheduleStatus(
                checked_at_utc=now_utc,
                enabled=False,
                interval_minutes=self.config.interval_minutes,
                last_digest_at_utc=last_utc,
                next_digest_at_utc=None,
                due=False,
                notification_status="disabled",
            )
        if last_utc is None:
            return DigestScheduleStatus(
                checked_at_utc=now_utc,
                enabled=True,
                interval_minutes=self.config.interval_minutes,
                last_digest_at_utc=None,
                next_digest_at_utc=now_utc,
                due=True,
                notification_status="due_no_previous_digest",
            )
        next_digest_at = last_utc + timedelta(minutes=self.config.interval_minutes)
        due = now_utc >= next_digest_at
        return DigestScheduleStatus(
            checked_at_utc=now_utc,
            enabled=True,
            interval_minutes=self.config.interval_minutes,
            last_digest_at_utc=last_utc,
            next_digest_at_utc=next_digest_at,
            due=due,
            notification_status="due" if due else "not_due",
        )

    def build_digest(
        self,
        candidates: list[SignalCandidate],
        *,
        previous_scores: dict[str, float] | None = None,
        now: datetime | None = None,
    ) -> AlertDigest | None:
        if not self.config.enabled:
            return None
        now_utc = now or datetime.now(tz=UTC)
        previous_scores = previous_scores or {}
        eligible = [candidate for candidate in candidates if _eligible_for_digest(candidate)]
        ranked = sorted(
            eligible,
            key=lambda candidate: (
                candidate.rank is None,
                candidate.rank if candidate.rank is not None else 10_000,
                -candidate.score,
            ),
        )[: self.config.top_n]
        major_changes = [
            _major_change(candidate, previous_score)
            for candidate in eligible
            if (previous_score := previous_scores.get(candidate.symbol)) is not None
            and abs(candidate.score - previous_score) >= self.config.major_score_delta
        ]
        major_changes.sort(key=lambda item: abs(float(item["score_delta"])), reverse=True)
        return AlertDigest(
            digest_id=str(uuid4()),
            created_at_utc=now_utc,
            interval_minutes=self.config.interval_minutes,
            top_candidates=[_candidate_digest_row(candidate) for candidate in ranked],
            major_changes=major_changes,
        )


def _eligible_for_digest(candidate: SignalCandidate) -> bool:
    return (
        candidate.is_closed_candle_signal
        and candidate.data_quality_status == "pass"
        and candidate.symbol_health_status != "quarantined"
        and candidate.benchmark_available
        and not has_critical_risk(candidate.risk_flags)
    )


def _candidate_digest_row(candidate: SignalCandidate) -> dict[str, Any]:
    return {
        "exchange": candidate.exchange,
        "symbol": candidate.symbol,
        "interval": candidate.interval,
        "rank": candidate.rank,
        "score": candidate.score,
        "confidence": candidate.confidence,
        "drivers": candidate.drivers[:5],
        "risk_flags": candidate.risk_flags[:5],
        "data_timestamp_utc": candidate.data_timestamp_utc,
        "data_freshness_seconds": candidate.data_freshness_seconds,
    }


def _major_change(candidate: SignalCandidate, previous_score: float) -> dict[str, Any]:
    return {
        "exchange": candidate.exchange,
        "symbol": candidate.symbol,
        "interval": candidate.interval,
        "previous_score": previous_score,
        "score": candidate.score,
        "score_delta": round(candidate.score - previous_score, 4),
        "rank": candidate.rank,
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
