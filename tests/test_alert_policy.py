from __future__ import annotations

from conftest import make_candidate
from crypto_signal_bot.alerts.policy import AlertPolicy


def test_threshold_crossing_generates_watch_event() -> None:
    candidate = make_candidate(data_freshness_seconds=33.0)
    events = AlertPolicy().evaluate([candidate], previous_scores={"BTCUSDT": 70})
    threshold_events = [event for event in events if event.event_type == "SCORE_THRESHOLD_CROSSED"]
    assert threshold_events
    assert threshold_events[0].data_freshness_seconds == 33.0


def test_stale_or_low_confidence_candidate_is_suppressed() -> None:
    candidate = make_candidate(confidence="low", risk_flags=["stale_data"], data_quality_status="warn")
    assert AlertPolicy().evaluate([candidate], previous_scores={"BTCUSDT": 70}) == []


def test_critical_risk_suppresses_upside_alert() -> None:
    candidate = make_candidate(risk_flags=["wide_spread"], confidence="medium")
    assert AlertPolicy().evaluate([candidate], previous_scores={"BTCUSDT": 70}) == []


def test_quarantined_symbol_suppresses_upside_alert() -> None:
    candidate = make_candidate(
        confidence="medium",
        risk_flags=["symbol_quarantined", "insufficient_history"],
        symbol_health_status="quarantined",
        quarantine_reason="insufficient_history",
        history_bars_available=40,
    )

    assert AlertPolicy().evaluate([candidate], previous_scores={"BTCUSDT": 70}) == []


def test_missing_benchmark_suppresses_upside_alert() -> None:
    candidate = make_candidate(
        confidence="medium",
        risk_flags=["benchmark_unavailable"],
        benchmark_available=False,
    )

    assert AlertPolicy().evaluate([candidate], previous_scores={"BTCUSDT": 70}) == []


def test_missing_orderbook_suppresses_upside_alert() -> None:
    candidate = make_candidate(
        confidence="medium",
        risk_flags=["orderbook_unavailable"],
    )

    assert AlertPolicy().evaluate([candidate], previous_scores={"BTCUSDT": 70}) == []


def test_top_n_entry_requires_alert_score_threshold() -> None:
    candidate = make_candidate(score=70.0, rank=1, confidence="medium")

    events = AlertPolicy().evaluate(
        [candidate],
        previous_scores={"BTCUSDT": 68},
        previous_ranks={"BTCUSDT": 25},
    )

    assert not any(event.event_type == "TOP_N_ENTRY" for event in events)


def test_breakout_watch_requires_component_threshold_crossing() -> None:
    candidate = make_candidate(
        rank=15,
        component_scores={
            "trend": 70.0,
            "momentum": 70.0,
            "volume": 70.0,
            "liquidity": 70.0,
            "breakout": 80.0,
            "relative_strength": 65.0,
            "market_regime": 55.0,
        },
    )
    policy = AlertPolicy()

    fresh_crossing = policy.evaluate(
        [candidate],
        previous_scores={"BTCUSDT": 85.0},
        previous_component_scores={"BTCUSDT": {"breakout": 70.0}},
    )
    already_above = AlertPolicy().evaluate(
        [candidate],
        previous_scores={"BTCUSDT": 85.0},
        previous_component_scores={"BTCUSDT": {"breakout": 80.0}},
    )

    assert any(event.event_type == "BREAKOUT_WATCH" for event in fresh_crossing)
    assert not any(event.event_type == "BREAKOUT_WATCH" for event in already_above)


def test_entry_timing_blocking_status_suppresses_upside_alert() -> None:
    candidate = make_candidate(
        confidence="medium",
        entry_timing_status="falling_knife_suppress",
        entry_risk_flags=["falling_knife_suppress"],
    )

    assert AlertPolicy().evaluate([candidate], previous_scores={"BTCUSDT": 70}) == []


def test_single_extreme_component_suppresses_upside_alert() -> None:
    candidate = make_candidate(
        score=85.0,
        confidence="medium",
        component_scores={
            "trend": 95.0,
            "momentum": 55.0,
            "volume": 50.0,
            "liquidity": 50.0,
            "breakout": 45.0,
            "relative_strength": 50.0,
            "market_regime": 55.0,
        },
    )

    assert AlertPolicy().evaluate([candidate], previous_scores={"BTCUSDT": 70}) == []
