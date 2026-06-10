from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conftest import make_candidate
from crypto_signal_bot.alerts.policy import AlertPolicy, AlertPolicyConfig
from crypto_signal_bot.alerts.state import SQLiteAlertStateStore


def test_hysteresis_prevents_threshold_oscillation_spam() -> None:
    policy = AlertPolicy(AlertPolicyConfig(score_threshold=80, exit_threshold=65))
    first = policy.evaluate([make_candidate(score=81)], previous_scores={"BTCUSDT": 70})
    second = policy.evaluate([make_candidate(score=79)], previous_scores={"BTCUSDT": 81})
    third = policy.evaluate([make_candidate(score=82)], previous_scores={"BTCUSDT": 79})
    assert any(event.event_type == "SCORE_THRESHOLD_CROSSED" for event in first)
    assert second == []
    assert third == []


def test_hysteresis_exits_below_exit_threshold() -> None:
    policy = AlertPolicy(AlertPolicyConfig(score_threshold=80, exit_threshold=65))
    policy.evaluate([make_candidate(score=82)], previous_scores={"BTCUSDT": 70})
    events = policy.evaluate([make_candidate(score=60)], previous_scores={"BTCUSDT": 82})
    assert any(event.event_type == "INVALIDATION" for event in events)


def test_data_quality_invalidation_uses_data_quality_risk_flag() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    policy = AlertPolicy(AlertPolicyConfig(score_threshold=80, exit_threshold=65))
    policy.evaluate([make_candidate(score=82)], previous_scores={"BTCUSDT": 70}, now=now)

    events = policy.evaluate(
        [make_candidate(score=82, data_quality_status="warn", risk_flags=[])],
        previous_scores={"BTCUSDT": 82},
        now=now + timedelta(minutes=1),
    )

    invalidations = [event for event in events if event.event_type == "INVALIDATION"]
    assert invalidations
    assert "data_quality_warning" in invalidations[0].risk_flags
    assert "score_below_exit_threshold" not in invalidations[0].risk_flags


def test_sqlite_alert_state_suppresses_repeated_cli_like_runs(tmp_path) -> None:
    state_path = tmp_path / "alerts.sqlite"
    first_policy = AlertPolicy(
        AlertPolicyConfig(score_threshold=80, exit_threshold=65),
        state_store=SQLiteAlertStateStore(state_path),
    )
    second_policy = AlertPolicy(
        AlertPolicyConfig(score_threshold=80, exit_threshold=65),
        state_store=SQLiteAlertStateStore(state_path),
    )
    assert first_policy.evaluate([make_candidate(score=82)], previous_scores={"BTCUSDT": 70})
    assert second_policy.evaluate([make_candidate(score=82)], previous_scores={"BTCUSDT": 70}) == []


def test_same_dedupe_reentry_allowed_after_exit_and_cooldown() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    policy = AlertPolicy(AlertPolicyConfig(score_threshold=80, exit_threshold=65, cooldown_minutes=60))

    first = policy.evaluate([make_candidate(score=82)], previous_scores={"BTCUSDT": 70}, now=now)
    invalidation = policy.evaluate(
        [make_candidate(score=60)],
        previous_scores={"BTCUSDT": 82},
        now=now + timedelta(minutes=5),
    )
    too_soon = policy.evaluate(
        [make_candidate(score=82)],
        previous_scores={"BTCUSDT": 60},
        now=now + timedelta(minutes=30),
    )
    reentry = policy.evaluate(
        [make_candidate(score=82)],
        previous_scores={"BTCUSDT": 60},
        now=now + timedelta(minutes=66),
    )

    assert any(event.event_type == "SCORE_THRESHOLD_CROSSED" for event in first)
    assert any(event.event_type == "INVALIDATION" for event in invalidation)
    assert not any(event.event_type == "SCORE_THRESHOLD_CROSSED" for event in too_soon)
    assert any(event.event_type == "SCORE_THRESHOLD_CROSSED" for event in reentry)


def test_risk_warning_uses_cooldown_and_risk_hash() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    policy = AlertPolicy(AlertPolicyConfig(score_threshold=80, exit_threshold=65, cooldown_minutes=60))
    policy.evaluate([make_candidate(score=82)], previous_scores={"BTCUSDT": 70}, now=now)

    first_warning = policy.evaluate(
        [make_candidate(score=84, risk_flags=["wide_spread"])],
        previous_scores={"BTCUSDT": 82},
        now=now + timedelta(minutes=1),
    )
    repeated_warning = policy.evaluate(
        [make_candidate(score=84, risk_flags=["wide_spread"])],
        previous_scores={"BTCUSDT": 84},
        now=now + timedelta(minutes=2),
    )
    changed_warning = policy.evaluate(
        [make_candidate(score=84, risk_flags=["wide_spread", "low_liquidity"])],
        previous_scores={"BTCUSDT": 84},
        now=now + timedelta(minutes=62),
    )

    assert any(event.event_type == "RISK_WARNING" for event in first_warning)
    assert repeated_warning == []
    assert any(event.event_type == "RISK_WARNING" for event in changed_warning)
