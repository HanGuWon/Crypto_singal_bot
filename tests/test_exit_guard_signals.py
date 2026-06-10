from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_signal_bot.data.models import Candle, DataQualityReport
from crypto_signal_bot.exit_guard.alerts import build_protective_exit_alert_event
from crypto_signal_bot.exit_guard.models import ProtectiveExitSignal
from crypto_signal_bot.exit_guard.signals import (
    TrendBreakExitConfig,
    build_trend_break_exit_signal,
    combine_multi_timeframe_exit_signals,
    compute_trend_break_diagnostics,
)


def test_long_exposure_trend_break_uses_closed_candles_only() -> None:
    candles = _long_break_candles()
    config = _fast_config()

    without_open = compute_trend_break_diagnostics(candles, exposure_side="long", config=config)
    with_open = compute_trend_break_diagnostics(
        [
            *candles,
            _candle(
                len(candles),
                close=50.0,
                open_=90.0,
                high=91.0,
                low=49.0,
                quote_volume=1_000_000.0,
                is_closed=False,
            ),
        ],
        exposure_side="long",
        config=config,
    )

    assert without_open.state in {"EXIT_CONFIRMED", "SEVERE_EXIT_CANDIDATE"}
    assert "swing_level_break" in without_open.drivers
    assert "ema_trend_break_confirmation" in without_open.drivers
    assert with_open.state == without_open.state
    assert with_open.exit_score == without_open.exit_score
    assert with_open.ignored_open_candles == 1
    assert "open_candles_ignored" in with_open.drivers


def test_short_exposure_upside_break_is_close_candidate() -> None:
    diagnostics = compute_trend_break_diagnostics(
        _short_break_candles(),
        exposure_side="short",
        config=_fast_config(),
    )

    assert diagnostics.state in {"EXIT_CONFIRMED", "SEVERE_EXIT_CANDIDATE"}
    assert diagnostics.break_distance_atr is not None
    assert diagnostics.break_distance_atr > 0
    assert "swing_level_break" in diagnostics.drivers
    assert "volume_confirmation" in diagnostics.drivers


def test_data_quality_failure_safety_blocks_exit_guard_signal() -> None:
    quality = DataQualityReport(
        status="fail",
        warnings=["stale_data"],
        coverage_ratio=0.5,
        stale_seconds=999.0,
        latest_close_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )

    signal = build_trend_break_exit_signal(
        _long_break_candles(),
        exposure_side="spot_long",
        quality=quality,
        config=_fast_config(),
        source_run_id="sig-quality-block",
    )
    event = build_protective_exit_alert_event(signal, now=datetime(2026, 1, 1, 3, tzinfo=UTC))

    assert signal.state == "SAFETY_BLOCKED"
    assert signal.data_quality_status == "fail"
    assert "exit_guard_data_quality_block" in signal.risk_flags
    assert "stale_data" in signal.risk_flags
    assert event.event_type == "PROTECTIVE_EXIT_BLOCKED"
    assert event.severity == "WARNING"


def test_insufficient_history_safety_blocks_without_order_intent() -> None:
    signal = build_trend_break_exit_signal(
        _long_break_candles()[:8],
        exposure_side="long",
        config=_fast_config(),
        source_run_id="sig-short-history",
    )

    assert signal.state == "SAFETY_BLOCKED"
    assert signal.exit_score == 0.0
    assert "insufficient_closed_candle_history" in signal.risk_flags


def test_multi_timeframe_confirmation_promotes_primary_warning() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    primary = ProtectiveExitSignal(
        signal_id="primary",
        created_at_utc=now,
        exchange="binance_usdm_futures",
        symbol="BTCUSDT",
        interval="5m",
        state="WARNING",
        exit_score=52.0,
        drivers=["close_below_ema20"],
    )
    confirmation = ProtectiveExitSignal(
        signal_id="confirm",
        created_at_utc=now,
        exchange="binance_usdm_futures",
        symbol="BTCUSDT",
        interval="15m",
        state="EXIT_CANDIDATE",
        exit_score=71.0,
        drivers=["swing_level_break"],
    )

    combined = combine_multi_timeframe_exit_signals(primary, [confirmation])

    assert combined.state == "EXIT_CANDIDATE"
    assert combined.exit_score == 57.0
    assert "mtf_confirmation:15m:EXIT_CANDIDATE" in combined.drivers
    assert combined.signal_id == "primary"


def _fast_config() -> TrendBreakExitConfig:
    return TrendBreakExitConfig(
        min_closed_candles=20,
        swing_lookback=5,
        ema_fast_period=5,
        ema_slow_period=10,
        atr_period=5,
        atr_break_fraction=0.25,
        warning_atr_fraction=0.20,
        volume_z_window=5,
        min_volume_z=0.4,
        severe_adverse_move_pct=0.08,
    )


def _long_break_candles() -> list[Candle]:
    closes = [
        125,
        124,
        123,
        122,
        121,
        120,
        119,
        118,
        117,
        116,
        115,
        114,
        113,
        112,
        111,
        108,
        106,
        104,
        102,
        100,
        99,
        98,
        97,
        96,
        91,
    ]
    return [
        _candle(
            index,
            close=float(close),
            open_=float(close + 1.0),
            high=float(close + 2.0),
            low=float(close - (3.0 if index == len(closes) - 1 else 1.0)),
            quote_volume=10_000.0 + index * 750.0 if index < len(closes) - 1 else 80_000.0,
        )
        for index, close in enumerate(closes)
    ]


def _short_break_candles() -> list[Candle]:
    closes = [
        125,
        123,
        121,
        119,
        117,
        115,
        113,
        111,
        109,
        107,
        105,
        103,
        101,
        100,
        99,
        100,
        101,
        102,
        103,
        104,
        105,
        106,
        107,
        108,
        114,
    ]
    return [
        _candle(
            index,
            close=float(close),
            open_=float(close - 1.0),
            high=float(close + (4.0 if index == len(closes) - 1 else 1.0)),
            low=float(close - 2.0),
            quote_volume=10_000.0 + index * 800.0 if index < len(closes) - 1 else 90_000.0,
        )
        for index, close in enumerate(closes)
    ]


def _candle(
    index: int,
    *,
    close: float,
    open_: float,
    high: float,
    low: float,
    quote_volume: float,
    is_closed: bool = True,
) -> Candle:
    open_time = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=5 * index)
    return Candle(
        exchange="binance",
        symbol="BTCUSDT",
        interval="5m",
        open_time_utc=open_time,
        close_time_utc=open_time + timedelta(minutes=5),
        open=open_,
        high=high,
        low=low,
        close=close,
        base_volume=quote_volume / close,
        quote_volume=quote_volume,
        is_closed=is_closed,
    )
