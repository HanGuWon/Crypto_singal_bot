from __future__ import annotations

from crypto_signal_bot.data.models import Candle


def range_size(candle: Candle) -> float:
    return max(candle.high - candle.low, 0.0)


def body_size(candle: Candle) -> float:
    return abs(candle.close - candle.open)


def body_pct(candle: Candle) -> float:
    if candle.open <= 0:
        return 0.0
    return body_size(candle) / candle.open


def range_pct(candle: Candle) -> float:
    if candle.open <= 0:
        return 0.0
    return range_size(candle) / candle.open


def upper_wick_ratio(candle: Candle) -> float:
    total_range = range_size(candle)
    if total_range <= 0:
        return 0.0
    return max(candle.high - max(candle.open, candle.close), 0.0) / total_range


def lower_wick_ratio(candle: Candle) -> float:
    total_range = range_size(candle)
    if total_range <= 0:
        return 0.0
    return max(min(candle.open, candle.close) - candle.low, 0.0) / total_range


def is_bullish(candle: Candle) -> bool:
    return candle.close > candle.open


def is_bearish(candle: Candle) -> bool:
    return candle.close < candle.open


def is_doji_like(candle: Candle, *, max_body_to_range: float = 0.15) -> bool:
    total_range = range_size(candle)
    if total_range <= 0:
        return True
    return body_size(candle) / total_range <= max_body_to_range


def is_large_candle(candle: Candle, *, min_body_bps: float = 35.0) -> bool:
    return body_pct(candle) * 10000 >= min_body_bps


def close_compression(candles: list[Candle]) -> float | None:
    closes = [candle.close for candle in candles if candle.is_closed and candle.close > 0]
    if len(closes) < 2:
        return None
    low = min(closes)
    if low <= 0:
        return None
    return max(closes) / low - 1
