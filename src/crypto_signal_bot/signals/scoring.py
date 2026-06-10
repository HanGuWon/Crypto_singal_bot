from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from crypto_signal_bot.data.symbols import normalize_symbol
from crypto_signal_bot.features.feature_builder import FeatureSnapshot
from crypto_signal_bot.features.indicators import clip_score, score_from_centered_value
from crypto_signal_bot.features.normalization import winsorized_component
from crypto_signal_bot.signals.risk_filters import RiskThresholds, derive_risk_flags, has_critical_risk
from crypto_signal_bot.signals.schemas import SignalCandidate


@dataclass(frozen=True)
class ScoringWeights:
    trend: float = 0.18
    momentum: float = 0.18
    volume: float = 0.18
    liquidity: float = 0.14
    breakout: float = 0.12
    relative_strength: float = 0.12
    regime: float = 0.08


class ScoringEngine:
    def __init__(
        self,
        weights: ScoringWeights | None = None,
        *,
        min_quote_volume: float = 1_000.0,
        max_spread_bps: float = 30.0,
    ) -> None:
        self.weights = weights or ScoringWeights()
        self.risk_thresholds = RiskThresholds(
            min_quote_volume=min_quote_volume,
            max_spread_bps=max_spread_bps,
        )

    def score(self, snapshot: FeatureSnapshot, *, source_run_id: str | None = None) -> SignalCandidate:
        values = snapshot.values
        trend = _trend_score(values)
        momentum = _momentum_score(values)
        volume = _volume_score(values)
        liquidity = _liquidity_score(values)
        breakout = _breakout_score(values)
        relative_strength = _relative_strength_score(values)
        regime = _market_regime_score(values)

        component_scores = {
            "trend": trend,
            "momentum": momentum,
            "volume": volume,
            "liquidity": liquidity,
            "breakout": breakout,
            "relative_strength": relative_strength,
            "market_regime": regime,
        }
        weighted = (
            trend * self.weights.trend
            + momentum * self.weights.momentum
            + volume * self.weights.volume
            + liquidity * self.weights.liquidity
            + breakout * self.weights.breakout
            + relative_strength * self.weights.relative_strength
            + regime * self.weights.regime
        )
        risk_flags = derive_risk_flags(snapshot, self.risk_thresholds)
        penalty = sum(_penalties(values, risk_flags).values())
        score = clip_score(weighted - penalty)
        confidence = _confidence(component_scores, risk_flags, snapshot.data_quality_status)
        identity = normalize_symbol(snapshot.exchange, snapshot.symbol)
        return SignalCandidate(
            exchange=snapshot.exchange,
            symbol=snapshot.symbol,
            raw_symbol=identity.raw_symbol,
            base_asset=identity.base_asset,
            quote_asset=identity.quote_asset,
            interval=snapshot.interval,
            current_price=snapshot.current_price,
            score=round(score, 2),
            component_scores={key: round(value, 2) for key, value in component_scores.items()},
            confidence=confidence,
            rank=None,
            drivers=_drivers(component_scores, values),
            risk_flags=risk_flags,
            invalidation_condition=(
                "Research view invalidates if score falls below 60, closes below EMA20, "
                "or data becomes stale."
            ),
            data_timestamp_utc=snapshot.data_timestamp_utc,
            source_run_id=source_run_id or str(uuid4()),
            is_closed_candle_signal=snapshot.is_closed_candle_signal,
            data_quality_status=snapshot.data_quality_status,
            data_freshness_seconds=snapshot.data_freshness_seconds,
        )

    def explain(self, snapshot: FeatureSnapshot, candidate: SignalCandidate) -> dict[str, object]:
        contributions = {
            "trend": candidate.component_scores["trend"] * self.weights.trend,
            "momentum": candidate.component_scores["momentum"] * self.weights.momentum,
            "volume": candidate.component_scores["volume"] * self.weights.volume,
            "liquidity": candidate.component_scores["liquidity"] * self.weights.liquidity,
            "breakout": candidate.component_scores["breakout"] * self.weights.breakout,
            "relative_strength": candidate.component_scores["relative_strength"] * self.weights.relative_strength,
            "market_regime": candidate.component_scores["market_regime"] * self.weights.regime,
        }
        penalties = _penalties(snapshot.values, candidate.risk_flags)
        weighted_total = sum(contributions.values())
        penalty_total = sum(penalties.values())
        reconstructed = clip_score(weighted_total - penalty_total)
        return {
            "component_contributions": {key: round(value, 6) for key, value in contributions.items()},
            "weighted_total": round(weighted_total, 6),
            "penalties": {key: round(value, 6) for key, value in penalties.items()},
            "penalty_total": round(penalty_total, 6),
            "reconstructed_score": round(reconstructed, 6),
            "final_score": candidate.score,
            "confidence": candidate.confidence,
            "confidence_reason": _confidence_reason(
                candidate.component_scores,
                candidate.risk_flags,
                snapshot.data_quality_status,
            ),
            "risk_flags": candidate.risk_flags,
            "data_quality_status": snapshot.data_quality_status,
            "data_freshness_seconds": snapshot.data_freshness_seconds,
            "data_quality_warnings": snapshot.data_quality_warnings,
            "symbol_health_status": candidate.symbol_health_status,
            "quarantine_reason": candidate.quarantine_reason,
            "history_bars_available": candidate.history_bars_available,
            "benchmark_available": candidate.benchmark_available,
        }


def _trend_score(values: dict[str, float | None]) -> float:
    score = 35.0
    if (values.get("price_vs_ema20") or 0.0) > 0:
        score += 25
    if (values.get("price_vs_ema50") or 0.0) > 0:
        score += 20
    if (values.get("ema20_slope") or 0.0) > 0:
        score += 20
    return clip_score(score)


def _momentum_score(values: dict[str, float | None]) -> float:
    parts = [
        score_from_centered_value(values.get("ret_15m") or 0.0, 0.015),
        score_from_centered_value(values.get("ret_1h") or 0.0, 0.03),
        score_from_centered_value(values.get("ret_4h") or 0.0, 0.06),
    ]
    return winsorized_component(parts, low=5.0, high=95.0)


def _volume_score(values: dict[str, float | None]) -> float:
    volume_z = values.get("quote_volume_z_48") or 0.0
    acceleration = values.get("volume_acceleration") or 0.0
    return clip_score(50 + min(volume_z, 5) * 7 + min(acceleration, 3) * 8)


def _liquidity_score(values: dict[str, float | None]) -> float:
    quote_volume = values.get("quote_volume") or 0.0
    volume_part = clip_score(35 + min(quote_volume / 1_000_000, 1.0) * 45)
    spread = values.get("spread_bps")
    spread_part = 70.0 if spread is None else clip_score(100 - max(spread, 0) * 2.5)
    return (volume_part + spread_part) / 2


def _breakout_score(values: dict[str, float | None]) -> float:
    distance = values.get("breakout_distance_20")
    if distance is None:
        return 50.0
    if distance >= 0:
        return clip_score(70 + min(distance / 0.03, 1.0) * 30)
    return clip_score(50 + max(distance / 0.03, -1.0) * 20)


def _relative_strength_score(values: dict[str, float | None]) -> float:
    return score_from_centered_value(values.get("relative_strength_1h") or 0.0, 0.03)


def _market_regime_score(values: dict[str, float | None]) -> float:
    benchmark_return = values.get("benchmark_ret_1h")
    if benchmark_return is None:
        return 55.0
    return score_from_centered_value(benchmark_return, 0.04)


def _penalty(values: dict[str, float | None], risk_flags: list[str]) -> float:
    return sum(_penalties(values, risk_flags).values())


def _penalties(values: dict[str, float | None], risk_flags: list[str]) -> dict[str, float]:
    penalties: dict[str, float] = {}
    rv = values.get("realized_volatility_20")
    if rv is not None and rv > 0.05:
        penalties["excessive_volatility"] = min((rv - 0.05) * 300, 15)
    if "wide_spread" in risk_flags:
        penalties["wide_spread"] = 20
    if "low_liquidity" in risk_flags:
        penalties["low_liquidity"] = 25
    if "upper_wick_reversal_risk" in risk_flags:
        penalties["upper_wick_reversal_risk"] = 10
    if has_critical_risk(risk_flags):
        penalties["critical_risk"] = 15
    return penalties


def _confidence(
    component_scores: dict[str, float],
    risk_flags: list[str],
    data_quality_status: str,
) -> str:
    if data_quality_status == "fail" or has_critical_risk(risk_flags):
        return "low"
    constructive = sum(1 for value in component_scores.values() if value >= 60)
    if constructive >= 5 and not risk_flags:
        return "high"
    if constructive >= 3:
        return "medium"
    return "low"


def _confidence_reason(
    component_scores: dict[str, float],
    risk_flags: list[str],
    data_quality_status: str,
) -> str:
    if data_quality_status == "fail":
        return "failed_data_quality"
    if has_critical_risk(risk_flags):
        return "critical_risk_flag"
    constructive = sum(1 for value in component_scores.values() if value >= 60)
    if constructive >= 5 and not risk_flags:
        return "broad_constructive_evidence"
    if constructive >= 3:
        return "mixed_constructive_evidence"
    return "limited_constructive_evidence"


def _drivers(component_scores: dict[str, float], values: dict[str, float | None]) -> list[str]:
    drivers: list[str] = []
    for name, score in sorted(component_scores.items(), key=lambda item: item[1], reverse=True):
        if score >= 65:
            drivers.append(f"{name}_constructive")
    if (values.get("price_vs_ema20") or 0.0) > 0:
        drivers.append("price_above_ema20")
    if (values.get("quote_volume_z_48") or 0.0) > 2:
        drivers.append("volume_expansion")
    if (values.get("relative_strength_1h") or 0.0) > 0:
        drivers.append("positive_relative_strength")
    if not drivers:
        drivers.append("mixed_evidence")
    return drivers[:5]
