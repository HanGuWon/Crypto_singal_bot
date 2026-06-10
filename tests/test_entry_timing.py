from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conftest import make_candidate
from crypto_signal_bot.data.models import Candle
from crypto_signal_bot.signals.entry_timing import (
    EntryTimingConfig,
    EntryTimingScorer,
    apply_entry_timing_result,
    validate_entry_timeframe_alignment,
)


def test_entry_timing_bottoming_confirmation_can_confirm_candidate() -> None:
    candidate = make_candidate(symbol="TESTUSDT", interval="5m")

    result = EntryTimingScorer(_fast_stochastic_config()).score(candidate, _bottoming_candles())

    assert result.status == "confirmed_candidate"
    assert result.entry_timing_score > 0
    assert result.research_priority_score >= candidate.score * 0.7
    assert "second_stage_confirmation" in result.reason_codes


def test_entry_timing_stochastic_cross_up_alone_does_not_confirm() -> None:
    candidate = make_candidate(symbol="TESTUSDT", interval="5m")

    result = EntryTimingScorer(_fast_stochastic_config()).score(candidate, _stochastic_only_candles())

    assert "stochastic_confirmation_cross_up" in result.reason_codes
    assert result.status != "confirmed_candidate"


def test_entry_timing_falling_knife_suppresses_candidate() -> None:
    candidate = make_candidate(symbol="TESTUSDT", interval="5m")

    result = EntryTimingScorer(_fast_stochastic_config()).score(candidate, _falling_knife_candles())

    assert result.status == "falling_knife_suppress"
    assert "falling_knife_suppress" in result.risk_flags


def test_entry_timing_stale_data_invalidates() -> None:
    candidate = make_candidate(
        symbol="TESTUSDT",
        interval="5m",
        data_quality_status="warn",
        risk_flags=["stale_data"],
    )

    result = EntryTimingScorer(_fast_stochastic_config()).score(candidate, _bottoming_candles())

    assert result.status == "invalidated"
    assert "entry_timing_data_quality_block" in result.risk_flags


def test_apply_entry_timing_result_extends_candidate_without_replacing_score() -> None:
    candidate = make_candidate(symbol="TESTUSDT", interval="5m", score=82.0)
    result = EntryTimingScorer(_fast_stochastic_config()).score(candidate, _bottoming_candles())

    updated = apply_entry_timing_result(candidate, result)

    assert updated.score == 82.0
    assert updated.entry_timing_status == result.status
    assert updated.entry_timing_score == result.entry_timing_score
    assert updated.research_priority_score == result.research_priority_score


def test_entry_timeframe_alignment_accepts_supported_public_intervals() -> None:
    alignment = validate_entry_timeframe_alignment("5m", ["15m", "30m"])

    assert alignment.status == "pass"
    assert alignment.timeframes == ("5m", "15m", "30m")
    assert alignment.anchor_minutes == 30
    assert "utc_epoch_minute_alignment" in alignment.reason_codes


def test_entry_timeframe_alignment_rejects_unsupported_interval() -> None:
    try:
        validate_entry_timeframe_alignment("5m", ["7m"])
    except ValueError as exc:
        assert "unsupported: 7m" in str(exc)
    else:  # pragma: no cover - keeps the assertion message explicit
        raise AssertionError("Expected unsupported entry timing interval to be rejected.")


def _fast_stochastic_config() -> EntryTimingConfig:
    return EntryTimingConfig(
        stochastic_k_period=3,
        stochastic_k_smoothing=1,
        stochastic_d_period=2,
    )


def _bottoming_candles() -> list[Candle]:
    return [
        _candle(0, open_price=103, high=104, low=100, close=101),
        _candle(1, open_price=101, high=102, low=99, close=100.4),
        _candle(2, open_price=100.4, high=101, low=99.2, close=100.1),
        _candle(3, open_price=100.1, high=100.6, low=99.0, close=100.0),
        _candle(4, open_price=100.0, high=100.4, low=99.0, close=99.95),
        _candle(5, open_price=99.95, high=100.2, low=99.1, close=99.92),
    ]


def _stochastic_only_candles() -> list[Candle]:
    return [
        _candle(0, open_price=100, high=110, low=99, close=105),
        _candle(1, open_price=105, high=115, low=104, close=106),
        _candle(2, open_price=106, high=116, low=105, close=107),
        _candle(3, open_price=107, high=117, low=106, close=108),
        _candle(4, open_price=108, high=118, low=107, close=116),
    ]


def _falling_knife_candles() -> list[Candle]:
    return [
        _candle(0, open_price=105, high=106, low=104, close=105),
        _candle(1, open_price=105, high=105.2, low=101, close=101),
        _candle(2, open_price=101, high=101.2, low=98, close=98),
        _candle(3, open_price=98, high=98.2, low=95, close=95),
        _candle(4, open_price=95, high=95.2, low=92, close=92),
        _candle(5, open_price=92, high=93, low=91, close=91.5),
    ]


def _candle(
    minutes: int,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    is_closed: bool = True,
) -> Candle:
    open_time = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes * 5)
    return Candle(
        exchange="binance",
        symbol="TESTUSDT",
        interval="5m",
        open_time_utc=open_time,
        close_time_utc=open_time + timedelta(minutes=5) - timedelta(milliseconds=1),
        open=open_price,
        high=high,
        low=low,
        close=close,
        base_volume=1000,
        quote_volume=100_000,
        trade_count=100,
        is_closed=is_closed,
    )
