from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from crypto_signal_bot.alerts.dedupe import make_dedupe_key
from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.alerts.state import AlertState, AlertStateStore, InMemoryAlertStateStore
from crypto_signal_bot.signals.risk_filters import has_critical_risk
from crypto_signal_bot.signals.schemas import SignalCandidate


@dataclass(frozen=True)
class AlertPolicyConfig:
    score_threshold: float = 80.0
    exit_threshold: float = 65.0
    score_delta_threshold: float = 15.0
    top_n: int = 10
    cooldown_minutes: int = 60


class AlertPolicy:
    def __init__(
        self,
        config: AlertPolicyConfig | None = None,
        state_store: AlertStateStore | None = None,
    ) -> None:
        self.config = config or AlertPolicyConfig()
        self.state_store = state_store or InMemoryAlertStateStore()

    def evaluate(
        self,
        candidates: list[SignalCandidate],
        *,
        previous_scores: dict[str, float] | None = None,
        previous_ranks: dict[str, int] | None = None,
        now: datetime | None = None,
    ) -> list[AlertEvent]:
        now_utc = now or datetime.now(tz=UTC)
        previous_scores = previous_scores or {}
        previous_ranks = previous_ranks or {}
        events: list[AlertEvent] = []
        for candidate in candidates:
            events.extend(
                self._evaluate_candidate(
                    candidate,
                    previous_score=previous_scores.get(candidate.symbol),
                    previous_rank=previous_ranks.get(candidate.symbol),
                    now=now_utc,
                )
            )
        return events

    def _evaluate_candidate(
        self,
        candidate: SignalCandidate,
        *,
        previous_score: float | None,
        previous_rank: int | None,
        now: datetime,
    ) -> list[AlertEvent]:
        severe_risk = has_critical_risk(candidate.risk_flags)
        state = self.state_store.get(
            candidate.exchange, candidate.symbol, candidate.interval, "SCORE_THRESHOLD_CROSSED"
        )

        if state.active and (
            candidate.score <= self.config.exit_threshold
            or candidate.data_quality_status != "pass"
            or "stale_data" in candidate.risk_flags
        ):
            event = self._event(
                candidate,
                "INVALIDATION",
                "WARNING",
                previous_score,
                now,
                risk_flags=candidate.risk_flags or ["score_below_exit_threshold"],
            )
            invalidation_state = self.state_store.get(
                candidate.exchange, candidate.symbol, candidate.interval, "INVALIDATION"
            )
            self.state_store.set_active(
                candidate.exchange,
                candidate.symbol,
                candidate.interval,
                "SCORE_THRESHOLD_CROSSED",
                active=False,
                score=candidate.score,
                alerted_at_utc=now,
            )
            if self._state_allows_event(invalidation_state, event, now):
                self.state_store.set_active(
                    candidate.exchange,
                    candidate.symbol,
                    candidate.interval,
                    "INVALIDATION",
                    active=True,
                    score=candidate.score,
                    dedupe_key=event.dedupe_key,
                    alerted_at_utc=now,
                )
                return [event]
            return []

        risk_state = self.state_store.get(
            candidate.exchange, candidate.symbol, candidate.interval, "RISK_WARNING"
        )
        if severe_risk and state.active:
            event = self._event(candidate, "RISK_WARNING", "WARNING", previous_score, now)
            if self._state_allows_event(risk_state, event, now):
                self.state_store.set_active(
                    candidate.exchange,
                    candidate.symbol,
                    candidate.interval,
                    "RISK_WARNING",
                    active=True,
                    score=candidate.score,
                    dedupe_key=event.dedupe_key,
                    alerted_at_utc=now,
                )
                return [event]
            return []
        if not severe_risk and risk_state.active:
            self.state_store.set_active(
                candidate.exchange,
                candidate.symbol,
                candidate.interval,
                "RISK_WARNING",
                active=False,
                score=candidate.score,
            )

        if not _eligible_for_upside_alert(candidate):
            return []

        events: list[AlertEvent] = []
        threshold_crossed = candidate.score >= self.config.score_threshold
        was_below = previous_score is None or previous_score < self.config.score_threshold
        if threshold_crossed and was_below and not state.active:
            event = self._event(candidate, "SCORE_THRESHOLD_CROSSED", "WATCH", previous_score, now)
            if self._state_allows_event(state, event, now):
                events.append(event)
                self.state_store.set_active(
                    candidate.exchange,
                    candidate.symbol,
                    candidate.interval,
                    "SCORE_THRESHOLD_CROSSED",
                    active=True,
                    score=candidate.score,
                    dedupe_key=event.dedupe_key,
                    alerted_at_utc=now,
                )
                self.state_store.set_active(
                    candidate.exchange,
                    candidate.symbol,
                    candidate.interval,
                    "INVALIDATION",
                    active=False,
                    score=candidate.score,
                )

        if (
            candidate.rank is not None
            and candidate.rank <= self.config.top_n
            and candidate.score >= self.config.exit_threshold
            and (previous_rank is None or previous_rank > self.config.top_n)
        ):
            top_state = self.state_store.get(
                candidate.exchange, candidate.symbol, candidate.interval, "TOP_N_ENTRY"
            )
            if not top_state.active:
                event = self._event(candidate, "TOP_N_ENTRY", "WATCH", previous_score, now)
                if self._state_allows_event(top_state, event, now):
                    events.append(event)
                    self.state_store.set_active(
                        candidate.exchange,
                        candidate.symbol,
                        candidate.interval,
                        "TOP_N_ENTRY",
                        active=True,
                        score=candidate.score,
                        dedupe_key=event.dedupe_key,
                        alerted_at_utc=now,
                    )
        elif candidate.rank is None or candidate.rank > self.config.top_n:
            self.state_store.set_active(
                candidate.exchange,
                candidate.symbol,
                candidate.interval,
                "TOP_N_ENTRY",
                active=False,
                score=candidate.score,
            )

        if (
            previous_score is not None
            and previous_score < self.config.score_threshold
            and candidate.score >= self.config.score_threshold
            and candidate.score - previous_score >= self.config.score_delta_threshold
        ):
            accel_state = self.state_store.get(
                candidate.exchange, candidate.symbol, candidate.interval, "SCORE_ACCELERATION"
            )
            event = self._event(candidate, "SCORE_ACCELERATION", "WATCH", previous_score, now)
            if self._state_allows_event(accel_state, event, now):
                events.append(event)
                self.state_store.set_active(
                    candidate.exchange,
                    candidate.symbol,
                    candidate.interval,
                    "SCORE_ACCELERATION",
                    active=True,
                    score=candidate.score,
                    dedupe_key=event.dedupe_key,
                    alerted_at_utc=now,
                )

        if (
            candidate.component_scores.get("breakout", 0) >= 75
            and candidate.component_scores.get("volume", 0) >= 60
            and candidate.component_scores.get("liquidity", 0) >= 50
        ):
            breakout_state = self.state_store.get(
                candidate.exchange, candidate.symbol, candidate.interval, "BREAKOUT_WATCH"
            )
            if not breakout_state.active:
                event = self._event(candidate, "BREAKOUT_WATCH", "WATCH", previous_score, now)
                if self._state_allows_event(breakout_state, event, now):
                    events.append(event)
                    self.state_store.set_active(
                        candidate.exchange,
                        candidate.symbol,
                        candidate.interval,
                        "BREAKOUT_WATCH",
                        active=True,
                        score=candidate.score,
                        dedupe_key=event.dedupe_key,
                        alerted_at_utc=now,
                    )
        elif candidate.component_scores.get("breakout", 0) < 60:
            self.state_store.set_active(
                candidate.exchange,
                candidate.symbol,
                candidate.interval,
                "BREAKOUT_WATCH",
                active=False,
                score=candidate.score,
            )
        return events

    def _state_allows_event(self, state: AlertState, event: AlertEvent, now: datetime) -> bool:
        if state.last_alerted_at_utc is None:
            return True
        cooldown_elapsed = now - state.last_alerted_at_utc >= timedelta(
            minutes=self.config.cooldown_minutes
        )
        if not cooldown_elapsed:
            return False
        if state.active and state.last_dedupe_key == event.dedupe_key:
            return False
        return True

    def _event(
        self,
        candidate: SignalCandidate,
        event_type: str,
        severity: str,
        previous_score: float | None,
        now: datetime,
        *,
        risk_flags: list[str] | None = None,
    ) -> AlertEvent:
        return AlertEvent(
            alert_event_id=str(uuid4()),
            created_at_utc=now,
            exchange=candidate.exchange,
            symbol=candidate.symbol,
            interval=candidate.interval,
            event_type=event_type,
            severity=severity,
            score=candidate.score,
            previous_score=previous_score,
            confidence=candidate.confidence,
            current_price=candidate.current_price,
            rank=candidate.rank,
            drivers=candidate.drivers,
            risk_flags=risk_flags if risk_flags is not None else candidate.risk_flags,
            invalidation_condition=candidate.invalidation_condition,
            data_timestamp_utc=candidate.data_timestamp_utc,
            data_freshness_seconds=candidate.data_freshness_seconds,
            dedupe_key=make_dedupe_key(candidate, event_type),
            source_run_id=candidate.source_run_id,
        )


def _eligible_for_upside_alert(candidate: SignalCandidate) -> bool:
    if candidate.entry_timing_status in {"falling_knife_suppress", "invalidated"}:
        return False
    if _has_single_extreme_component(candidate):
        return False
    return (
        candidate.is_closed_candle_signal
        and candidate.data_quality_status == "pass"
        and candidate.symbol_health_status != "quarantined"
        and candidate.benchmark_available
        and candidate.confidence != "low"
        and not has_critical_risk(candidate.risk_flags)
    )


def _has_single_extreme_component(candidate: SignalCandidate) -> bool:
    scored_components = [
        value
        for name, value in candidate.component_scores.items()
        if name != "market_regime"
    ]
    if len(scored_components) < 2:
        return False
    ordered = sorted(scored_components, reverse=True)
    constructive_count = sum(1 for value in scored_components if value >= 60)
    return ordered[0] >= 90 and ordered[1] < 60 and constructive_count <= 1
