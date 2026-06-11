from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_signal_bot.data.collector import make_mock_candles
from crypto_signal_bot.data.models import OrderBook, PriceLevel
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
    assert first.canonical_asset_id == "ALPHA"
    assert first.canonical_pair_id == "ALPHA/USDT"
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


def test_scoring_flags_missing_candles_as_critical_risk() -> None:
    candles = [
        candle
        for index, candle in enumerate(
            [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "BTCUSDT"]
        )
        if index % 10 != 0
    ]
    quality = assess_candles(candles, "5m", now=datetime.now(tz=UTC) + timedelta(minutes=1))
    snapshot = build_feature_snapshot(candles, quality=quality)

    candidate = ScoringEngine().score(snapshot)

    assert quality.status == "warn"
    assert "missing_candles" in quality.warnings
    assert "missing_candles" in candidate.risk_flags
    assert candidate.confidence == "low"


def test_scoring_does_not_treat_upbit_no_trade_gap_as_missing_candles() -> None:
    candles = [
        candle
        for index, candle in enumerate(
            [c for c in make_mock_candles("upbit", "KRW", "5m", limit=100) if c.symbol == "KRW-BTC"]
        )
        if index not in {15, 30, 45, 60, 75, 90}
    ]
    quality = assess_candles(candles, "5m", now=datetime.now(tz=UTC) + timedelta(minutes=1))
    snapshot = build_feature_snapshot(candles, quality=quality)

    candidate = ScoringEngine().score(snapshot)

    assert quality.status == "warn"
    assert quality.warnings == ["upbit_possible_no_trade_gap"]
    assert "missing_candles" not in candidate.risk_flags


def test_scoring_uses_configured_liquidity_threshold() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "BTCUSDT"]
    quality = assess_candles(candles, "5m", now=datetime.now(tz=UTC) + timedelta(minutes=1))
    snapshot = build_feature_snapshot(candles, quality=quality)
    candidate = ScoringEngine(min_quote_volume=1_000_000_000).score(snapshot)
    assert "low_liquidity" in candidate.risk_flags
    assert candidate.confidence == "low"


def test_scoring_flags_stale_orderbook_as_critical_risk() -> None:
    now = datetime.now(tz=UTC) + timedelta(minutes=1)
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "BTCUSDT"]
    latest = candles[-1].close
    orderbook = OrderBook(
        exchange="binance",
        symbol="BTCUSDT",
        event_time_utc=now - timedelta(minutes=2),
        bids=[PriceLevel(latest * 0.9995, 10.0)],
        asks=[PriceLevel(latest * 1.0005, 10.0)],
    )
    quality = assess_candles(candles, "5m", now=now)
    snapshot = build_feature_snapshot(candles, quality=quality, orderbook=orderbook, now_utc=now)

    candidate = ScoringEngine(max_orderbook_age_seconds=30).score(snapshot)

    assert snapshot.values["orderbook_age_seconds"] == 120.0
    assert "stale_orderbook" in candidate.risk_flags
    assert candidate.confidence == "low"


def test_scoring_flags_future_orderbook_timestamp_drift() -> None:
    now = datetime.now(tz=UTC) + timedelta(minutes=1)
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=100) if c.symbol == "BTCUSDT"]
    latest = candles[-1].close
    orderbook = OrderBook(
        exchange="binance",
        symbol="BTCUSDT",
        event_time_utc=now + timedelta(seconds=5),
        bids=[PriceLevel(latest * 0.9995, 10.0)],
        asks=[PriceLevel(latest * 1.0005, 10.0)],
    )
    quality = assess_candles(candles, "5m", now=now)
    snapshot = build_feature_snapshot(candles, quality=quality, orderbook=orderbook, now_utc=now)

    candidate = ScoringEngine(max_orderbook_age_seconds=30).score(snapshot)

    assert snapshot.values["orderbook_timestamp_drift_seconds"] == 5.0
    assert "orderbook_timestamp_drift" in candidate.risk_flags
    assert candidate.confidence == "low"
