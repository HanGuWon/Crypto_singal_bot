from __future__ import annotations

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
    symbol_conditions: dict[str, dict[str, Any]] | None = None,
    assumptions_grid: list[BacktestAssumptions] | None = None,
) -> dict[str, object]:
    symbol_conditions = symbol_conditions or {}
    base_assumptions = BacktestAssumptions()
    records = _event_records(candles_by_symbol, signal_indices_by_symbol, base_assumptions, symbol_conditions)
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


def _walk_forward_diagnostic(records: list[dict[str, Any]]) -> dict[str, object]:
    ordered = sorted(records, key=lambda record: str(record["signal_time_utc"]))
    split = len(ordered) // 2
    feature_window = ordered[:split]
    evaluation_window = ordered[split:]
    return {
        "feature_scoring_window": _window_metadata(feature_window),
        "evaluation_window": {
            **_window_metadata(evaluation_window),
            "summary": summarize_returns([record["return"] for record in evaluation_window]),
        },
        "no_future_feature_normalization": True,
    }


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
