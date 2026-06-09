from __future__ import annotations

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
