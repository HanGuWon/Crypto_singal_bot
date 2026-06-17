from __future__ import annotations

from datetime import datetime

from crypto_signal_bot.data.models import Candle, DataQualityReport, ensure_utc, utc_now
from crypto_signal_bot.features.indicators import interval_to_minutes

UPBIT_NO_TRADE_GAP_COVERAGE_FLOOR = 0.80
UPBIT_NO_TRADE_GAP_MAX_INTERVALS = 3
TIMESTAMP_DRIFT_TOLERANCE_SECONDS = 1.0


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
        return DataQualityReport(
            "fail",
            ["no_candles"],
            0.0,
            None,
            None,
            gap_classification="unavailable",
            gap_policy_reason="no candles supplied",
        )

    open_times = [candle.open_time_utc for candle in candles]
    if len(open_times) != len(set(open_times)):
        warnings.append("duplicate_candles")
    ordered_candles = sorted(candles, key=lambda candle: candle.open_time_utc)
    if any(
        current.open_time_utc < previous.close_time_utc
        for previous, current in zip(ordered_candles, ordered_candles[1:], strict=False)
    ):
        warnings.append("overlapping_candles")

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
    timestamp_drift_count = _timestamp_drift_count(candles, interval_seconds)
    if timestamp_drift_count:
        warnings.append("timestamp_drift")
    first = min(open_times)
    last = max(open_times)
    expected = int((last - first).total_seconds() // interval_seconds) + 1
    unique_open_times = sorted(set(open_times))
    missing_candle_count, max_gap_intervals = _gap_counts(unique_open_times, interval_seconds)
    coverage = min(len(unique_open_times) / max(expected, 1), 1.0)
    gap_classification = "complete"
    gap_policy_reason: str | None = None
    if coverage < 0.95:
        gap_classification, gap_policy_reason = _classify_gap(
            candles,
            coverage=coverage,
            max_gap_intervals=max_gap_intervals,
        )
        warnings.append(gap_classification)

    stale_seconds = (now_utc - latest.close_time_utc).total_seconds()
    if stale_seconds > max_staleness_seconds:
        warnings.append("stale_data")

    hard_failures = {
        "no_candles",
        "duplicate_candles",
        "overlapping_candles",
        "invalid_ohlc",
        "incomplete_current_candle",
        "timestamp_drift",
    }
    status = "fail" if hard_failures.intersection(warnings) else "pass"
    if status == "pass" and warnings:
        status = "warn"
    return DataQualityReport(
        status,
        warnings,
        coverage,
        stale_seconds,
        latest.close_time_utc,
        missing_candle_count,
        max_gap_intervals,
        timestamp_drift_count,
        gap_classification,
        gap_policy_reason,
    )


def _timestamp_drift_count(candles: list[Candle], interval_seconds: int) -> int:
    drifted = 0
    for candle in candles:
        duration_seconds = (candle.close_time_utc - candle.open_time_utc).total_seconds()
        if abs(duration_seconds - interval_seconds) > TIMESTAMP_DRIFT_TOLERANCE_SECONDS:
            drifted += 1
    return drifted


def _gap_counts(open_times: list[datetime], interval_seconds: int) -> tuple[int, int]:
    missing = 0
    max_gap = 0
    for previous, current in zip(open_times, open_times[1:], strict=False):
        intervals_between = int((current - previous).total_seconds() // interval_seconds)
        missing_between = max(0, intervals_between - 1)
        missing += missing_between
        max_gap = max(max_gap, missing_between)
    return missing, max_gap


def _classify_gap(
    candles: list[Candle],
    *,
    coverage: float,
    max_gap_intervals: int,
) -> tuple[str, str]:
    exchanges = {candle.exchange for candle in candles}
    if (
        exchanges == {"upbit"}
        and coverage >= UPBIT_NO_TRADE_GAP_COVERAGE_FLOOR
        and max_gap_intervals <= UPBIT_NO_TRADE_GAP_MAX_INTERVALS
    ):
        return (
            "upbit_possible_no_trade_gap",
            (
                "Upbit may omit minute candles for intervals with no trades; small internal gaps "
                "are tracked as warning-level observation gaps instead of hard missing-candle risk."
            ),
        )
    return (
        "missing_candles",
        "Observed candle coverage or max gap exceeded the exchange-specific missing-candle policy.",
    )
