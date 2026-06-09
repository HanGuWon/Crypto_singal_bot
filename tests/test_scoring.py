from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_signal_bot.data.collector import make_mock_candles
from crypto_signal_bot.data.quality import assess_candles
from crypto_signal_bot.features.feature_builder import build_feature_snapshot
from crypto_signal_bot.signals.scoring import ScoringEngine


def test_scoring_is_deterministic_and_bounded() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "ALPHAUSDT"]
    quality = assess_candles(candles, "5m", now=datetime.now(tz=UTC) + timedelta(minutes=1))
    snapshot = build_feature_snapshot(candles, quality=quality)
    engine = ScoringEngine()
    first = engine.score(snapshot, source_run_id="run")
    second = engine.score(snapshot, source_run_id="run")
    assert first.score == second.score
    assert 0 <= first.score <= 100
    assert first.component_scores
    assert first.drivers


def test_scoring_flags_failed_quality_as_low_confidence() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "BTCUSDT"]
    quality = assess_candles(candles, "5m", now=datetime.now(tz=UTC) + timedelta(days=2))
    snapshot = build_feature_snapshot(candles, quality=quality)
    candidate = ScoringEngine().score(snapshot)
    assert "stale_data" in candidate.risk_flags
    assert candidate.confidence == "low"


def test_scoring_uses_configured_liquidity_threshold() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "BTCUSDT"]
    quality = assess_candles(candles, "5m", now=datetime.now(tz=UTC) + timedelta(minutes=1))
    snapshot = build_feature_snapshot(candles, quality=quality)
    candidate = ScoringEngine(min_quote_volume=1_000_000_000).score(snapshot)
    assert "low_liquidity" in candidate.risk_flags
    assert candidate.confidence == "low"
