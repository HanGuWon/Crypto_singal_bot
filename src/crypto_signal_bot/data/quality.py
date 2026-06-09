from __future__ import annotations

from datetime import datetime

from crypto_signal_bot.data.models import Candle, DataQualityReport, ensure_utc, utc_now
from crypto_signal_bot.features.indicators import interval_to_minutes


def assess_candles(
    candles: list[Candle],
    interval: str,
    *,
    now: datetime | None = None,
    max_staleness_seconds: int = 1200,
) -> DataQualityReport:
    now_utc = ensure_utc(now or utc_now())
    warnings: list[str] = []
    if not candles:
        return DataQualityReport("fail", ["no_candles"], 0.0, None, None)

    open_times = [candle.open_time_utc for candle in candles]
    if len(open_times) != len(set(open_times)):
        warnings.append("duplicate_candles")

    invalid_ohlc = [
        candle
        for candle in candles
        if candle.low > min(candle.open, candle.close)
        or candle.high < max(candle.open, candle.close)
        or candle.high < candle.low
        or candle.open <= 0
        or candle.close <= 0
    ]
    if invalid_ohlc:
        warnings.append("invalid_ohlc")

    latest = max(candles, key=lambda candle: candle.close_time_utc)
    if not latest.is_closed or latest.close_time_utc > now_utc:
        warnings.append("incomplete_current_candle")

    interval_seconds = interval_to_minutes(interval) * 60
    first = min(open_times)
    last = max(open_times)
    expected = int((last - first).total_seconds() // interval_seconds) + 1
    coverage = min(len(set(open_times)) / max(expected, 1), 1.0)
    if coverage < 0.95:
        warnings.append("missing_candles")

    stale_seconds = (now_utc - latest.close_time_utc).total_seconds()
    if stale_seconds > max_staleness_seconds:
        warnings.append("stale_data")

    hard_failures = {"no_candles", "duplicate_candles", "invalid_ohlc", "incomplete_current_candle"}
    status = "fail" if hard_failures.intersection(warnings) else "pass"
    if status == "pass" and warnings:
        status = "warn"
    return DataQualityReport(status, warnings, coverage, stale_seconds, latest.close_time_utc)
