from __future__ import annotations

from crypto_signal_bot.features.indicators import clip_score, robust_z


def robust_score(value: float, sample: list[float], *, cap: float = 3.0) -> float:
    z = robust_z(value, sample, cap=cap)
    return clip_score(50.0 + (z / cap) * 50.0)


def winsorized_component(values: list[float], *, low: float = 0.0, high: float = 100.0) -> float:
    if not values:
        return 50.0
    clipped = [max(low, min(high, value)) for value in values]
    return sum(clipped) / len(clipped)
