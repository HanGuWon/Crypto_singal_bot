from __future__ import annotations

from datetime import UTC, datetime

from conftest import make_candidate
from crypto_signal_bot.features.feature_builder import FeatureSnapshot
from crypto_signal_bot.signals.binance_liquid_momentum import (
    RESEARCH_ONLY_WARNING,
    apply_binance_liquid_momentum_v2,
    build_strategy_candidate,
)


def test_binance_liquid_momentum_v2_adds_research_only_fields() -> None:
    candidate = make_candidate(
        symbol="ALPHAUSDT",
        quote_asset="USDT",
        confidence="high",
        history_bars_available=120,
        benchmark_available=True,
        component_scores={
            "trend": 88.0,
            "momentum": 82.0,
            "volume": 78.0,
            "liquidity": 91.0,
            "breakout": 72.0,
            "relative_strength": 80.0,
            "market_regime": 62.0,
        },
    )
    snapshot = _snapshot(
        symbol="ALPHAUSDT",
        quote_volume=6_000_000.0,
        ret_15m=0.01,
        ret_1h=0.025,
        ret_4h=0.06,
        relative_strength_1h=0.02,
    )

    updated = apply_binance_liquid_momentum_v2(candidate, snapshot)

    assert updated.entry_strategy == "binance_liquid_momentum_v2"
    assert updated.directional_view == "upside_watch"
    assert updated.evidence_grade in {"A", "B", "C"}
    assert updated.why_not_trade_signal == "Research screen only; not a trade instruction."
    assert updated.next_validation_needed
    assert updated.strategy_overlay["no_advice_warning"] == RESEARCH_ONLY_WARNING
    assert updated.research_priority_score is not None
    assert "buy now" not in str(updated.to_dict()).lower()


def test_binance_liquid_momentum_v2_caps_high_manipulation_risk() -> None:
    candidate = make_candidate(
        symbol="THINUSDT",
        quote_asset="USDT",
        confidence="high",
        history_bars_available=120,
        benchmark_available=True,
    )
    snapshot = _snapshot(
        symbol="THINUSDT",
        quote_volume=25_000.0,
        volume_z=8.0,
        ret_15m=0.06,
        ret_1h=0.065,
        upper_wick_ratio=0.75,
    )

    overlay = build_strategy_candidate(candidate, snapshot)
    updated = apply_binance_liquid_momentum_v2(candidate, snapshot)

    assert overlay.manipulation_risk["risk_level"] == "high"
    assert overlay.evidence_grade == "D"
    assert "high_manipulation_risk" in updated.risk_flags
    assert "low_evidence_grade" in updated.risk_flags


def _snapshot(
    *,
    symbol: str,
    quote_volume: float,
    volume_z: float = 2.5,
    ret_15m: float = 0.008,
    ret_1h: float = 0.018,
    ret_4h: float = 0.04,
    relative_strength_1h: float = 0.012,
    upper_wick_ratio: float = 0.15,
) -> FeatureSnapshot:
    now = datetime(2026, 1, 1, 1, tzinfo=UTC)
    return FeatureSnapshot(
        exchange="binance",
        symbol=symbol,
        interval="5m",
        current_price=100.0,
        data_timestamp_utc=now.isoformat(),
        data_freshness_seconds=1.0,
        is_closed_candle_signal=True,
        data_quality_status="pass",
        data_quality_warnings=[],
        values={
            "quote_volume": quote_volume,
            "quote_volume_z_48": volume_z,
            "realized_volatility_20": 0.012,
            "benchmark_ret_1h": 0.004,
            "ret_15m": ret_15m,
            "ret_1h": ret_1h,
            "ret_4h": ret_4h,
            "relative_strength_1h": relative_strength_1h,
            "price_vs_ema20": 0.025,
            "price_vs_ema50": 0.04,
            "ema20_slope": 0.003,
            "breakout_distance_20": 0.01,
            "spread_bps": 5.0,
            "upper_wick_ratio": upper_wick_ratio,
        },
    )
