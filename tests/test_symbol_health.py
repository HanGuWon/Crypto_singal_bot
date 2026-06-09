from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.data.collector import make_mock_candles
from crypto_signal_bot.data.models import SymbolHealth
from crypto_signal_bot.data.quality import assess_candles
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.data.symbol_health import assess_symbol_health


def test_newly_listed_symbol_is_quarantined_until_min_history() -> None:
    candles = _symbol_candles(limit=40)
    quality = assess_candles(candles, "5m", now=_after_latest(candles))

    health = assess_symbol_health(
        exchange="binance",
        symbol="BTCUSDT",
        interval="5m",
        candles=candles,
        quality=quality,
        min_history_bars=80,
    )

    assert health.status == "quarantined"
    assert health.quarantine_reason == "insufficient_history"
    assert health.history_bars_available == 40
    assert health.quarantine_until_utc is None


def test_stale_symbol_is_quarantined_temporarily() -> None:
    candles = _symbol_candles(limit=100)
    quality = assess_candles(candles, "5m", now=_after_latest(candles) + timedelta(days=1))

    health = assess_symbol_health(
        exchange="binance",
        symbol="BTCUSDT",
        interval="5m",
        candles=candles,
        quality=quality,
        min_history_bars=80,
        quarantine_minutes=30,
    )

    assert health.status == "quarantined"
    assert health.quarantine_reason == "stale_data"
    assert health.quarantine_until_utc is not None


def test_warning_market_status_is_quarantined_without_candle_fetch() -> None:
    quality = assess_candles([], "5m")

    health = assess_symbol_health(
        exchange="upbit",
        symbol="KRW-WARN",
        interval="5m",
        candles=[],
        quality=quality,
        market_status="WARNING",
    )

    assert health.status == "quarantined"
    assert health.quarantine_reason == "market_status_WARNING"
    assert health.quarantine_until_utc is None


def test_malformed_candle_quarantines_symbol() -> None:
    candles = _symbol_candles(limit=100)
    candles[-1] = replace(candles[-1], high=candles[-1].close * 0.9)
    quality = assess_candles(candles, "5m", now=_after_latest(candles))

    health = assess_symbol_health(
        exchange="binance",
        symbol="BTCUSDT",
        interval="5m",
        candles=candles,
        quality=quality,
        min_history_bars=80,
    )

    assert "invalid_ohlc" in quality.warnings
    assert health.status == "quarantined"
    assert health.quarantine_reason == "invalid_ohlc"


def test_quarantine_expiry_allows_recovery() -> None:
    candles = _symbol_candles(limit=100)
    now = _after_latest(candles)
    previous = SymbolHealth(
        exchange="binance",
        symbol="BTCUSDT",
        interval="5m",
        status="quarantined",
        first_seen_utc=now - timedelta(days=2),
        last_seen_utc=now - timedelta(days=1),
        last_good_candle_utc=None,
        history_bars_available=100,
        quarantine_reason="stale_data",
        quarantine_until_utc=now - timedelta(minutes=1),
        benchmark_available=True,
    )
    quality = assess_candles(candles, "5m", now=now)

    health = assess_symbol_health(
        exchange="binance",
        symbol="BTCUSDT",
        interval="5m",
        candles=candles,
        quality=quality,
        previous=previous,
        now=now,
        min_history_bars=80,
    )

    assert health.status == "healthy"
    assert health.quarantine_reason is None


def test_symbol_health_persists_to_sqlite(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "health.sqlite")
    candles = _symbol_candles(limit=100)
    quality = assess_candles(candles, "5m", now=_after_latest(candles))
    health = assess_symbol_health(
        exchange="binance",
        symbol="BTCUSDT",
        interval="5m",
        candles=candles,
        quality=quality,
        min_history_bars=80,
    )

    store.upsert_symbol_health(health)

    loaded = store.get_symbol_health("binance", "BTCUSDT", "5m")
    assert loaded is not None
    assert loaded.status == "healthy"
    assert loaded.history_bars_available == 100
    assert loaded.benchmark_available is True


def _symbol_candles(limit: int):
    return [
        candle
        for candle in make_mock_candles("binance", "USDT", "5m", limit=limit)
        if candle.symbol == "BTCUSDT"
    ]


def _after_latest(candles) -> datetime:  # type: ignore[no-untyped-def]
    return max(candle.close_time_utc for candle in candles).astimezone(UTC) + timedelta(seconds=1)
