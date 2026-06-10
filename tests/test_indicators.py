from __future__ import annotations

import math

from crypto_signal_bot.features.indicators import (
    atr,
    ema,
    log_return,
    prior_high_breakout_distance,
    rsi,
    stochastic_cross_down,
    stochastic_cross_up,
    stochastic_kd,
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


def test_stochastic_kd_uses_smoothed_closed_window_values() -> None:
    highs = [10, 11, 12, 13]
    lows = [0, 1, 2, 3]
    closes = [5, 9, 11, 12]

    k_values, d_values = stochastic_kd(
        highs,
        lows,
        closes,
        k_period=3,
        k_smoothing=1,
        d_period=2,
    )

    assert len(k_values) == 2
    assert len(d_values) == 1
    assert math.isclose(k_values[-1], 100 * (12 - 1) / (13 - 1))
    assert math.isclose(d_values[-1], sum(k_values) / 2)


def test_stochastic_flat_range_returns_neutral_value() -> None:
    k_values, d_values = stochastic_kd(
        [10, 10, 10],
        [10, 10, 10],
        [10, 10, 10],
        k_period=3,
        k_smoothing=1,
        d_period=1,
    )

    assert k_values == [50.0]
    assert d_values == [50.0]


def test_stochastic_cross_helpers() -> None:
    assert stochastic_cross_up([20, 35], [30, 32])
    assert not stochastic_cross_up([35], [32])
    assert stochastic_cross_down([45, 30], [35, 32])
