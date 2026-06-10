from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_signal_bot.data.models import Candle, DataQualityReport, OrderBook, ensure_utc
from crypto_signal_bot.features.indicators import (
    atr,
    ema,
    interval_to_minutes,
    log_return,
    prior_high_breakout_distance,
    realized_volatility,
    rolling_zscore,
    rsi,
)


@dataclass(frozen=True)
class FeatureSnapshot:
    exchange: str
    symbol: str
    interval: str
    current_price: float
    data_timestamp_utc: str
    data_freshness_seconds: float | None
    is_closed_candle_signal: bool
    data_quality_status: str
    data_quality_warnings: list[str]
    values: dict[str, float | None] = field(default_factory=dict)


def build_feature_snapshot(
    candles: list[Candle],
    *,
    quality: DataQualityReport,
    benchmark_candles: list[Candle] | None = None,
    orderbook: OrderBook | None = None,
    now_utc: datetime | None = None,
) -> FeatureSnapshot:
    closed = [candle for candle in candles if candle.is_closed]
    if not closed:
        raise ValueError("Cannot build features without closed candles.")
    latest = closed[-1]
    closes = [candle.close for candle in closed]
    highs = [candle.high for candle in closed]
    lows = [candle.low for candle in closed]
    quote_volumes = [candle.quote_volume or 0.0 for candle in closed]
    minutes = interval_to_minutes(latest.interval)

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    slope_bars = min(5, max(len(ema20) - 1, 1))
    ema20_slope = None
    if len(ema20) > slope_bars and ema20[-1] > 0 and ema20[-1 - slope_bars] > 0:
        ema20_slope = math.log(ema20[-1] / ema20[-1 - slope_bars]) / slope_bars

    def bars_for(horizon_minutes: int) -> int:
        return max(1, horizon_minutes // minutes)

    ret_15m = log_return(closes, bars_for(15))
    ret_1h = log_return(closes, bars_for(60))
    ret_4h = log_return(closes, bars_for(240))
    benchmark_ret_1h = None
    if benchmark_candles:
        benchmark_ret_1h = log_return([candle.close for candle in benchmark_candles if candle.is_closed], bars_for(60))
    relative_strength_1h = None
    if ret_1h is not None and benchmark_ret_1h is not None:
        relative_strength_1h = ret_1h - benchmark_ret_1h

    latest_range = latest.high - latest.low
    upper_wick_ratio = None
    if latest_range > 0:
        upper_wick_ratio = (latest.high - max(latest.open, latest.close)) / latest_range

    spread_bps = orderbook.spread_bps if orderbook else None
    orderbook_age_seconds, orderbook_timestamp_drift_seconds = _orderbook_freshness(
        orderbook,
        observed_at=ensure_utc(now_utc or datetime.now(tz=UTC)),
    )
    atr_value = atr(highs, lows, closes, 14)

    values: dict[str, float | None] = {
        "ret_15m": ret_15m,
        "ret_1h": ret_1h,
        "ret_4h": ret_4h,
        "ema20": ema20[-1] if ema20 else None,
        "ema50": ema50[-1] if ema50 else None,
        "ema20_slope": ema20_slope,
        "price_vs_ema20": latest.close / ema20[-1] - 1 if ema20 and ema20[-1] > 0 else None,
        "price_vs_ema50": latest.close / ema50[-1] - 1 if ema50 and ema50[-1] > 0 else None,
        "breakout_distance_20": prior_high_breakout_distance(highs, latest.close, 20),
        "rsi_14": rsi(closes, 14),
        "realized_volatility_20": realized_volatility(closes, 20),
        "atr_pct_14": atr_value / latest.close if atr_value is not None and latest.close > 0 else None,
        "quote_volume": latest.quote_volume,
        "quote_volume_z_48": rolling_zscore(quote_volumes, 48),
        "volume_acceleration": _volume_acceleration(quote_volumes),
        "benchmark_ret_1h": benchmark_ret_1h,
        "relative_strength_1h": relative_strength_1h,
        "spread_bps": spread_bps,
        "orderbook_age_seconds": orderbook_age_seconds,
        "orderbook_timestamp_drift_seconds": orderbook_timestamp_drift_seconds,
        "upper_wick_ratio": upper_wick_ratio,
    }
    return FeatureSnapshot(
        exchange=latest.exchange,
        symbol=latest.symbol,
        interval=latest.interval,
        current_price=latest.close,
        data_timestamp_utc=latest.close_time_utc.isoformat(),
        data_freshness_seconds=quality.stale_seconds,
        is_closed_candle_signal=latest.is_closed,
        data_quality_status=quality.status,
        data_quality_warnings=quality.warnings,
        values=values,
    )


def _volume_acceleration(quote_volumes: list[float]) -> float | None:
    if len(quote_volumes) < 24:
        return None
    short_window = min(6, len(quote_volumes) // 4)
    long_window = min(48, len(quote_volumes) - short_window)
    short_sum = sum(quote_volumes[-short_window:])
    long_avg = sum(quote_volumes[-long_window - short_window : -short_window]) / long_window
    expected = max(long_avg * short_window, 1e-12)
    return math.log((short_sum + 1e-12) / expected)


def _orderbook_freshness(
    orderbook: OrderBook | None,
    *,
    observed_at: datetime,
) -> tuple[float | None, float | None]:
    if orderbook is None:
        return None, None
    age_seconds = (observed_at - orderbook.event_time_utc).total_seconds()
    timestamp_drift_seconds = abs(age_seconds) if age_seconds < 0 else None
    return age_seconds, timestamp_drift_seconds
