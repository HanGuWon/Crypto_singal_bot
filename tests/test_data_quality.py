from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_signal_bot.data.models import Candle
from crypto_signal_bot.data.quality import assess_candles


def _candle(
    index: int,
    *,
    now: datetime,
    exchange: str = "binance",
    symbol: str = "BTCUSDT",
) -> Candle:
    open_time = now - timedelta(minutes=10 - index)
    return Candle(
        exchange,
        symbol,
        "1m",
        open_time,
        open_time + timedelta(minutes=1),
        100,
        101,
        99,
        100,
        1,
        100,
        1,
        True,
    )


def test_quality_detects_duplicate_and_invalid_ohlc() -> None:
    now = datetime.now(tz=UTC)
    candles = [_candle(1, now=now), _candle(1, now=now)]
    bad = Candle("binance", "BTCUSDT", "1m", now, now + timedelta(minutes=1), 100, 90, 95, 100, 1, 100)
    report = assess_candles(candles + [bad], "1m", now=now + timedelta(minutes=2))
    assert report.status == "fail"
    assert "duplicate_candles" in report.warnings
    assert "invalid_ohlc" in report.warnings


def test_quality_flags_stale_data() -> None:
    now = datetime.now(tz=UTC)
    report = assess_candles([_candle(1, now=now)], "1m", now=now + timedelta(hours=2))
    assert "stale_data" in report.warnings


def test_upbit_small_internal_gap_is_marked_possible_no_trade_gap() -> None:
    now = datetime.now(tz=UTC)
    candles = [
        _candle(index, now=now, exchange="upbit", symbol="KRW-LOWVOL")
        for index in range(10)
        if index != 4
    ]

    report = assess_candles(candles, "1m", now=now + timedelta(minutes=1))

    assert report.status == "warn"
    assert "upbit_possible_no_trade_gap" in report.warnings
    assert "missing_candles" not in report.warnings
    assert report.missing_candle_count == 1
    assert report.max_gap_intervals == 1


def test_binance_internal_gap_is_marked_missing_candles() -> None:
    now = datetime.now(tz=UTC)
    candles = [_candle(index, now=now) for index in range(10) if index != 4]

    report = assess_candles(candles, "1m", now=now + timedelta(minutes=1))

    assert report.status == "warn"
    assert "missing_candles" in report.warnings
    assert "upbit_possible_no_trade_gap" not in report.warnings
    assert report.missing_candle_count == 1


def test_quality_flags_timestamp_drift() -> None:
    now = datetime.now(tz=UTC)
    open_time = now - timedelta(minutes=5)
    drifted = Candle(
        "binance",
        "BTCUSDT",
        "1m",
        open_time,
        open_time + timedelta(minutes=2),
        100,
        101,
        99,
        100,
        1,
        100,
    )

    report = assess_candles([drifted], "1m", now=now)

    assert report.status == "fail"
    assert "timestamp_drift" in report.warnings
    assert report.timestamp_drift_count == 1
