from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any
from uuid import uuid4

from crypto_signal_bot.backtest.leakage_checks import assert_next_candle_entry
from crypto_signal_bot.backtest.metrics import summarize_returns
from crypto_signal_bot.data.models import Candle, DataQualityReport
from crypto_signal_bot.features.bottoming import compute_bottoming_state
from crypto_signal_bot.features.indicators import interval_to_minutes, stochastic_cross_up, stochastic_kd
from crypto_signal_bot.features.three_tick import compute_three_tick_state
from crypto_signal_bot.signals.entry_timing import EntryTimingConfig, EntryTimingScorer
from crypto_signal_bot.signals.schemas import SignalCandidate

STRATEGY_VARIANTS = (
    "raw_three_tick_watch",
    "confirmed_entry_timing",
    "bottoming_confirmed",
    "stochastic_three_tick_confirmation",
    "excluding_falling_knife",
)


@dataclass(frozen=True)
class StrategyEventStudyConfig:
    min_history_bars: int = 30
    horizons: tuple[int, ...] = (1, 3, 6, 12)
    fee_bps: float = 10.0
    spread_bps: float = 5.0
    slippage_bps: float = 5.0
    signal_cooldown_bars: int = 3
    entry_timing: EntryTimingConfig = EntryTimingConfig(
        min_upside_score=0.0,
        min_liquidity_component=0.0,
    )

    @property
    def round_trip_cost(self) -> float:
        return (self.fee_bps + self.spread_bps + self.slippage_bps) / 10000


def strategy_event_study(
    candles_by_symbol: dict[str, list[Candle]],
    *,
    benchmark_symbol: str | None = None,
    benchmark_symbols: tuple[str, ...] | None = None,
    config: StrategyEventStudyConfig | None = None,
) -> dict[str, object]:
    cfg = config or StrategyEventStudyConfig()
    signal_records = _strategy_signal_records(candles_by_symbol, cfg)
    summaries = {
        variant: _variant_horizon_summaries(candles_by_symbol, signal_records[variant], cfg)
        for variant in STRATEGY_VARIANTS
    }
    turnover_exposure = _strategy_turnover_exposure_diagnostics(signal_records, cfg)
    return {
        **_strategy_diagnostic_flags(),
        "variants": list(STRATEGY_VARIANTS),
        "horizons": list(cfg.horizons),
        "cost_model": _cost_model(cfg),
        "signal_counts": {
            variant: len(signal_records[variant])
            for variant in STRATEGY_VARIANTS
        },
        "variant_summaries": summaries,
        "universe_diagnostics": _strategy_universe_diagnostics(candles_by_symbol, signal_records, cfg),
        "turnover_diagnostics": turnover_exposure["turnover_diagnostics"],
        "exposure_diagnostics": turnover_exposure["exposure_diagnostics"],
        "cost_sensitivity": _cost_sensitivity(candles_by_symbol, signal_records, cfg),
        "benchmark_diagnostics": _benchmark_diagnostics(
            candles_by_symbol,
            signal_records,
            benchmark_symbol=benchmark_symbol,
            config=cfg,
        ),
        "benchmark_set_diagnostics": _benchmark_set_diagnostics(
            candles_by_symbol,
            signal_records,
            benchmark_symbols=_benchmark_symbol_set(benchmark_symbol, benchmark_symbols),
            config=cfg,
        ),
        "baseline_diagnostics": _strategy_baseline_diagnostics(
            candles_by_symbol,
            signal_records,
            config=cfg,
        ),
        "stress_diagnostics": _strategy_stress_diagnostics(
            candles_by_symbol,
            signal_records,
            benchmark_symbol=benchmark_symbol,
            config=cfg,
        ),
        "falling_knife_filter": _falling_knife_filter(candles_by_symbol, signal_records, cfg),
        "sample_signals": {
            variant: signal_records[variant][:5]
            for variant in STRATEGY_VARIANTS
        },
    }


def generate_strategy_signal_indices(
    candles: list[Candle],
    *,
    variant: str,
    config: StrategyEventStudyConfig | None = None,
) -> list[int]:
    cfg = config or StrategyEventStudyConfig()
    return [
        int(record["signal_index"])
        for record in _symbol_signal_records(candles, cfg).get(variant, [])
    ]


def _strategy_signal_records(
    candles_by_symbol: dict[str, list[Candle]],
    config: StrategyEventStudyConfig,
) -> dict[str, list[dict[str, Any]]]:
    records: dict[str, list[dict[str, Any]]] = {variant: [] for variant in STRATEGY_VARIANTS}
    for symbol, candles in candles_by_symbol.items():
        by_variant = _symbol_signal_records(candles, config)
        for variant, variant_records in by_variant.items():
            for record in variant_records:
                records[variant].append({"symbol": symbol, **record})
    return records


def _symbol_signal_records(
    candles: list[Candle],
    config: StrategyEventStudyConfig,
) -> dict[str, list[dict[str, Any]]]:
    records: dict[str, list[dict[str, Any]]] = {variant: [] for variant in STRATEGY_VARIANTS}
    if len(candles) <= config.min_history_bars + max(config.horizons) + 1:
        return records

    last_signal_index = {variant: -10_000 for variant in STRATEGY_VARIANTS}
    max_horizon = max(config.horizons)
    for index in range(config.min_history_bars, len(candles) - max_horizon - 1):
        if not candles[index].is_closed:
            continue
        past = candles[: index + 1]
        state = _strategy_state_at(past, config)
        triggered = _triggered_variants(state)
        for variant in triggered:
            if index - last_signal_index[variant] <= config.signal_cooldown_bars:
                continue
            records[variant].append(_record_for_signal(candles, index, state))
            last_signal_index[variant] = index
    return records


def _strategy_state_at(candles: list[Candle], config: StrategyEventStudyConfig) -> dict[str, Any]:
    latest = candles[-1]
    candidate = _candidate_for_backtest(latest)
    quality = DataQualityReport(
        status="pass",
        warnings=[],
        coverage_ratio=1.0,
        stale_seconds=0.0,
        latest_close_time_utc=latest.close_time_utc,
    )
    entry_timing = EntryTimingScorer(config.entry_timing).score(
        candidate,
        candles,
        quality=quality,
    )
    three_tick = compute_three_tick_state(candles, config.entry_timing.three_tick)
    bottoming = compute_bottoming_state(candles, config.entry_timing.bottoming)
    closed = [candle for candle in candles if candle.is_closed]
    highs = [candle.high for candle in closed]
    lows = [candle.low for candle in closed]
    closes = [candle.close for candle in closed]
    k_values, d_values = stochastic_kd(highs, lows, closes)
    return {
        "entry_timing_status": entry_timing.status,
        "entry_timing_score": entry_timing.entry_timing_score,
        "three_tick_status": three_tick.status,
        "bottoming_status": bottoming.status,
        "stochastic_cross_up": stochastic_cross_up(k_values, d_values),
        "reason_codes": [
            *three_tick.reason_codes,
            *bottoming.reason_codes,
            *entry_timing.reason_codes,
        ],
        "risk_flags": [
            *three_tick.risk_flags,
            *bottoming.risk_flags,
            *entry_timing.risk_flags,
        ],
    }


def _triggered_variants(state: dict[str, Any]) -> list[str]:
    risk_flags = set(state["risk_flags"])
    variants: list[str] = []
    if state["three_tick_status"] == "watch":
        variants.append("raw_three_tick_watch")
    if state["entry_timing_status"] == "confirmed_candidate":
        variants.append("confirmed_entry_timing")
    if state["bottoming_status"] == "confirmed":
        variants.append("bottoming_confirmed")
    if state["three_tick_status"] == "watch" and state["stochastic_cross_up"]:
        variants.append("stochastic_three_tick_confirmation")
    if (
        state["entry_timing_status"] in {"confirmed_candidate", "watch"}
        and "falling_knife_suppress" not in risk_flags
    ):
        variants.append("excluding_falling_knife")
    return variants


def _record_for_signal(candles: list[Candle], index: int, state: dict[str, Any]) -> dict[str, Any]:
    entry_index = index + 1
    assert_next_candle_entry(candles[index], candles[entry_index])
    return {
        "signal_index": index,
        "entry_index": entry_index,
        "signal_time_utc": candles[index].close_time_utc.isoformat(),
        "entry_time_utc": candles[entry_index].open_time_utc.isoformat(),
        "entry_price": candles[entry_index].open,
        "entry_timing_status": state["entry_timing_status"],
        "three_tick_status": state["three_tick_status"],
        "bottoming_status": state["bottoming_status"],
        "stochastic_cross_up": state["stochastic_cross_up"],
        "reason_codes": _unique_strings(state["reason_codes"])[:10],
        "risk_flags": _unique_strings(state["risk_flags"])[:10],
    }


def _variant_horizon_summaries(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    config: StrategyEventStudyConfig,
    *,
    cost: float | None = None,
) -> dict[str, dict[str, float]]:
    applied_cost = config.round_trip_cost if cost is None else cost
    return {
        str(horizon): summarize_returns([
            ret
            for record in records
            if (ret := _forward_return(candles_by_symbol, record, horizon, applied_cost)) is not None
        ])
        for horizon in config.horizons
    }


def _cost_model(config: StrategyEventStudyConfig) -> dict[str, object]:
    return {
        "fee_bps": config.fee_bps,
        "spread_bps": config.spread_bps,
        "slippage_bps": config.slippage_bps,
        "round_trip_cost_bps": config.fee_bps + config.spread_bps + config.slippage_bps,
        "round_trip_cost_fraction": config.round_trip_cost,
        "applied_to_variant_summaries": True,
    }


def _cost_sensitivity(
    candles_by_symbol: dict[str, list[Candle]],
    signal_records: dict[str, list[dict[str, Any]]],
    config: StrategyEventStudyConfig,
) -> dict[str, object]:
    scenarios = {
        "zero_cost": 0.0,
        "configured_cost": config.round_trip_cost,
        "double_configured_cost": config.round_trip_cost * 2,
    }
    return {
        "scenarios": {
            name: {
                "round_trip_cost_fraction": cost,
                "round_trip_cost_bps": cost * 10000,
                "variant_summaries": {
                    variant: _variant_horizon_summaries(
                        candles_by_symbol,
                        signal_records[variant],
                        config,
                        cost=cost,
                    )
                    for variant in STRATEGY_VARIANTS
                },
            }
            for name, cost in scenarios.items()
        }
    }


def _benchmark_diagnostics(
    candles_by_symbol: dict[str, list[Candle]],
    signal_records: dict[str, list[dict[str, Any]]],
    *,
    benchmark_symbol: str | None,
    config: StrategyEventStudyConfig,
) -> dict[str, object]:
    if benchmark_symbol is None or benchmark_symbol not in candles_by_symbol:
        return {
            "benchmark_symbol": benchmark_symbol,
            "windows_aligned_point_in_time": True,
            "benchmark_return": {},
            "universe_median_return": {},
        }
    records = signal_records["confirmed_entry_timing"] or signal_records["excluding_falling_knife"]
    return {
        "benchmark_symbol": benchmark_symbol,
        "windows_aligned_point_in_time": True,
        "benchmark_return": {
            str(horizon): summarize_returns([
                ret
                for record in records
                if (
                    ret := _symbol_forward_return(
                        candles_by_symbol[benchmark_symbol],
                        int(record["signal_index"]),
                        horizon,
                        0.0,
                    )
                )
                is not None
            ])
            for horizon in config.horizons
        },
        "universe_median_return": {
            str(horizon): summarize_returns(_universe_median_returns(candles_by_symbol, records, horizon))
            for horizon in config.horizons
        },
    }


def _benchmark_symbol_set(
    benchmark_symbol: str | None,
    benchmark_symbols: tuple[str, ...] | None,
) -> tuple[str, ...]:
    values: list[str] = []
    if benchmark_symbol:
        values.append(benchmark_symbol)
    if benchmark_symbols is not None:
        values.extend(benchmark_symbols)
    return tuple(_unique_strings(values))


def _benchmark_set_diagnostics(
    candles_by_symbol: dict[str, list[Candle]],
    signal_records: dict[str, list[dict[str, Any]]],
    *,
    benchmark_symbols: tuple[str, ...],
    config: StrategyEventStudyConfig,
) -> dict[str, object]:
    records = signal_records["confirmed_entry_timing"] or signal_records["excluding_falling_knife"]
    available_symbols = [symbol for symbol in benchmark_symbols if symbol in candles_by_symbol]
    missing_symbols = [symbol for symbol in benchmark_symbols if symbol not in candles_by_symbol]
    return {
        "windows_aligned_point_in_time": True,
        "requested_symbols": list(benchmark_symbols),
        "available_symbols": available_symbols,
        "missing_symbols": missing_symbols,
        "benchmark_return_by_symbol": {
            symbol: {
                str(horizon): summarize_returns([
                    ret
                    for record in records
                    if (
                        ret := _symbol_forward_return(
                            candles_by_symbol[symbol],
                            int(record["signal_index"]),
                            horizon,
                            0.0,
                        )
                    )
                    is not None
                ])
                for horizon in config.horizons
            }
            for symbol in available_symbols
        },
        "benchmark_notes": (
            "Benchmark set diagnostics compare the same event windows against available benchmark symbols. "
            "They are not execution models."
        ),
    }


def _strategy_baseline_diagnostics(
    candles_by_symbol: dict[str, list[Candle]],
    signal_records: dict[str, list[dict[str, Any]]],
    *,
    config: StrategyEventStudyConfig,
) -> dict[str, object]:
    return {
        "windows_aligned_point_in_time": True,
        "applied_round_trip_cost_fraction": config.round_trip_cost,
        "variant_baselines": {
            variant: {
                "deterministic_random_symbol_return": _baseline_horizon_summaries(
                    candles_by_symbol,
                    records,
                    config,
                    selector="deterministic_random",
                ),
                "liquidity_ranked_symbol_return": _baseline_horizon_summaries(
                    candles_by_symbol,
                    records,
                    config,
                    selector="liquidity_ranked",
                ),
                "top_volume_equal_weight_basket_return": _baseline_horizon_summaries(
                    candles_by_symbol,
                    records,
                    config,
                    selector="top_volume_equal_weight_basket",
                ),
                "top_volume_basket_size": 3,
                "top_volume_basket_point_in_time": True,
            }
            for variant, records in signal_records.items()
        },
        "baseline_notes": (
            "Baselines are deterministic strategy event-study diagnostics using the same windows. "
            "They are not execution models."
        ),
    }


def _strategy_turnover_exposure_diagnostics(
    signal_records: dict[str, list[dict[str, Any]]],
    config: StrategyEventStudyConfig,
) -> dict[str, dict[str, object]]:
    all_records = [record for records in signal_records.values() for record in records]
    variant_event_counts = {
        variant: len(records)
        for variant, records in signal_records.items()
    }
    if not all_records:
        return {
            "turnover_diagnostics": {
                "events": 0,
                "unique_signal_times": 0,
                "diagnostic_turnover_events_per_signal_time": 0.0,
                "variant_event_counts": variant_event_counts,
                "event_turnover_only": True,
                "not_order_turnover": True,
            },
            "exposure_diagnostics": {
                "holding_horizons": list(config.horizons),
                "max_overlapping_event_windows": 0,
                "average_overlapping_event_windows": 0.0,
                "event_overlap_only": True,
                "not_account_exposure": True,
                "not_portfolio_exposure": True,
            },
        }

    unique_signal_times = {str(record["signal_time_utc"]) for record in all_records}
    overlap_counts = _strategy_overlap_counts(all_records, max(config.horizons))
    return {
        "turnover_diagnostics": {
            "events": len(all_records),
            "unique_signal_times": len(unique_signal_times),
            "diagnostic_turnover_events_per_signal_time": len(all_records) / len(unique_signal_times),
            "variant_event_counts": variant_event_counts,
            "event_turnover_only": True,
            "not_order_turnover": True,
        },
        "exposure_diagnostics": {
            "holding_horizons": list(config.horizons),
            "max_overlapping_event_windows": max(overlap_counts),
            "average_overlapping_event_windows": sum(overlap_counts) / len(overlap_counts),
            "event_overlap_only": True,
            "not_account_exposure": True,
            "not_portfolio_exposure": True,
        },
    }


def _strategy_overlap_counts(records: list[dict[str, Any]], holding_bars: int) -> list[int]:
    min_entry = min(int(record["entry_index"]) for record in records)
    max_exit = max(int(record["entry_index"]) + holding_bars for record in records)
    return [
        sum(
            1
            for record in records
            if int(record["entry_index"]) <= index <= int(record["entry_index"]) + holding_bars
        )
        for index in range(min_entry, max_exit + 1)
    ]


def _strategy_universe_diagnostics(
    candles_by_symbol: dict[str, list[Candle]],
    signal_records: dict[str, list[dict[str, Any]]],
    config: StrategyEventStudyConfig,
) -> dict[str, object]:
    input_symbols = sorted(candles_by_symbol)
    symbols_with_sufficient_history = [
        symbol
        for symbol, candles in sorted(candles_by_symbol.items())
        if len(candles) > config.min_history_bars + max(config.horizons) + 1
    ]
    symbols_with_signals = sorted({
        str(record["symbol"])
        for records in signal_records.values()
        for record in records
    })
    empty_candle_symbols = [symbol for symbol, candles in sorted(candles_by_symbol.items()) if not candles]
    return {
        "input_symbols": input_symbols,
        "symbols_with_sufficient_history": symbols_with_sufficient_history,
        "symbols_with_strategy_events": symbols_with_signals,
        "symbols_without_strategy_events": [
            symbol for symbol in input_symbols if symbol not in symbols_with_signals
        ],
        "empty_candle_symbols": empty_candle_symbols,
        "insufficient_history_symbols": [
            symbol for symbol in input_symbols if symbol not in symbols_with_sufficient_history
        ],
        "delisted_or_missing_asset_candidates": empty_candle_symbols,
        "external_missing_assets_not_detectable_without_manifest": True,
        "survivorship_bias_audit_only": True,
        "not_complete_delisting_database": True,
    }


def _baseline_horizon_summaries(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    config: StrategyEventStudyConfig,
    *,
    selector: str,
) -> dict[str, dict[str, float]]:
    return {
        str(horizon): summarize_returns(
            _baseline_returns(
                candles_by_symbol,
                records,
                horizon,
                config.round_trip_cost,
                selector=selector,
            )
        )
        for horizon in config.horizons
    }


def _baseline_returns(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    horizon_bars: int,
    cost: float,
    *,
    selector: str,
) -> list[float]:
    returns: list[float] = []
    for record in records:
        symbols = _eligible_baseline_symbols(candles_by_symbol, record, horizon_bars, cost)
        if not symbols:
            continue
        if selector == "deterministic_random":
            selected = symbols[_stable_baseline_index(record, horizon_bars, len(symbols))]
        elif selector == "liquidity_ranked":
            selected = max(
                symbols,
                key=lambda symbol: (
                    candles_by_symbol[symbol][int(record["signal_index"])].quote_volume or 0.0,
                    symbol,
                ),
            )
        elif selector == "top_volume_equal_weight_basket":
            selected_symbols = sorted(
                symbols,
                key=lambda symbol: (
                    candles_by_symbol[symbol][int(record["signal_index"])].quote_volume or 0.0,
                    symbol,
                ),
                reverse=True,
            )[:3]
            basket_returns = [
                value
                for symbol in selected_symbols
                if (
                    value := _symbol_forward_return(
                        candles_by_symbol[symbol],
                        int(record["signal_index"]),
                        horizon_bars,
                        cost,
                    )
                )
                is not None
            ]
            if basket_returns:
                returns.append(sum(basket_returns) / len(basket_returns))
            continue
        else:
            raise ValueError(f"Unknown baseline selector: {selector}")
        ret = _symbol_forward_return(
            candles_by_symbol[selected],
            int(record["signal_index"]),
            horizon_bars,
            cost,
        )
        if ret is not None:
            returns.append(ret)
    return returns


def _eligible_baseline_symbols(
    candles_by_symbol: dict[str, list[Candle]],
    record: dict[str, Any],
    horizon_bars: int,
    cost: float,
) -> list[str]:
    signal_index = int(record["signal_index"])
    return [
        symbol
        for symbol, candles in sorted(candles_by_symbol.items())
        if _symbol_forward_return(candles, signal_index, horizon_bars, cost) is not None
    ]


def _stable_baseline_index(record: dict[str, Any], horizon_bars: int, symbol_count: int) -> int:
    symbol = str(record["symbol"])
    symbol_offset = sum(ord(character) for character in symbol)
    return (int(record["signal_index"]) + horizon_bars + symbol_offset) % symbol_count


def _falling_knife_filter(
    candles_by_symbol: dict[str, list[Candle]],
    signal_records: dict[str, list[dict[str, Any]]],
    config: StrategyEventStudyConfig,
) -> dict[str, object]:
    raw_records = signal_records["raw_three_tick_watch"]
    without_falling_knife = [
        record
        for record in raw_records
        if "falling_knife_suppress" not in record.get("risk_flags", [])
    ]
    horizon = config.horizons[0]
    return {
        "variant": "raw_three_tick_watch",
        "horizon_bars": horizon,
        "including_all_signals": summarize_returns([
            ret
            for record in raw_records
            if (ret := _forward_return(candles_by_symbol, record, horizon, config.round_trip_cost)) is not None
        ]),
        "excluding_falling_knife": summarize_returns([
            ret
            for record in without_falling_knife
            if (ret := _forward_return(candles_by_symbol, record, horizon, config.round_trip_cost)) is not None
        ]),
    }


def _strategy_stress_diagnostics(
    candles_by_symbol: dict[str, list[Candle]],
    signal_records: dict[str, list[dict[str, Any]]],
    *,
    benchmark_symbol: str | None,
    config: StrategyEventStudyConfig,
) -> dict[str, object]:
    horizon = config.horizons[0]
    all_records = [record for records in signal_records.values() for record in records]
    volatility_values = [
        value
        for record in all_records
        if (value := _prior_realized_volatility(candles_by_symbol, record)) is not None
    ]
    liquidity_values = [
        value
        for record in all_records
        if (value := _signal_quote_volume(candles_by_symbol, record)) is not None
    ]
    volatility_threshold = median(volatility_values) if volatility_values else None
    liquidity_threshold = median(liquidity_values) if liquidity_values else None
    return {
        "strategy_event_stress_only": True,
        "not_portfolio_simulator": True,
        "horizon_bars": horizon,
        "thresholds": {
            "prior_realized_volatility_median": volatility_threshold,
            "entry_quote_volume_median": liquidity_threshold,
            "benchmark_drawdown_return_below": 0.0,
            "api_outage_gap_multiple": 1.5,
        },
        "variant_slices": {
            variant: _stress_slices_for_records(
                candles_by_symbol,
                records,
                benchmark_symbol=benchmark_symbol,
                config=config,
                horizon_bars=horizon,
                volatility_threshold=volatility_threshold,
                liquidity_threshold=liquidity_threshold,
            )
            for variant, records in signal_records.items()
        },
    }


def _stress_slices_for_records(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    *,
    benchmark_symbol: str | None,
    config: StrategyEventStudyConfig,
    horizon_bars: int,
    volatility_threshold: float | None,
    liquidity_threshold: float | None,
) -> dict[str, object]:
    high_volatility_returns: list[float] = []
    thin_liquidity_returns: list[float] = []
    benchmark_drawdown_returns: list[float] = []
    outage_returns: list[float] = []
    non_outage_returns: list[float] = []
    for record in records:
        ret = _forward_return(candles_by_symbol, record, horizon_bars, config.round_trip_cost)
        if ret is None:
            continue
        if _is_high_volatility_window(candles_by_symbol, record, volatility_threshold):
            high_volatility_returns.append(ret)
        if _is_thin_liquidity_window(candles_by_symbol, record, liquidity_threshold):
            thin_liquidity_returns.append(ret)
        if _benchmark_forward_return(candles_by_symbol, record, benchmark_symbol, horizon_bars) < 0:
            benchmark_drawdown_returns.append(ret)
        if _has_api_outage_gap(candles_by_symbol, record, horizon_bars):
            outage_returns.append(ret)
        else:
            non_outage_returns.append(ret)
    return {
        "high_volatility_windows": summarize_returns(high_volatility_returns),
        "thin_liquidity_windows": summarize_returns(thin_liquidity_returns),
        "benchmark_drawdown_windows": summarize_returns(benchmark_drawdown_returns),
        "api_outage_windows": {
            "outage_flagged": summarize_returns(outage_returns),
            "excluding_outage_flagged": summarize_returns(non_outage_returns),
        },
    }


def _is_high_volatility_window(
    candles_by_symbol: dict[str, list[Candle]],
    record: dict[str, Any],
    threshold: float | None,
) -> bool:
    value = _prior_realized_volatility(candles_by_symbol, record)
    return threshold is not None and value is not None and value >= threshold


def _is_thin_liquidity_window(
    candles_by_symbol: dict[str, list[Candle]],
    record: dict[str, Any],
    threshold: float | None,
) -> bool:
    value = _signal_quote_volume(candles_by_symbol, record)
    return threshold is not None and value is not None and value <= threshold


def _prior_realized_volatility(
    candles_by_symbol: dict[str, list[Candle]],
    record: dict[str, Any],
    *,
    lookback: int = 20,
) -> float | None:
    candles = candles_by_symbol.get(str(record["symbol"]), [])
    signal_index = int(record["signal_index"])
    if signal_index <= 0 or signal_index >= len(candles):
        return None
    start = max(1, signal_index - lookback + 1)
    returns: list[float] = []
    for index in range(start, signal_index + 1):
        previous = candles[index - 1]
        current = candles[index]
        if previous.close <= 0 or current.close <= 0:
            return None
        returns.append(current.close / previous.close - 1)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    return variance**0.5


def _signal_quote_volume(
    candles_by_symbol: dict[str, list[Candle]],
    record: dict[str, Any],
) -> float | None:
    candles = candles_by_symbol.get(str(record["symbol"]), [])
    entry_index = int(record["entry_index"])
    if entry_index < 0 or entry_index >= len(candles):
        return None
    return candles[entry_index].quote_volume


def _benchmark_forward_return(
    candles_by_symbol: dict[str, list[Candle]],
    record: dict[str, Any],
    benchmark_symbol: str | None,
    horizon_bars: int,
) -> float:
    if benchmark_symbol is None or benchmark_symbol not in candles_by_symbol:
        return 0.0
    ret = _symbol_forward_return(
        candles_by_symbol[benchmark_symbol],
        int(record["signal_index"]),
        horizon_bars,
        0.0,
    )
    return ret if ret is not None else 0.0


def _has_api_outage_gap(
    candles_by_symbol: dict[str, list[Candle]],
    record: dict[str, Any],
    horizon_bars: int,
) -> bool:
    candles = candles_by_symbol.get(str(record["symbol"]), [])
    signal_index = int(record["signal_index"])
    if signal_index <= 0 or signal_index >= len(candles):
        return False
    expected_seconds = interval_to_minutes(candles[signal_index].interval) * 60
    first_index = max(1, signal_index - 3)
    last_index = min(len(candles) - 1, int(record["entry_index"]) + horizon_bars)
    for index in range(first_index, last_index + 1):
        delta_seconds = (candles[index].open_time_utc - candles[index - 1].open_time_utc).total_seconds()
        if delta_seconds > expected_seconds * 1.5:
            return True
    return False


def _forward_return(
    candles_by_symbol: dict[str, list[Candle]],
    record: dict[str, Any],
    horizon_bars: int,
    cost: float,
) -> float | None:
    candles = candles_by_symbol.get(str(record["symbol"]), [])
    return _symbol_forward_return(candles, int(record["signal_index"]), horizon_bars, cost)


def _symbol_forward_return(
    candles: list[Candle],
    signal_index: int,
    horizon_bars: int,
    cost: float,
) -> float | None:
    entry_index = signal_index + 1
    exit_index = entry_index + horizon_bars
    if signal_index < 0 or exit_index >= len(candles):
        return None
    signal = candles[signal_index]
    entry = candles[entry_index]
    exit_candle = candles[exit_index]
    if not signal.is_closed or not entry.is_closed or not exit_candle.is_closed:
        return None
    assert_next_candle_entry(signal, entry)
    if entry.open <= 0:
        return None
    return exit_candle.close / entry.open - 1 - cost


def _universe_median_returns(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    horizon_bars: int,
) -> list[float]:
    returns: list[float] = []
    for record in records:
        window_returns = [
            value
            for candles in candles_by_symbol.values()
            if (
                value := _symbol_forward_return(
                    candles,
                    int(record["signal_index"]),
                    horizon_bars,
                    0.0,
                )
            )
            is not None
        ]
        if window_returns:
            returns.append(median(window_returns))
    return returns


def _candidate_for_backtest(candle: Candle) -> SignalCandidate:
    return SignalCandidate(
        exchange=candle.exchange,
        symbol=candle.symbol,
        interval=candle.interval,
        current_price=candle.close,
        score=75.0,
        component_scores={
            "trend": 60.0,
            "momentum": 60.0,
            "volume": 70.0,
            "liquidity": 80.0,
            "breakout": 50.0,
            "relative_strength": 50.0,
            "market_regime": 55.0,
        },
        confidence="medium",
        rank=None,
        drivers=["strategy_event_study_fixture"],
        risk_flags=[],
        invalidation_condition="Strategy event study diagnostic only.",
        data_timestamp_utc=candle.close_time_utc.isoformat(),
        source_run_id=str(uuid4()),
        is_closed_candle_signal=candle.is_closed,
        data_quality_status="pass",
        data_freshness_seconds=0.0,
    )


def _strategy_diagnostic_flags() -> dict[str, bool | str]:
    return {
        "strategy_event_study_only": True,
        "diagnostic_event_study_only": True,
        "not_portfolio_simulator": True,
        "no_execution_model": True,
        "hypothetical_diagnostic_only": True,
        "closed_candle_signals_only": True,
        "next_open_entry_enforced": True,
        "notification_logic_excluded": True,
        "not_financial_advice": True,
        "research_warning": (
            "Strategy event study is hypothetical diagnostic research only. "
            "It is not financial advice, not a portfolio simulator, and no order was placed."
        ),
    }


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
