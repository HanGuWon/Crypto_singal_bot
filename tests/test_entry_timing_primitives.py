from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.data.models import Candle
from crypto_signal_bot.features.bottoming import compute_bottoming_state
from crypto_signal_bot.features.candle_patterns import (
    body_pct,
    close_compression,
    is_bearish,
    is_bullish,
    is_doji_like,
    lower_wick_ratio,
    upper_wick_ratio,
)
from crypto_signal_bot.features.three_tick import ThreeTickConfig, compute_three_tick_state


def test_candle_pattern_primitives() -> None:
    candle = _candle(0, open_price=100, high=110, low=90, close=101)

    assert is_bullish(candle)
    assert not is_bearish(candle)
    assert body_pct(candle) == 0.01
    assert upper_wick_ratio(candle) == 9 / 20
    assert lower_wick_ratio(candle) == 10 / 20
    assert is_doji_like(_candle(1, open_price=100, high=110, low=90, close=101), max_body_to_range=0.06)


def test_close_compression_ignores_incomplete_candles() -> None:
    candles = [
        _candle(0, open_price=100, high=101, low=99, close=100),
        _candle(1, open_price=100, high=101, low=99, close=100.4),
        _candle(2, open_price=100, high=120, low=80, close=110, is_closed=False),
    ]

    assert math.isclose(close_compression(candles) or 0, 0.004)


def test_three_tick_counts_large_transition_but_not_small_transition() -> None:
    candles = [
        _candle(0, open_price=100, high=102, low=99, close=101),
        _candle(1, open_price=101, high=101.2, low=100.5, close=100.9),
        _candle(2, open_price=101, high=101.1, low=99, close=99.5),
        _candle(3, open_price=99.5, high=99.6, low=98.8, close=99.0),
        _candle(4, open_price=99.0, high=99.1, low=98.2, close=98.5),
    ]

    state = compute_three_tick_state(
        candles,
        ThreeTickConfig(large_transition_body_bps=30, falling_knife_drop_pct=0.20),
    )

    assert state.status == "watch"
    assert state.bearish_tick_count == 3
    assert "bullish_to_bearish_transition_not_counted" in state.reason_codes


def test_three_tick_uses_closed_candles_only() -> None:
    candles = [
        _candle(0, open_price=100, high=101, low=99, close=100.5),
        _candle(1, open_price=100.5, high=101, low=99, close=99.5),
        _candle(2, open_price=99.5, high=100, low=98, close=98.7),
        _candle(3, open_price=98.7, high=99, low=97, close=98.0),
        _candle(4, open_price=98.0, high=98.2, low=90, close=90.0, is_closed=False),
    ]

    state = compute_three_tick_state(candles, ThreeTickConfig(falling_knife_drop_pct=0.20))

    assert state.used_closed_candles == 4
    assert state.status != "falling_knife_suppress"


def test_three_tick_falling_knife_suppresses_unconfirmed_decline() -> None:
    candles = [
        _candle(0, open_price=105, high=106, low=104, close=105),
        _candle(1, open_price=105, high=105.2, low=101, close=101),
        _candle(2, open_price=101, high=101.2, low=98, close=98),
        _candle(3, open_price=98, high=98.2, low=95, close=95),
        _candle(4, open_price=95, high=95.2, low=92, close=92),
    ]

    state = compute_three_tick_state(candles, ThreeTickConfig(falling_knife_drop_pct=0.04))

    assert state.status == "falling_knife_suppress"
    assert "falling_knife_suppress" in state.risk_flags


def test_bottoming_confirms_shrinking_compressed_lower_wick_support() -> None:
    candles = [
        _candle(0, open_price=103, high=104, low=100, close=101),
        _candle(1, open_price=101, high=102, low=99, close=100.4),
        _candle(2, open_price=100.4, high=101, low=99.2, close=100.1),
        _candle(3, open_price=100.1, high=100.6, low=99.0, close=100.0),
        _candle(4, open_price=100.0, high=100.4, low=99.0, close=99.95),
        _candle(5, open_price=99.95, high=100.2, low=99.1, close=99.92),
    ]

    state = compute_bottoming_state(candles)

    assert state.status == "confirmed"
    assert state.body_shrinking
    assert state.close_compressed
    assert state.lower_wick_support


def test_bottoming_support_failure_invalidates() -> None:
    candles = [
        _candle(0, open_price=103, high=104, low=100, close=101),
        _candle(1, open_price=101, high=102, low=99, close=100.4),
        _candle(2, open_price=100.4, high=101, low=99.2, close=100.1),
        _candle(3, open_price=100.1, high=100.6, low=99.0, close=100.0),
        _candle(4, open_price=100.0, high=100.4, low=99.0, close=99.95),
        _candle(5, open_price=99.95, high=100.2, low=97.0, close=98.0),
    ]

    state = compute_bottoming_state(candles)

    assert state.status == "invalidated"
    assert "support_failed" in state.risk_flags


def _candle(
    minutes: int,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    is_closed: bool = True,
) -> Candle:
    open_time = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes)
    return Candle(
        exchange="binance",
        symbol="TESTUSDT",
        interval="5m",
        open_time_utc=open_time,
        close_time_utc=open_time + timedelta(minutes=5) - timedelta(milliseconds=1),
        open=open_price,
        high=high,
        low=low,
        close=close,
        base_volume=1000,
        quote_volume=100_000,
        trade_count=100,
        is_closed=is_closed,
    )
