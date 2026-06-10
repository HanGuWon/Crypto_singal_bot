from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product
from statistics import median
from typing import Any

from crypto_signal_bot.backtest.leakage_checks import assert_next_candle_entry
from crypto_signal_bot.backtest.metrics import summarize_returns
from crypto_signal_bot.data.models import Candle


@dataclass(frozen=True)
class BacktestAssumptions:
    fee_bps: float = 10.0
    spread_bps: float = 5.0
    slippage_bps: float = 5.0
    holding_bars: int = 3

    @property
    def round_trip_cost(self) -> float:
        return (self.fee_bps + self.spread_bps + self.slippage_bps) / 10000


def event_study_next_open(
    candles: list[Candle],
    signal_indices: list[int],
    *,
    assumptions: BacktestAssumptions | None = None,
) -> dict[str, float | bool | str]:
    assumptions = assumptions or BacktestAssumptions()
    returns = _window_returns(candles, signal_indices, assumptions)
    metrics: dict[str, float | bool | str] = {}
    metrics.update(summarize_returns(returns))
    metrics.update(_diagnostic_flags())
    return metrics


def diagnostic_event_study(
    candles_by_symbol: dict[str, list[Candle]],
    signal_indices_by_symbol: dict[str, list[int]],
    *,
    benchmark_symbol: str | None = None,
    benchmark_symbols: tuple[str, ...] | None = None,
    symbol_conditions: dict[str, dict[str, Any]] | None = None,
    assumptions_grid: list[BacktestAssumptions] | None = None,
) -> dict[str, object]:
    symbol_conditions = symbol_conditions or {}
    base_assumptions = BacktestAssumptions()
    records = _event_records(candles_by_symbol, signal_indices_by_symbol, base_assumptions, symbol_conditions)
    event_exposure = _event_exposure_diagnostics(records, base_assumptions)
    benchmark_records = _benchmark_records(
        candles_by_symbol,
        records,
        benchmark_symbol=benchmark_symbol,
        assumptions=BacktestAssumptions(fee_bps=0, spread_bps=0, slippage_bps=0),
    )
    return {
        **_diagnostic_flags(),
        "benchmark_diagnostics": {
            "benchmark_symbol": benchmark_symbol,
            "benchmark_return": summarize_returns([record["return"] for record in benchmark_records]),
            "universe_median_return": summarize_returns(_universe_window_returns(candles_by_symbol, records, "median")),
            "equal_weight_universe_return": summarize_returns(
                _universe_window_returns(candles_by_symbol, records, "equal_weight")
            ),
            "windows_aligned_point_in_time": True,
        },
        "baseline_diagnostics": _baseline_diagnostics(candles_by_symbol, records),
        "benchmark_set_diagnostics": _benchmark_set_diagnostics(
            candles_by_symbol,
            records,
            benchmark_symbols=_benchmark_symbol_set(benchmark_symbol, benchmark_symbols),
            assumptions=BacktestAssumptions(fee_bps=0, spread_bps=0, slippage_bps=0),
        ),
        "event_exposure_diagnostics": event_exposure,
        "turnover_diagnostics": _turnover_diagnostics(event_exposure),
        "exposure_diagnostics": _exposure_diagnostics(event_exposure),
        "stress_diagnostics": _stress_diagnostics(
            candles_by_symbol,
            records,
            benchmark_symbol=benchmark_symbol,
            assumptions=BacktestAssumptions(fee_bps=0, spread_bps=0, slippage_bps=0),
        ),
        "calibration_diagnostics": _calibration_diagnostics(records),
        "sensitivity_grid": _sensitivity_grid(
            candles_by_symbol,
            signal_indices_by_symbol,
            symbol_conditions,
            assumptions_grid or _default_assumption_grid(),
        ),
        "data_quality_conditioned": _conditioned_results(records),
        "walk_forward": _walk_forward_diagnostic(records),
    }


def _window_returns(
    candles: list[Candle],
    signal_indices: list[int],
    assumptions: BacktestAssumptions,
) -> list[float]:
    returns: list[float] = []
    for index in signal_indices:
        value = _window_return(candles, index, assumptions)
        if value is not None:
            returns.append(value)
    return returns


def _window_return(candles: list[Candle], index: int, assumptions: BacktestAssumptions) -> float | None:
    entry_index = index + 1
    exit_index = entry_index + assumptions.holding_bars
    if index < 0 or exit_index >= len(candles):
        return None
    signal = candles[index]
    entry = candles[entry_index]
    exit_candle = candles[exit_index]
    if not signal.is_closed or not entry.is_closed or not exit_candle.is_closed:
        return None
    assert_next_candle_entry(signal, entry)
    return exit_candle.close / entry.open - 1 - assumptions.round_trip_cost


def _event_records(
    candles_by_symbol: dict[str, list[Candle]],
    signal_indices_by_symbol: dict[str, list[int]],
    assumptions: BacktestAssumptions,
    symbol_conditions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for symbol, indices in signal_indices_by_symbol.items():
        candles = candles_by_symbol.get(symbol, [])
        for index in indices:
            ret = _window_return(candles, index, assumptions)
            if ret is None:
                continue
            entry_index = index + 1
            exit_index = entry_index + assumptions.holding_bars
            records.append(
                {
                    "symbol": symbol,
                    "signal_index": index,
                    "entry_index": entry_index,
                    "exit_index": exit_index,
                    "signal_time_utc": candles[index].close_time_utc.isoformat(),
                    "entry_time_utc": candles[entry_index].open_time_utc.isoformat(),
                    "exit_time_utc": candles[exit_index].close_time_utc.isoformat(),
                    "return": ret,
                    "condition": symbol_conditions.get(symbol, {}),
                }
            )
    return records


def _benchmark_records(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    *,
    benchmark_symbol: str | None,
    assumptions: BacktestAssumptions,
) -> list[dict[str, Any]]:
    if benchmark_symbol is None or benchmark_symbol not in candles_by_symbol:
        return []
    benchmark = candles_by_symbol[benchmark_symbol]
    output: list[dict[str, Any]] = []
    for record in records:
        ret = _window_return(benchmark, int(record["signal_index"]), assumptions)
        if ret is None:
            continue
        output.append({**record, "symbol": benchmark_symbol, "return": ret})
    return output


def _benchmark_symbol_set(
    benchmark_symbol: str | None,
    benchmark_symbols: tuple[str, ...] | None,
) -> tuple[str, ...]:
    values: list[str] = []
    if benchmark_symbol:
        values.append(benchmark_symbol)
    if benchmark_symbols is not None:
        values.extend(benchmark_symbols)
    return tuple(dict.fromkeys(value for value in values if value))


def _benchmark_set_diagnostics(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    *,
    benchmark_symbols: tuple[str, ...],
    assumptions: BacktestAssumptions,
) -> dict[str, object]:
    available_symbols = [symbol for symbol in benchmark_symbols if symbol in candles_by_symbol]
    missing_symbols = [symbol for symbol in benchmark_symbols if symbol not in candles_by_symbol]
    return {
        "windows_aligned_point_in_time": True,
        "requested_symbols": list(benchmark_symbols),
        "available_symbols": available_symbols,
        "missing_symbols": missing_symbols,
        "benchmark_return_by_symbol": {
            symbol: summarize_returns([
                record["return"]
                for record in _benchmark_records(
                    candles_by_symbol,
                    records,
                    benchmark_symbol=symbol,
                    assumptions=assumptions,
                )
            ])
            for symbol in available_symbols
        },
        "benchmark_notes": (
            "Benchmark set diagnostics compare the same event windows against available benchmark symbols. "
            "They are not execution models."
        ),
    }


def _baseline_diagnostics(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
) -> dict[str, object]:
    assumptions = BacktestAssumptions(fee_bps=0, spread_bps=0, slippage_bps=0)
    return {
        "windows_aligned_point_in_time": True,
        "deterministic_random_symbol_return": summarize_returns(
            _deterministic_random_baseline_returns(candles_by_symbol, records, assumptions)
        ),
        "liquidity_ranked_symbol_return": summarize_returns(
            _liquidity_ranked_baseline_returns(candles_by_symbol, records, assumptions)
        ),
        "baseline_notes": (
            "Baselines are deterministic event-study diagnostics using the same signal windows. "
            "They are not portfolio execution models."
        ),
    }


def _deterministic_random_baseline_returns(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    assumptions: BacktestAssumptions,
) -> list[float]:
    returns: list[float] = []
    for record in records:
        symbols = _eligible_symbols_for_window(candles_by_symbol, int(record["signal_index"]), assumptions)
        if not symbols:
            continue
        selected = symbols[_stable_baseline_index(record, len(symbols))]
        ret = _window_return(candles_by_symbol[selected], int(record["signal_index"]), assumptions)
        if ret is not None:
            returns.append(ret)
    return returns


def _liquidity_ranked_baseline_returns(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    assumptions: BacktestAssumptions,
) -> list[float]:
    returns: list[float] = []
    for record in records:
        index = int(record["signal_index"])
        symbols = _eligible_symbols_for_window(candles_by_symbol, index, assumptions)
        if not symbols:
            continue
        selected = max(
            symbols,
            key=lambda symbol: (
                candles_by_symbol[symbol][index].quote_volume or 0.0,
                symbol,
            ),
        )
        ret = _window_return(candles_by_symbol[selected], index, assumptions)
        if ret is not None:
            returns.append(ret)
    return returns


def _eligible_symbols_for_window(
    candles_by_symbol: dict[str, list[Candle]],
    signal_index: int,
    assumptions: BacktestAssumptions,
) -> list[str]:
    return [
        symbol
        for symbol, candles in sorted(candles_by_symbol.items())
        if _window_return(candles, signal_index, assumptions) is not None
    ]


def _stable_baseline_index(record: dict[str, Any], symbol_count: int) -> int:
    symbol = str(record["symbol"])
    symbol_offset = sum(ord(character) for character in symbol)
    return (int(record["signal_index"]) + symbol_offset) % symbol_count


def _universe_window_returns(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    mode: str,
) -> list[float]:
    returns: list[float] = []
    assumptions = BacktestAssumptions(fee_bps=0, spread_bps=0, slippage_bps=0)
    for record in records:
        window_returns = [
            value
            for candles in candles_by_symbol.values()
            if (value := _window_return(candles, int(record["signal_index"]), assumptions)) is not None
        ]
        if not window_returns:
            continue
        if mode == "median":
            returns.append(median(window_returns))
        else:
            returns.append(sum(window_returns) / len(window_returns))
    return returns


def _sensitivity_grid(
    candles_by_symbol: dict[str, list[Candle]],
    signal_indices_by_symbol: dict[str, list[int]],
    symbol_conditions: dict[str, dict[str, Any]],
    assumptions_grid: list[BacktestAssumptions],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for assumptions in assumptions_grid:
        records = _event_records(candles_by_symbol, signal_indices_by_symbol, assumptions, symbol_conditions)
        rows.append(
            {
                "fee_bps": assumptions.fee_bps,
                "spread_bps": assumptions.spread_bps,
                "slippage_bps": assumptions.slippage_bps,
                "holding_bars": assumptions.holding_bars,
                "summary": summarize_returns([record["return"] for record in records]),
            }
        )
    return rows


def _conditioned_results(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    return {
        "all_eligible_candidates": summarize_returns([record["return"] for record in records]),
        "excluding_stale_fail_symbols": summarize_returns(
            [
                record["return"]
                for record in records
                if record["condition"].get("data_quality_status", "pass") == "pass"
                and "stale_data" not in record["condition"].get("risk_flags", [])
            ]
        ),
        "excluding_quarantined_symbols": summarize_returns(
            [
                record["return"]
                for record in records
                if record["condition"].get("symbol_health_status", "healthy") != "quarantined"
            ]
        ),
        "low_confidence": summarize_returns(
            [record["return"] for record in records if record["condition"].get("confidence") == "low"]
        ),
        "low_liquidity": summarize_returns(
            [
                record["return"]
                for record in records
                if "low_liquidity" in record["condition"].get("risk_flags", [])
            ]
        ),
    }


def _stress_diagnostics(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    *,
    benchmark_symbol: str | None,
    assumptions: BacktestAssumptions,
) -> dict[str, object]:
    vol_rows = [
        (record, volatility)
        for record in records
        if (
            volatility := _prior_realized_volatility(
                candles_by_symbol.get(str(record["symbol"]), []),
                int(record["signal_index"]),
            )
        )
        is not None
    ]
    volume_rows = [
        (record, quote_volume)
        for record in records
        if (
            quote_volume := _signal_quote_volume(
                candles_by_symbol.get(str(record["symbol"]), []),
                int(record["signal_index"]),
            )
        )
        is not None
    ]
    benchmark_rows = _benchmark_stress_records(
        candles_by_symbol,
        records,
        benchmark_symbol=benchmark_symbol,
        assumptions=assumptions,
    )
    vol_threshold = median([value for _, value in vol_rows]) if vol_rows else None
    volume_threshold = median([value for _, value in volume_rows]) if volume_rows else None
    outage_records = [
        record
        for record in records
        if record["condition"].get("api_outage_simulated") is True
        or "api_outage" in record["condition"].get("risk_flags", [])
    ]
    return {
        "event_study_stress_only": True,
        "high_volatility_windows": summarize_returns(
            [
                record["return"]
                for record, volatility in vol_rows
                if vol_threshold is not None and volatility >= vol_threshold
            ]
        ),
        "thin_liquidity_windows": summarize_returns(
            [
                record["return"]
                for record, quote_volume in volume_rows
                if volume_threshold is not None and quote_volume <= volume_threshold
            ]
        ),
        "benchmark_drawdown_windows": summarize_returns(
            [record["return"] for record, benchmark_return in benchmark_rows if benchmark_return < 0]
        ),
        "api_outage_simulation": {
            "outage_flagged": summarize_returns([record["return"] for record in outage_records]),
            "excluding_outage_flagged": summarize_returns([
                record["return"]
                for record in records
                if record not in outage_records
            ]),
        },
        "thresholds": {
            "realized_volatility_median": vol_threshold,
            "quote_volume_median": volume_threshold,
            "benchmark_drawdown_return_below": 0.0,
        },
        "not_portfolio_simulator": True,
    }


def _prior_realized_volatility(candles: list[Candle], signal_index: int, lookback: int = 20) -> float | None:
    if signal_index <= 0 or signal_index >= len(candles):
        return None
    start = max(1, signal_index - lookback + 1)
    returns = [
        candles[index].close / candles[index - 1].close - 1
        for index in range(start, signal_index + 1)
        if candles[index - 1].close > 0
    ]
    if not returns:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((ret - mean) ** 2 for ret in returns) / len(returns)
    return math.sqrt(variance)


def _signal_quote_volume(candles: list[Candle], signal_index: int) -> float | None:
    if signal_index < 0 or signal_index >= len(candles):
        return None
    return candles[signal_index].quote_volume


def _benchmark_stress_records(
    candles_by_symbol: dict[str, list[Candle]],
    records: list[dict[str, Any]],
    *,
    benchmark_symbol: str | None,
    assumptions: BacktestAssumptions,
) -> list[tuple[dict[str, Any], float]]:
    if benchmark_symbol is None or benchmark_symbol not in candles_by_symbol:
        return []
    benchmark = candles_by_symbol[benchmark_symbol]
    output: list[tuple[dict[str, Any], float]] = []
    for record in records:
        ret = _window_return(benchmark, int(record["signal_index"]), assumptions)
        if ret is not None:
            output.append((record, ret))
    return output


def _calibration_diagnostics(records: list[dict[str, Any]]) -> dict[str, object]:
    scored_records = [
        (record, score)
        for record in records
        if (score := _record_score(record)) is not None
    ]
    buckets: dict[str, list[float]] = {}
    for record, score in scored_records:
        bucket_start = int(score // 10) * 10
        bucket_end = min(bucket_start + 9, 100)
        key = f"{bucket_start:02d}-{bucket_end:02d}"
        buckets.setdefault(key, []).append(record["return"])
    return {
        "score_field": "condition.score",
        "calibration_available": bool(scored_records),
        "bucket_count": len(buckets),
        "score_buckets": {
            key: summarize_returns(values)
            for key, values in sorted(buckets.items())
        },
        "not_predictive_claim": True,
    }


def _record_score(record: dict[str, Any]) -> float | None:
    value = record["condition"].get("score")
    if value is None:
        value = record["condition"].get("research_priority_score")
    if value is None:
        return None
    try:
        return max(0.0, min(float(value), 100.0))
    except (TypeError, ValueError):
        return None


def _event_exposure_diagnostics(
    records: list[dict[str, Any]],
    assumptions: BacktestAssumptions,
) -> dict[str, object]:
    if not records:
        return {
            "events": 0,
            "unique_signal_times": 0,
            "average_events_per_signal_time": 0.0,
            "max_events_same_signal_time": 0,
            "holding_bars": assumptions.holding_bars,
            "max_overlapping_event_windows": 0,
            "average_overlapping_event_windows": 0.0,
            "diagnostic_turnover_events_per_signal_time": 0.0,
            "event_overlap_only": True,
            "not_portfolio_exposure": True,
        }
    counts_by_signal_time: dict[str, int] = {}
    for record in records:
        signal_time = str(record["signal_time_utc"])
        counts_by_signal_time[signal_time] = counts_by_signal_time.get(signal_time, 0) + 1
    overlap_counts = _overlap_counts(records)
    unique_signal_times = len(counts_by_signal_time)
    return {
        "events": len(records),
        "unique_signal_times": unique_signal_times,
        "average_events_per_signal_time": len(records) / unique_signal_times,
        "max_events_same_signal_time": max(counts_by_signal_time.values()),
        "holding_bars": assumptions.holding_bars,
        "max_overlapping_event_windows": max(overlap_counts),
        "average_overlapping_event_windows": sum(overlap_counts) / len(overlap_counts),
        "diagnostic_turnover_events_per_signal_time": len(records) / unique_signal_times,
        "event_overlap_only": True,
        "not_portfolio_exposure": True,
    }


def _turnover_diagnostics(event_exposure: dict[str, object]) -> dict[str, object]:
    return {
        "events": event_exposure["events"],
        "unique_signal_times": event_exposure["unique_signal_times"],
        "diagnostic_turnover_events_per_signal_time": event_exposure[
            "diagnostic_turnover_events_per_signal_time"
        ],
        "event_turnover_only": True,
        "not_order_turnover": True,
    }


def _exposure_diagnostics(event_exposure: dict[str, object]) -> dict[str, object]:
    return {
        "holding_bars": event_exposure["holding_bars"],
        "max_overlapping_event_windows": event_exposure["max_overlapping_event_windows"],
        "average_overlapping_event_windows": event_exposure["average_overlapping_event_windows"],
        "event_overlap_only": True,
        "not_account_exposure": True,
        "not_portfolio_exposure": True,
    }


def _overlap_counts(records: list[dict[str, Any]]) -> list[int]:
    min_entry = min(int(record["entry_index"]) for record in records)
    max_exit = max(int(record["exit_index"]) for record in records)
    return [
        sum(
            1
            for record in records
            if int(record["entry_index"]) <= index <= int(record["exit_index"])
        )
        for index in range(min_entry, max_exit + 1)
    ]


def _walk_forward_diagnostic(records: list[dict[str, Any]]) -> dict[str, object]:
    ordered = sorted(records, key=lambda record: str(record["signal_time_utc"]))
    feature_window, evaluation_window = _chronological_half_split(ordered)
    folds, fold_evaluation_records = _walk_forward_folds(ordered)
    return {
        "feature_scoring_window": _window_metadata(feature_window),
        "evaluation_window": {
            **_window_metadata(evaluation_window),
            "summary": summarize_returns([record["return"] for record in evaluation_window]),
        },
        "fold_count": len(folds),
        "folds": folds,
        "aggregate_evaluation_summary": summarize_returns([
            record["return"] for record in fold_evaluation_records
        ]),
        "expanding_prior_windows": True,
        "no_future_feature_normalization": True,
    }


def _chronological_half_split(
    ordered: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    times = _unique_signal_times(ordered)
    if len(times) < 2:
        return ordered, []
    split = max(1, len(times) // 2)
    feature_times = set(times[:split])
    evaluation_times = set(times[split:])
    return (
        [record for record in ordered if str(record["signal_time_utc"]) in feature_times],
        [record for record in ordered if str(record["signal_time_utc"]) in evaluation_times],
    )


def _walk_forward_folds(
    ordered: list[dict[str, Any]],
    *,
    max_folds: int = 3,
) -> tuple[list[dict[str, object]], list[dict[str, Any]]]:
    times = _unique_signal_times(ordered)
    if len(times) < 2:
        return [], []
    fold_count = min(max_folds, len(times) - 1)
    boundaries = [(index * len(times)) // (fold_count + 1) for index in range(fold_count + 2)]
    boundaries[-1] = len(times)
    folds: list[dict[str, object]] = []
    evaluation_records: list[dict[str, Any]] = []
    for fold_index in range(1, len(boundaries) - 1):
        fit_times = set(times[: boundaries[fold_index]])
        eval_times = set(times[boundaries[fold_index] : boundaries[fold_index + 1]])
        fit_records = [record for record in ordered if str(record["signal_time_utc"]) in fit_times]
        eval_records = [record for record in ordered if str(record["signal_time_utc"]) in eval_times]
        if not fit_records or not eval_records:
            continue
        evaluation_records.extend(eval_records)
        fit_metadata = _window_metadata(fit_records)
        eval_metadata = _window_metadata(eval_records)
        folds.append(
            {
                "fold": len(folds) + 1,
                "fit_window": fit_metadata,
                "evaluation_window": {
                    **eval_metadata,
                    "summary": summarize_returns([record["return"] for record in eval_records]),
                },
                "fit_end_before_evaluation_start": (
                    fit_metadata["end_utc"] is not None
                    and eval_metadata["start_utc"] is not None
                    and str(fit_metadata["end_utc"]) < str(eval_metadata["start_utc"])
                ),
                "expanding_prior_window": True,
            }
        )
    return folds, evaluation_records


def _unique_signal_times(records: list[dict[str, Any]]) -> list[str]:
    return sorted({str(record["signal_time_utc"]) for record in records})


def _window_metadata(records: list[dict[str, Any]]) -> dict[str, object]:
    if not records:
        return {"events": 0, "start_utc": None, "end_utc": None}
    return {
        "events": len(records),
        "start_utc": min(str(record["signal_time_utc"]) for record in records),
        "end_utc": max(str(record["signal_time_utc"]) for record in records),
    }


def _default_assumption_grid() -> list[BacktestAssumptions]:
    return [
        BacktestAssumptions(fee_bps=fee, spread_bps=spread, slippage_bps=slippage, holding_bars=holding)
        for fee, spread, slippage, holding in product([0.0, 10.0], [0.0, 5.0], [0.0, 5.0], [1, 3])
    ]


def _diagnostic_flags() -> dict[str, bool | str]:
    return {
        "diagnostic_event_study_only": True,
        "not_portfolio_simulator": True,
        "no_execution_model": True,
        "hypothetical_diagnostic_only": True,
        "not_financial_advice": True,
        "research_warning": (
            "Backtest output is hypothetical diagnostic research only. "
            "It is not financial advice, not a portfolio simulator, and no order was placed."
        ),
    }
