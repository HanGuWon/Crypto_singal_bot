from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_signal_bot.data.models import Candle
from crypto_signal_bot.data.quality import assess_candles


def _candle(index: int, *, now: datetime) -> Candle:
    open_time = now - timedelta(minutes=10 - index)
    return Candle(
        "binance",
        "BTCUSDT",
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
