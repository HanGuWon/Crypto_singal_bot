from __future__ import annotations

import json
from datetime import timedelta

import pytest

from crypto_signal_bot.backtest.engine import (
    BacktestAssumptions,
    PortfolioSimulationConfig,
    diagnostic_event_study,
    event_study_next_open,
    research_portfolio_simulation,
)
from crypto_signal_bot.backtest.leakage_checks import assert_next_candle_entry
from crypto_signal_bot.backtest.metrics import summarize_returns
from crypto_signal_bot.data.collector import make_mock_candles


def test_entry_must_be_after_signal_close() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=5) if c.symbol == "BTCUSDT"]
    assert_next_candle_entry(candles[0], candles[1])
    bad_entry = candles[1].__class__(
        **{**candles[1].__dict__, "open_time_utc": candles[0].close_time_utc - timedelta(seconds=1)}
    )
    with pytest.raises(AssertionError):
        assert_next_candle_entry(candles[0], bad_entry)


def test_backtest_output_is_marked_diagnostic_only() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=80) if c.symbol == "BTCUSDT"]
    metrics = event_study_next_open(candles, [50])
    assert metrics["diagnostic_event_study_only"] is True
    assert "diagnostic research only" in str(metrics["research_warning"])
    assert metrics["not_portfolio_simulator"] is True
    assert metrics["no_execution_model"] is True


def test_incomplete_candles_are_excluded() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=80) if c.symbol == "BTCUSDT"]
    candles[50] = candles[50].__class__(**{**candles[50].__dict__, "is_closed": False})

    metrics = event_study_next_open(candles, [50])

    assert metrics["trades"] == 0


def test_costs_reduce_diagnostic_returns() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=80) if c.symbol == "BTCUSDT"]

    no_cost = event_study_next_open(
        candles,
        [50],
        assumptions=BacktestAssumptions(fee_bps=0, spread_bps=0, slippage_bps=0),
    )
    with_cost = event_study_next_open(
        candles,
        [50],
        assumptions=BacktestAssumptions(fee_bps=20, spread_bps=10, slippage_bps=10),
    )

    assert float(with_cost["average_return"]) < float(no_cost["average_return"])


def test_return_summary_includes_risk_distribution_metrics() -> None:
    summary = summarize_returns([0.10, -0.05, 0.02, -0.01, -0.20])

    assert summary["trades"] == 5.0
    assert summary["average_win"] == pytest.approx(0.06)
    assert summary["average_loss"] < 0
    assert summary["gain_loss_factor"] > 0
    assert summary["profit_factor"] == summary["gain_loss_factor"]
    assert summary["win_loss_ratio"] > 0
    assert summary["sortino"] != 0
    assert summary["worst_return"] == -0.20
    assert summary["tail_loss_5pct"] == -0.20


def test_benchmark_windows_align_point_in_time() -> None:
    candles_by_symbol = _mock_universe(limit=100)
    signal_indices = {symbol: [50, 70] for symbol in candles_by_symbol}

    metrics = diagnostic_event_study(candles_by_symbol, signal_indices, benchmark_symbol="BTCUSDT")

    benchmark = metrics["benchmark_diagnostics"]
    assert benchmark["windows_aligned_point_in_time"] is True
    assert benchmark["benchmark_return"]["trades"] == 6.0


def test_benchmark_set_diagnostics_include_btc_eth_and_missing_symbols() -> None:
    candles_by_symbol = _mock_universe(limit=100)
    signal_indices = {symbol: [50, 70] for symbol in candles_by_symbol}

    metrics = diagnostic_event_study(
        candles_by_symbol,
        signal_indices,
        benchmark_symbol="BTCUSDT",
        benchmark_symbols=("BTCUSDT", "ETHUSDT", "MISSINGUSDT"),
    )

    benchmark_set = metrics["benchmark_set_diagnostics"]
    assert benchmark_set["windows_aligned_point_in_time"] is True
    assert benchmark_set["requested_symbols"] == ["BTCUSDT", "ETHUSDT", "MISSINGUSDT"]
    assert benchmark_set["available_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert benchmark_set["missing_symbols"] == ["MISSINGUSDT"]
    assert benchmark_set["benchmark_return_by_symbol"]["BTCUSDT"]["trades"] == 6.0
    assert benchmark_set["benchmark_return_by_symbol"]["ETHUSDT"]["trades"] == 6.0


def test_universe_diagnostics_track_missing_and_empty_signal_assets() -> None:
    candles_by_symbol = _mock_universe(limit=100)
    signal_indices = {
        **{symbol: [50] for symbol in candles_by_symbol},
        "MISSINGUSDT": [50],
        "EMPTYUSDT": [50],
    }
    candles_by_symbol["EMPTYUSDT"] = []

    metrics = diagnostic_event_study(candles_by_symbol, signal_indices, benchmark_symbol="BTCUSDT")

    universe = metrics["universe_diagnostics"]
    assert universe["missing_signal_symbols"] == ["MISSINGUSDT"]
    assert universe["empty_candle_symbols"] == ["EMPTYUSDT"]
    assert universe["delisted_or_missing_asset_candidates"] == ["MISSINGUSDT", "EMPTYUSDT"]
    assert universe["missing_or_empty_symbol_count"] == 2
    assert universe["survivorship_bias_audit_only"] is True
    assert universe["not_complete_delisting_database"] is True


def test_diagnostic_baselines_use_same_point_in_time_windows() -> None:
    candles_by_symbol = _mock_universe(limit=100)
    signal_indices = {symbol: [50, 70] for symbol in candles_by_symbol}

    metrics = diagnostic_event_study(candles_by_symbol, signal_indices, benchmark_symbol="BTCUSDT")

    baselines = metrics["baseline_diagnostics"]
    assert baselines["windows_aligned_point_in_time"] is True
    assert baselines["deterministic_random_symbol_return"]["trades"] == 6.0
    assert baselines["liquidity_ranked_symbol_return"]["trades"] == 6.0
    assert baselines["top_volume_equal_weight_basket_return"]["trades"] == 6.0
    assert baselines["top_volume_basket_size"] == 3
    assert baselines["top_volume_basket_point_in_time"] is True
    assert "not portfolio execution models" in baselines["baseline_notes"]


def test_event_exposure_diagnostics_are_event_overlap_only() -> None:
    candles_by_symbol = _mock_universe(limit=100)
    signal_indices = {symbol: [50, 51] for symbol in candles_by_symbol}

    metrics = diagnostic_event_study(candles_by_symbol, signal_indices, benchmark_symbol="BTCUSDT")

    exposure = metrics["event_exposure_diagnostics"]
    assert exposure["events"] == 6
    assert exposure["unique_signal_times"] == 2
    assert exposure["average_events_per_signal_time"] == 3.0
    assert exposure["max_events_same_signal_time"] == 3
    assert exposure["max_overlapping_event_windows"] >= 3
    assert exposure["event_overlap_only"] is True
    assert exposure["not_portfolio_exposure"] is True
    turnover = metrics["turnover_diagnostics"]
    explicit_exposure = metrics["exposure_diagnostics"]
    assert turnover["events"] == 6
    assert turnover["diagnostic_turnover_events_per_signal_time"] == 3.0
    assert turnover["not_order_turnover"] is True
    assert explicit_exposure["max_overlapping_event_windows"] == exposure["max_overlapping_event_windows"]
    assert explicit_exposure["not_account_exposure"] is True


def test_research_portfolio_simulation_enforces_position_cap_and_next_open_entries() -> None:
    candles_by_symbol = _mock_universe(limit=100)
    signal_indices = {symbol: [50] for symbol in candles_by_symbol}

    result = research_portfolio_simulation(
        candles_by_symbol,
        signal_indices,
        config=PortfolioSimulationConfig(max_positions=2),
    )

    assert result["research_portfolio_simulation"] is True
    assert result["next_open_entries_only"] is True
    assert result["closed_candle_signals_only"] is True
    assert result["signals_considered"] == 3
    assert result["selected_trades"] == 2
    assert result["dropped_by_constraint"]["capacity_full"] == 1
    assert result["exposure"]["position_cap_enforced"] is True
    assert result["exposure"]["max_exposure_fraction"] <= 1.0
    assert result["turnover"]["not_order_turnover"] is True
    assert result["no_order_was_placed"] is True


def test_research_portfolio_simulation_filters_risky_candidates() -> None:
    candles_by_symbol = _mock_universe(limit=100)
    signal_indices = {symbol: [50] for symbol in candles_by_symbol}
    conditions = {
        "BTCUSDT": {"data_quality_status": "pass", "risk_flags": [], "symbol_health_status": "healthy"},
        "ETHUSDT": {"data_quality_status": "warn", "risk_flags": ["stale_data"], "symbol_health_status": "healthy"},
        "ALPHAUSDT": {"data_quality_status": "pass", "risk_flags": [], "symbol_health_status": "quarantined"},
    }

    result = research_portfolio_simulation(
        candles_by_symbol,
        signal_indices,
        symbol_conditions=conditions,
        config=PortfolioSimulationConfig(max_positions=3),
    )

    assert result["selected_trades"] == 1
    assert result["dropped_by_constraint"]["data_quality_not_pass"] == 1
    assert result["dropped_by_constraint"]["symbol_quarantined"] == 1
    assert result["return_summary"]["trades"] == 1.0


def test_diagnostic_event_study_includes_research_portfolio_simulation() -> None:
    candles_by_symbol = _mock_universe(limit=100)
    signal_indices = {symbol: [50] for symbol in candles_by_symbol}

    metrics = diagnostic_event_study(candles_by_symbol, signal_indices, benchmark_symbol="BTCUSDT")

    portfolio = metrics["portfolio_simulation"]
    assert portfolio["research_portfolio_simulation"] is True
    assert portfolio["selected_trades"] > 0
    assert portfolio["notification_logic_excluded"] is True
    assert portfolio["research_warning"].endswith("No order was placed.")


def test_diagnostic_event_study_reports_explicit_research_coverage() -> None:
    candles_by_symbol = _mock_universe(limit=120)
    signal_indices = {symbol: [30, 40, 50, 60, 70] for symbol in candles_by_symbol}
    conditions = {
        "BTCUSDT": {"score": 82.0, "risk_flags": ["api_outage"], "api_outage_simulated": True},
        "ETHUSDT": {"score": 71.0, "risk_flags": []},
        "ALPHAUSDT": {"score": 64.0, "risk_flags": []},
    }

    metrics = diagnostic_event_study(
        candles_by_symbol,
        signal_indices,
        benchmark_symbol="BTCUSDT",
        benchmark_symbols=("BTCUSDT", "ETHUSDT"),
        symbol_conditions=conditions,
    )

    summary = metrics["event_return_summary"]
    coverage = metrics["research_diagnostic_coverage"]

    assert summary["trades"] > 0
    assert coverage["public_market_data_only"] is True
    assert coverage["closed_candle_signals_only"] is True
    assert coverage["next_candle_open_entries"] is True
    assert coverage["fee_spread_slippage_model"] is True
    assert coverage["notification_logic_excluded"] is True
    assert all(coverage["event_return_summary_fields"].values())
    assert coverage["benchmark_set_diagnostics"]["point_in_time_windows"] is True
    assert coverage["walk_forward_diagnostics"]["expanding_prior_windows"] is True
    assert coverage["walk_forward_diagnostics"]["no_future_feature_normalization"] is True
    assert coverage["stress_diagnostics"]["api_outage_simulation"] is True
    assert coverage["calibration_diagnostics"]["calibration_available"] is True
    assert coverage["calibration_diagnostics"]["not_predictive_claim"] is True
    assert coverage["research_portfolio_simulation"]["hypothetical_only"] is True
    assert coverage["research_portfolio_simulation"]["position_cap_enforced"] is True
    assert coverage["research_portfolio_simulation"]["no_order_was_placed"] is True
    assert coverage["not_financial_advice"] is True


def test_walk_forward_diagnostics_use_prior_time_windows_only() -> None:
    candles_by_symbol = _mock_universe(limit=110)
    signal_indices = {symbol: [30, 40, 50, 60, 70] for symbol in candles_by_symbol}

    metrics = diagnostic_event_study(candles_by_symbol, signal_indices, benchmark_symbol="BTCUSDT")

    walk_forward = metrics["walk_forward"]
    assert walk_forward["no_future_feature_normalization"] is True
    assert walk_forward["expanding_prior_windows"] is True
    assert walk_forward["fold_count"] >= 2
    assert walk_forward["aggregate_evaluation_summary"]["trades"] > 0
    for fold in walk_forward["folds"]:
        assert fold["fit_end_before_evaluation_start"] is True
        assert fold["fit_window"]["end_utc"] < fold["evaluation_window"]["start_utc"]
        assert fold["evaluation_window"]["summary"]["trades"] > 0


def test_stress_diagnostics_include_volatility_liquidity_benchmark_and_outage_slices() -> None:
    candles_by_symbol = _mock_universe(limit=100)
    signal_indices = {symbol: [50] for symbol in candles_by_symbol}
    conditions = {
        "BTCUSDT": {"risk_flags": ["api_outage"], "api_outage_simulated": True},
        "ETHUSDT": {"risk_flags": []},
        "ALPHAUSDT": {"risk_flags": []},
    }

    metrics = diagnostic_event_study(
        candles_by_symbol,
        signal_indices,
        benchmark_symbol="BTCUSDT",
        symbol_conditions=conditions,
    )

    stress = metrics["stress_diagnostics"]
    assert stress["event_study_stress_only"] is True
    assert stress["not_portfolio_simulator"] is True
    assert "realized_volatility_median" in stress["thresholds"]
    assert stress["high_volatility_windows"]["trades"] >= 1
    assert stress["thin_liquidity_windows"]["trades"] >= 1
    assert "benchmark_drawdown_windows" in stress
    assert stress["api_outage_simulation"]["outage_flagged"]["trades"] == 1.0
    assert stress["api_outage_simulation"]["excluding_outage_flagged"]["trades"] == 2.0


def test_calibration_diagnostics_bucket_condition_scores() -> None:
    candles_by_symbol = _mock_universe(limit=100)
    signal_indices = {symbol: [50] for symbol in candles_by_symbol}
    conditions = {
        "BTCUSDT": {"score": 82.0},
        "ETHUSDT": {"score": 71.0},
        "ALPHAUSDT": {"score": 64.0},
    }

    metrics = diagnostic_event_study(
        candles_by_symbol,
        signal_indices,
        benchmark_symbol="BTCUSDT",
        symbol_conditions=conditions,
    )

    calibration = metrics["calibration_diagnostics"]
    assert calibration["calibration_available"] is True
    assert calibration["not_predictive_claim"] is True
    assert calibration["score_buckets"]["80-89"]["trades"] == 1.0
    assert calibration["score_buckets"]["70-79"]["trades"] == 1.0
    assert calibration["score_buckets"]["60-69"]["trades"] == 1.0


def test_quarantined_and_stale_symbols_are_conditioned_out() -> None:
    candles_by_symbol = _mock_universe(limit=100)
    signal_indices = {symbol: [50] for symbol in candles_by_symbol}
    conditions = {
        "BTCUSDT": {"data_quality_status": "pass", "risk_flags": [], "symbol_health_status": "healthy"},
        "ETHUSDT": {"data_quality_status": "warn", "risk_flags": ["stale_data"], "symbol_health_status": "healthy"},
        "ALPHAUSDT": {"data_quality_status": "pass", "risk_flags": [], "symbol_health_status": "quarantined"},
    }

    metrics = diagnostic_event_study(
        candles_by_symbol,
        signal_indices,
        benchmark_symbol="BTCUSDT",
        symbol_conditions=conditions,
    )
    conditioned = metrics["data_quality_conditioned"]

    assert conditioned["all_eligible_candidates"]["trades"] == 3.0
    assert conditioned["excluding_stale_fail_symbols"]["trades"] == 2.0
    assert conditioned["excluding_quarantined_symbols"]["trades"] == 2.0


def test_diagnostic_output_avoids_forbidden_recommendation_language() -> None:
    candles_by_symbol = _mock_universe(limit=90)
    signal_indices = {symbol: [50] for symbol in candles_by_symbol}

    text = json.dumps(diagnostic_event_study(candles_by_symbol, signal_indices, benchmark_symbol="BTCUSDT"))

    assert "profit_factor" in text
    for forbidden in ["buy now", "sure profit", "guaranteed", "urgent buy", "this is financial advice"]:
        assert forbidden not in text.lower()


def _mock_universe(limit: int):
    candles = make_mock_candles("binance", "USDT", "5m", limit=limit)
    return {
        symbol: [candle for candle in candles if candle.symbol == symbol]
        for symbol in sorted({candle.symbol for candle in candles})
    }
