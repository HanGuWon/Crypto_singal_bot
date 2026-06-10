from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.signals.schemas import SignalCandidate


def make_candidate(**overrides: object) -> SignalCandidate:
    data = {
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "interval": "15m",
        "current_price": 100.0,
        "score": 85.0,
        "component_scores": {
            "trend": 80.0,
            "momentum": 75.0,
            "volume": 70.0,
            "liquidity": 90.0,
            "breakout": 80.0,
            "relative_strength": 65.0,
            "market_regime": 55.0,
        },
        "confidence": "medium",
        "rank": 1,
        "drivers": ["trend_constructive", "volume_expansion", "positive_relative_strength"],
        "risk_flags": [],
        "invalidation_condition": (
            "Research view invalidates if score falls below 60, closes below EMA20, "
            "or data becomes stale."
        ),
        "data_timestamp_utc": datetime.now(tz=UTC).isoformat(),
        "source_run_id": str(uuid4()),
        "is_closed_candle_signal": True,
        "data_quality_status": "pass",
        "data_freshness_seconds": 42.0,
    }
    data.update(overrides)
    return SignalCandidate(**data)


def make_alert(**overrides: object) -> AlertEvent:
    candidate = make_candidate()
    data = {
        "alert_event_id": str(uuid4()),
        "created_at_utc": datetime.now(tz=UTC),
        "exchange": candidate.exchange,
        "symbol": candidate.symbol,
        "interval": candidate.interval,
        "event_type": "SCORE_THRESHOLD_CROSSED",
        "severity": "WATCH",
        "score": candidate.score,
        "previous_score": 50.0,
        "confidence": candidate.confidence,
        "current_price": candidate.current_price,
        "rank": candidate.rank,
        "drivers": candidate.drivers,
        "risk_flags": candidate.risk_flags,
        "invalidation_condition": candidate.invalidation_condition,
        "data_timestamp_utc": candidate.data_timestamp_utc,
        "data_freshness_seconds": candidate.data_freshness_seconds,
        "dedupe_key": "binance:BTCUSDT:15m:SCORE_THRESHOLD_CROSSED:85:test",
        "source_run_id": candidate.source_run_id,
    }
    data.update(overrides)
    return AlertEvent(**data)
