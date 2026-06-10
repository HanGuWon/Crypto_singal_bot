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
    assert first.raw_symbol == "ALPHAUSDT"
    assert first.base_asset == "ALPHA"
    assert first.quote_asset == "USDT"
    assert first.data_freshness_seconds == snapshot.data_freshness_seconds
    assert first.data_freshness_seconds is not None


def test_scoring_uses_benchmark_return_for_market_regime() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "ALPHAUSDT"]
    benchmark = [
        candle.__class__(
            **{
                **candle.__dict__,
                "open": candle.close * (1 - index * 0.003) * 1.001,
                "high": candle.close * (1 - index * 0.003) * 1.003,
                "low": candle.close * (1 - index * 0.003) * 0.997,
                "close": candle.close * (1 - index * 0.003),
            }
        )
        for index, candle in enumerate(
            [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "BTCUSDT"]
        )
    ]
    quality = assess_candles(candles, "5m", now=datetime.now(tz=UTC) + timedelta(minutes=1))
    snapshot = build_feature_snapshot(candles, quality=quality, benchmark_candles=benchmark)
    candidate = ScoringEngine().score(snapshot)

    assert (snapshot.values["benchmark_ret_1h"] or 0) < 0
    assert candidate.component_scores["market_regime"] < 55


def test_scoring_flags_failed_quality_as_low_confidence() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "BTCUSDT"]
    quality = assess_candles(candles, "5m", now=datetime.now(tz=UTC) + timedelta(days=2))
    snapshot = build_feature_snapshot(candles, quality=quality)
    candidate = ScoringEngine().score(snapshot)
    assert "stale_data" in candidate.risk_flags
    assert candidate.confidence == "low"


def test_scoring_flags_timestamp_drift_as_critical_risk() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "BTCUSDT"]
    drifted = candles[-1].__class__(
        **{
            **candles[-1].__dict__,
            "close_time_utc": candles[-1].open_time_utc + timedelta(minutes=10),
        }
    )
    drifted_candles = [*candles[:-1], drifted]
    quality = assess_candles(drifted_candles, "5m", now=datetime.now(tz=UTC) + timedelta(minutes=1))
    snapshot = build_feature_snapshot(drifted_candles, quality=quality)
    candidate = ScoringEngine().score(snapshot)

    assert "timestamp_drift" in candidate.risk_flags
    assert candidate.confidence == "low"


def test_scoring_uses_configured_liquidity_threshold() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "BTCUSDT"]
    quality = assess_candles(candles, "5m", now=datetime.now(tz=UTC) + timedelta(minutes=1))
    snapshot = build_feature_snapshot(candles, quality=quality)
    candidate = ScoringEngine(min_quote_volume=1_000_000_000).score(snapshot)
    assert "low_liquidity" in candidate.risk_flags
    assert candidate.confidence == "low"
