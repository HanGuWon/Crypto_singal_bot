from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from crypto_signal_bot.data.models import Candle, DataQualityReport, SymbolHealth, ensure_utc, utc_now

HEALTHY = "healthy"
WATCH = "watch"
QUARANTINED = "quarantined"

DATA_QUALITY_QUARANTINE_WARNINGS = {
    "duplicate_candles",
    "invalid_ohlc",
    "incomplete_current_candle",
    "timestamp_drift",
    "missing_candles",
    "stale_data",
}

DATA_QUALITY_OBSERVATION_WARNINGS = {
    "upbit_possible_no_trade_gap",
}


def assess_symbol_health(
    *,
    exchange: str,
    symbol: str,
    interval: str,
    candles: list[Candle],
    quality: DataQualityReport,
    market_status: str = "TRADING",
    benchmark_available: bool = True,
    previous: SymbolHealth | None = None,
    now: datetime | None = None,
    min_history_bars: int = 80,
    quarantine_minutes: int = 120,
) -> SymbolHealth:
    now_utc = ensure_utc(now or utc_now())
    first_seen = previous.first_seen_utc if previous is not None else now_utc
    closed = [candle for candle in candles if candle.is_closed]
    last_good = (
        quality.latest_close_time_utc
        if quality.status == "pass" or set(quality.warnings).issubset(DATA_QUALITY_OBSERVATION_WARNINGS)
        else None
    )
    if last_good is None and previous is not None:
        last_good = previous.last_good_candle_utc

    active_previous = _active_previous_quarantine(previous, now_utc)
    reason = _quarantine_reason(
        quality=quality,
        market_status=market_status,
        history_bars_available=len(closed),
        min_history_bars=min_history_bars,
    )
    if reason is None and active_previous is not None:
        return replace(
            active_previous,
            first_seen_utc=first_seen,
            last_seen_utc=now_utc,
            last_good_candle_utc=last_good,
            history_bars_available=len(closed),
            benchmark_available=benchmark_available,
        )
    if reason is not None:
        return SymbolHealth(
            exchange=exchange,
            symbol=symbol,
            interval=interval,
            status=QUARANTINED,
            first_seen_utc=first_seen,
            last_seen_utc=now_utc,
            last_good_candle_utc=last_good,
            history_bars_available=len(closed),
            quarantine_reason=reason,
            quarantine_until_utc=_quarantine_until(reason, now_utc, quarantine_minutes),
            benchmark_available=benchmark_available,
        )
    return SymbolHealth(
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        status=HEALTHY if benchmark_available else WATCH,
        first_seen_utc=first_seen,
        last_seen_utc=now_utc,
        last_good_candle_utc=last_good,
        history_bars_available=len(closed),
        quarantine_reason=None,
        quarantine_until_utc=None,
        benchmark_available=benchmark_available,
    )


def _active_previous_quarantine(previous: SymbolHealth | None, now: datetime) -> SymbolHealth | None:
    if previous is None or previous.status != QUARANTINED:
        return None
    if previous.quarantine_until_utc is None:
        return previous
    return previous if previous.quarantine_until_utc > now else None


def _quarantine_reason(
    *,
    quality: DataQualityReport,
    market_status: str,
    history_bars_available: int,
    min_history_bars: int,
) -> str | None:
    if market_status != "TRADING":
        return f"market_status_{market_status}"
    for warning in quality.warnings:
        if warning in DATA_QUALITY_QUARANTINE_WARNINGS:
            return warning
    if quality.status == "fail":
        return "failed_data_quality"
    if history_bars_available < min_history_bars:
        return "insufficient_history"
    return None


def _quarantine_until(reason: str, now: datetime, quarantine_minutes: int) -> datetime | None:
    if reason.startswith("market_status_") or reason == "insufficient_history":
        return None
    return now + timedelta(minutes=quarantine_minutes)
