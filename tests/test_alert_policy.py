from __future__ import annotations

from conftest import make_candidate
from crypto_signal_bot.alerts.policy import AlertPolicy


def test_threshold_crossing_generates_watch_event() -> None:
    events = AlertPolicy().evaluate([make_candidate()], previous_scores={"BTCUSDT": 70})
    assert any(event.event_type == "SCORE_THRESHOLD_CROSSED" for event in events)


def test_stale_or_low_confidence_candidate_is_suppressed() -> None:
    candidate = make_candidate(confidence="low", risk_flags=["stale_data"], data_quality_status="warn")
    assert AlertPolicy().evaluate([candidate], previous_scores={"BTCUSDT": 70}) == []


def test_critical_risk_suppresses_upside_alert() -> None:
    candidate = make_candidate(risk_flags=["wide_spread"], confidence="medium")
    assert AlertPolicy().evaluate([candidate], previous_scores={"BTCUSDT": 70}) == []
