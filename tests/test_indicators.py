from __future__ import annotations

import math

from crypto_signal_bot.features.indicators import (
    atr,
    ema,
    log_return,
    prior_high_breakout_distance,
    rsi,
)


def test_log_return() -> None:
    assert math.isclose(log_return([100, 110, 121], 2) or 0, math.log(121 / 100))


def test_ema_tracks_values() -> None:
    result = ema([10, 12, 14], 2)
    assert result[0] == 10
    assert result[-1] > result[0]


def test_rsi_and_atr_are_bounded() -> None:
    closes = [100 + index for index in range(20)]
    assert 0 <= (rsi(closes, 14) or 0) <= 100
    highs = [close + 1 for close in closes]
    lows = [close - 1 for close in closes]
    assert (atr(highs, lows, closes, 14) or 0) > 0


def test_breakout_uses_prior_high_not_current_high() -> None:
    highs = [10] * 20 + [100]
    assert math.isclose(prior_high_breakout_distance(highs, close=11, lookback=20) or 0, 0.1)
