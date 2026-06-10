from __future__ import annotations

import math
from statistics import median


def interval_to_minutes(interval: str) -> int:
    if interval.endswith("m"):
        return int(interval[:-1])
    if interval.endswith("h"):
        return int(interval[:-1]) * 60
    if interval.endswith("d"):
        return int(interval[:-1]) * 1440
    raise ValueError(f"Unsupported interval: {interval}")


def log_return(values: list[float], bars: int) -> float | None:
    if bars <= 0 or len(values) <= bars:
        return None
    current = values[-1]
    prior = values[-1 - bars]
    if current <= 0 or prior <= 0:
        return None
    return math.log(current / prior)


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1 - alpha) * result[-1])
    return result


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [abs(min(delta, 0.0)) for delta in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:], strict=False):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def true_ranges(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    if not highs or not lows or not closes:
        return []
    ranges = [highs[0] - lows[0]]
    for index in range(1, min(len(highs), len(lows), len(closes))):
        ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    return ranges


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    ranges = true_ranges(highs, lows, closes)
    if len(ranges) < period:
        return None
    value = sum(ranges[:period]) / period
    for item in ranges[period:]:
        value = (value * (period - 1) + item) / period
    return value


def realized_volatility(values: list[float], period: int = 20) -> float | None:
    if len(values) <= period:
        return None
    returns = []
    for index in range(len(values) - period, len(values)):
        previous = values[index - 1]
        current = values[index]
        if previous <= 0 or current <= 0:
            return None
        returns.append(math.log(current / previous))
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / len(returns)
    return math.sqrt(variance)


def prior_high_breakout_distance(highs: list[float], close: float, lookback: int = 20) -> float | None:
    if len(highs) <= lookback:
        return None
    prior_high = max(highs[-lookback - 1 : -1])
    if prior_high <= 0:
        return None
    return close / prior_high - 1


def rolling_zscore(values: list[float], window: int = 48) -> float | None:
    if len(values) <= window:
        return None
    sample = values[-window - 1 : -1]
    mean = sum(sample) / len(sample)
    variance = sum((item - mean) ** 2 for item in sample) / len(sample)
    std = math.sqrt(variance)
    if std <= 1e-12:
        return 0.0
    return (values[-1] - mean) / std


def robust_z(value: float, sample: list[float], cap: float = 3.0) -> float:
    if not sample:
        return 0.0
    med = median(sample)
    deviations = [abs(item - med) for item in sample]
    mad = median(deviations)
    if mad <= 1e-12:
        return 0.0
    z = 0.6745 * (value - med) / mad
    return max(-cap, min(cap, z))


def winsorize(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def score_from_centered_value(value: float, scale: float, cap: float = 3.0) -> float:
    if scale <= 0:
        return 50.0
    z = max(-cap, min(cap, value / scale))
    return max(0.0, min(100.0, 50.0 + (z / cap) * 50.0))


def clip_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def stochastic_kd(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    k_period: int = 14,
    k_smoothing: int = 3,
    d_period: int = 3,
) -> tuple[list[float], list[float]]:
    limit = min(len(highs), len(lows), len(closes))
    if limit < k_period or k_period <= 0 or k_smoothing <= 0 or d_period <= 0:
        return [], []
    raw_k: list[float] = []
    for index in range(k_period - 1, limit):
        high = max(highs[index - k_period + 1 : index + 1])
        low = min(lows[index - k_period + 1 : index + 1])
        if high <= low:
            raw_k.append(50.0)
        else:
            raw_k.append(100 * (closes[index] - low) / (high - low))
    smooth_k = _moving_average(raw_k, k_smoothing)
    smooth_d = _moving_average(smooth_k, d_period)
    return smooth_k, smooth_d


def stochastic_cross_up(k_values: list[float], d_values: list[float]) -> bool:
    if len(k_values) < 2 or len(d_values) < 2:
        return False
    return k_values[-2] <= d_values[-2] and k_values[-1] > d_values[-1]


def stochastic_cross_down(k_values: list[float], d_values: list[float]) -> bool:
    if len(k_values) < 2 or len(d_values) < 2:
        return False
    return k_values[-2] >= d_values[-2] and k_values[-1] < d_values[-1]


def _moving_average(values: list[float], period: int) -> list[float]:
    if period <= 0:
        return []
    if len(values) < period:
        return []
    return [
        sum(values[index - period + 1 : index + 1]) / period
        for index in range(period - 1, len(values))
    ]
