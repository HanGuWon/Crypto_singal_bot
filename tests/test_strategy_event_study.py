from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.backtest.strategy_event_study import (
    StrategyEventStudyConfig,
    generate_strategy_signal_indices,
    strategy_event_study,
)
from crypto_signal_bot.data.models import Candle


def test_strategy_event_study_has_diagnostic_flags_and_horizons() -> None:
    candles_by_symbol = _strategy_universe()

    result = strategy_event_study(
        candles_by_symbol,
        benchmark_symbol="BTCUSDT",
        config=StrategyEventStudyConfig(horizons=(1, 3), min_history_bars=20),
    )

    assert result["strategy_event_study_only"] is True
    assert result["next_open_entry_enforced"] is True
    assert result["notification_logic_excluded"] is True
    assert result["horizons"] == [1, 3]
    assert result["signal_counts"]["confirmed_entry_timing"] >= 1
    assert result["variant_summaries"]["confirmed_entry_timing"]["1"]["trades"] >= 1
    assert result["cost_model"]["applied_to_variant_summaries"] is True


def test_strategy_event_study_reports_cost_sensitivity() -> None:
    result = strategy_event_study(
        _strategy_universe(),
        benchmark_symbol="BTCUSDT",
        config=StrategyEventStudyConfig(
            horizons=(1,),
            min_history_bars=20,
            fee_bps=20.0,
            spread_bps=10.0,
            slippage_bps=10.0,
        ),
    )

    sensitivity = result["cost_sensitivity"]["scenarios"]
    zero_summary = sensitivity["zero_cost"]["variant_summaries"]["confirmed_entry_timing"]["1"]
    configured_summary = sensitivity["configured_cost"]["variant_summaries"]["confirmed_entry_timing"]["1"]
    double_summary = sensitivity["double_configured_cost"]["variant_summaries"]["confirmed_entry_timing"]["1"]

    assert result["cost_model"]["round_trip_cost_bps"] == 40.0
    assert configured_summary["trades"] == zero_summary["trades"]
    assert configured_summary["average_return"] < zero_summary["average_return"]
    assert double_summary["average_return"] < configured_summary["average_return"]


def test_strategy_signals_use_closed_candles_only() -> None:
    candles = _strategy_candles("TESTUSDT")
    candles[35] = _replace_candle(candles[35], is_closed=False)

    indices = generate_strategy_signal_indices(
        candles,
        variant="bottoming_confirmed",
        config=StrategyEventStudyConfig(horizons=(1,), min_history_bars=20),
    )

    assert 35 not in indices


def test_strategy_records_enter_on_next_candle_open() -> None:
    result = strategy_event_study(
        {"TESTUSDT": _strategy_candles("TESTUSDT")},
        config=StrategyEventStudyConfig(horizons=(1,), min_history_bars=20),
    )

    sample = result["sample_signals"]["confirmed_entry_timing"][0]
    assert sample["entry_index"] == sample["signal_index"] + 1
    assert sample["entry_time_utc"] > sample["signal_time_utc"]


def test_strategy_benchmark_windows_are_point_in_time() -> None:
    result = strategy_event_study(
        _strategy_universe(),
        benchmark_symbol="BTCUSDT",
        config=StrategyEventStudyConfig(horizons=(1, 3), min_history_bars=20),
    )

    diagnostics = result["benchmark_diagnostics"]
    assert diagnostics["benchmark_symbol"] == "BTCUSDT"
    assert diagnostics["windows_aligned_point_in_time"] is True
    assert "1" in diagnostics["benchmark_return"]
    assert "3" in diagnostics["universe_median_return"]


def test_strategy_output_avoids_forbidden_recommendation_language() -> None:
    text = json.dumps(
        strategy_event_study(
            _strategy_universe(),
            benchmark_symbol="BTCUSDT",
            config=StrategyEventStudyConfig(horizons=(1,), min_history_bars=20),
        )
    ).lower()

    for forbidden in ["buy", "sell", "profit", "guaranteed"]:
        assert forbidden not in text


def _strategy_universe() -> dict[str, list[Candle]]:
    return {
        "BTCUSDT": _strategy_candles("BTCUSDT", base_price=100.0),
        "ETHUSDT": _strategy_candles("ETHUSDT", base_price=80.0),
        "ALPHAUSDT": _strategy_candles("ALPHAUSDT", base_price=50.0),
    }


def _strategy_candles(symbol: str, *, base_price: float = 100.0) -> list[Candle]:
    candles: list[Candle] = []
    for index in range(30):
        close = base_price + index * 0.03
        candles.append(
            _candle(
                index,
                symbol=symbol,
                open_price=close + 0.04,
                high=close + 0.35,
                low=close - 0.35,
                close=close,
            )
        )
    pattern = [
        (103.0, 104.0, 100.0, 101.0),
        (101.0, 102.0, 99.0, 100.4),
        (100.4, 101.0, 99.2, 100.1),
        (100.1, 100.6, 99.0, 100.0),
        (100.0, 100.4, 99.0, 99.95),
        (99.95, 100.2, 99.1, 99.92),
    ]
    scale = base_price / 100.0
    for offset, values in enumerate(pattern, start=30):
        candles.append(
            _candle(
                offset,
                symbol=symbol,
                open_price=values[0] * scale,
                high=values[1] * scale,
                low=values[2] * scale,
                close=values[3] * scale,
            )
        )
    for index in range(36, 52):
        close = base_price * (1.002 + (index - 36) * 0.002)
        candles.append(
            _candle(
                index,
                symbol=symbol,
                open_price=close * 0.999,
                high=close * 1.004,
                low=close * 0.996,
                close=close,
            )
        )
    return candles


def _candle(
    index: int,
    *,
    symbol: str,
    open_price: float,
    high: float,
    low: float,
    close: float,
    is_closed: bool = True,
) -> Candle:
    open_time = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=index * 5)
    return Candle(
        exchange="binance",
        symbol=symbol,
        interval="5m",
        open_time_utc=open_time,
        close_time_utc=open_time + timedelta(minutes=5) - timedelta(milliseconds=1),
        open=open_price,
        high=high,
        low=low,
        close=close,
        base_volume=1000.0,
        quote_volume=100_000.0,
        trade_count=100,
        is_closed=is_closed,
    )


def _replace_candle(candle: Candle, **overrides: object) -> Candle:
    return Candle(**{**candle.__dict__, **overrides})
