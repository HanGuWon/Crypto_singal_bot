from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.features.feature_builder import FeatureSnapshot
from crypto_signal_bot.features.indicators import clip_score
from crypto_signal_bot.signals.schemas import SignalCandidate

RESEARCH_ONLY_WARNING = "Research only. Not financial advice. No order was placed."
NO_TRADE_SIGNAL = "Research screen only; not a trade instruction."
NEXT_VALIDATION = "Needs closed-candle follow-up and benchmark confirmation."


@dataclass(frozen=True)
class StrategyHypothesis:
    name: str
    directional_view: str
    evidence_grade: str
    required_conditions: list[str]
    falsifiers: list[str]
    risk_suppressors: list[str]
    reason_codes: list[str]


@dataclass(frozen=True)
class StrategyCandidate:
    symbol: str
    base_score: float
    strategy_score: float
    research_priority_score: float
    directional_view: str
    evidence_grade: str
    timeframe_alignment: dict[str, object]
    manipulation_risk: dict[str, object]
    liquidity_regime: str
    benchmark_context: dict[str, object]
    next_review_time_utc: str
    no_advice_warning: str = RESEARCH_ONLY_WARNING
    confidence_calibration: str = "unvalidated"
    why_not_trade_signal: str = NO_TRADE_SIGNAL
    next_validation_needed: str = NEXT_VALIDATION
    component_contributions: dict[str, float] = field(default_factory=dict)
    hypothesis: StrategyHypothesis | None = None
    skipped: bool = False
    skipped_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "base_score": self.base_score,
            "strategy_score": self.strategy_score,
            "research_priority_score": self.research_priority_score,
            "directional_view": self.directional_view,
            "evidence_grade": self.evidence_grade,
            "timeframe_alignment": self.timeframe_alignment,
            "manipulation_risk": self.manipulation_risk,
            "liquidity_regime": self.liquidity_regime,
            "benchmark_context": self.benchmark_context,
            "next_review_time_utc": self.next_review_time_utc,
            "no_advice_warning": self.no_advice_warning,
            "confidence_calibration": self.confidence_calibration,
            "why_not_trade_signal": self.why_not_trade_signal,
            "next_validation_needed": self.next_validation_needed,
            "component_contributions": self.component_contributions,
            "hypothesis": None if self.hypothesis is None else self.hypothesis.__dict__,
            "skipped": self.skipped,
            "skipped_reasons": self.skipped_reasons,
        }


WEIGHTS = {
    "liquidity_quality": 0.20,
    "trend_momentum": 0.20,
    "relative_strength": 0.15,
    "benchmark_regime": 0.15,
    "volume_confirmation": 0.10,
    "volatility_quality": 0.10,
    "timeframe_alignment": 0.10,
}
MAX_COMPONENT_CONTRIBUTION = 20.0


def apply_binance_liquid_momentum_v2(
    candidate: SignalCandidate,
    snapshot: FeatureSnapshot,
    *,
    timeframe_alignment: dict[str, object] | None = None,
    now_utc: datetime | None = None,
) -> SignalCandidate:
    overlay = build_strategy_candidate(
        candidate,
        snapshot,
        timeframe_alignment=timeframe_alignment,
        now_utc=now_utc,
    )
    data = candidate.to_dict()
    reason_codes = overlay.hypothesis.reason_codes if overlay.hypothesis else []
    merged_risks = _unique_strings([*candidate.risk_flags, *_overlay_risk_flags(overlay)])
    merged_drivers = _unique_strings([*reason_codes, *candidate.drivers])[:8]
    data.update(
        {
            "risk_flags": merged_risks,
            "drivers": merged_drivers or candidate.drivers,
            "research_priority_score": overlay.research_priority_score,
            "entry_strategy": "binance_liquid_momentum_v2",
            "entry_timing_status": overlay.directional_view,
            "entry_timing_score": overlay.strategy_score,
            "entry_reason_codes": reason_codes,
            "entry_risk_flags": _overlay_risk_flags(overlay),
            "entry_invalidation_condition": NEXT_VALIDATION,
            "directional_view": overlay.directional_view,
            "confidence_calibration": overlay.confidence_calibration,
            "evidence_grade": overlay.evidence_grade,
            "why_not_trade_signal": overlay.why_not_trade_signal,
            "next_validation_needed": overlay.next_validation_needed,
            "strategy_overlay": overlay.to_dict(),
        }
    )
    return SignalCandidate(**data)


def build_strategy_candidate(
    candidate: SignalCandidate,
    snapshot: FeatureSnapshot,
    *,
    timeframe_alignment: dict[str, object] | None = None,
    now_utc: datetime | None = None,
) -> StrategyCandidate:
    values = snapshot.values
    manipulation = manipulation_risk(values, candidate)
    liquidity_regime = _liquidity_regime(values, candidate)
    benchmark_context = _benchmark_context(values, candidate)
    directional_view, hypothesis = _hypothesis(candidate, values, manipulation)
    component_scores = _strategy_component_scores(candidate, values, timeframe_alignment)
    contributions = {
        name: round(min(score * WEIGHTS[name], MAX_COMPONENT_CONTRIBUTION), 6)
        for name, score in component_scores.items()
    }
    penalty = _strategy_penalty(candidate, manipulation)
    strategy_score = clip_score(sum(contributions.values()) - penalty)
    manipulation_level = _manipulation_risk_level(manipulation)
    manipulation_score = _manipulation_score(manipulation)
    if manipulation_level == "high" and directional_view == "upside_watch":
        strategy_score = min(strategy_score, 59.0)
    if directional_view == "downside_risk_watch":
        strategy_score = max(strategy_score, min(75.0, 45.0 + manipulation_score * 0.2))
    evidence_grade = _evidence_grade(strategy_score, candidate, manipulation)
    priority = _research_priority(strategy_score, candidate.score, directional_view, evidence_grade)
    checked_at = now_utc or datetime.now(tz=UTC)
    return StrategyCandidate(
        symbol=candidate.symbol,
        base_score=candidate.score,
        strategy_score=round(strategy_score, 2),
        research_priority_score=round(priority, 2),
        directional_view=directional_view,
        evidence_grade=evidence_grade,
        timeframe_alignment=timeframe_alignment or {"strategy": "single_timeframe", "aligned": True},
        manipulation_risk=manipulation,
        liquidity_regime=liquidity_regime,
        benchmark_context=benchmark_context,
        next_review_time_utc=(checked_at.astimezone(UTC) + timedelta(minutes=15)).isoformat(),
        confidence_calibration=_confidence_calibration(strategy_score, evidence_grade),
        component_contributions=contributions,
        hypothesis=hypothesis,
        skipped=_is_skipped(candidate),
        skipped_reasons=_skipped_reasons(candidate),
    )


def manipulation_risk(values: dict[str, float | None], candidate: SignalCandidate) -> dict[str, object]:
    reasons: list[str] = []
    score = 0.0
    volume_z = values.get("quote_volume_z_48") or 0.0
    quote_volume = values.get("quote_volume") or 0.0
    spread = values.get("spread_bps")
    upper_wick = values.get("upper_wick_ratio") or 0.0
    ret_15m = values.get("ret_15m") or 0.0
    ret_1h = values.get("ret_1h") or 0.0
    if volume_z >= 5:
        score += 30
        reasons.append("extreme_volume_z")
    if quote_volume < 2_000_000:
        score += 25
        reasons.append("low_quote_volume")
    if spread is not None and spread > 30:
        score += 20
        reasons.append("wide_spread")
    if upper_wick >= 0.6:
        score += 15
        reasons.append("long_upper_wick")
    if ret_15m > 0.04 and ret_1h < ret_15m * 1.5:
        score += 20
        reasons.append("single_candle_jump")
    if candidate.history_bars_available and candidate.history_bars_available < 80:
        score += 20
        reasons.append("insufficient_history")
    if not candidate.benchmark_available:
        score += 15
        reasons.append("missing_benchmark")
    level = "low"
    if score >= 60:
        level = "high"
    elif score >= 30:
        level = "medium"
    return {
        "score": round(clip_score(score), 2),
        "risk_level": level,
        "reason_codes": reasons or ["manipulation_risk_low"],
        "suppresses_upside_alerts": level == "high",
    }


def _manipulation_score(manipulation: dict[str, object]) -> float:
    value = manipulation.get("score", 0.0)
    return float(value) if isinstance(value, int | float) else 0.0


def _manipulation_risk_level(manipulation: dict[str, object]) -> str:
    value = manipulation.get("risk_level", "unknown")
    return str(value)


def _manipulation_reason_codes(manipulation: dict[str, object]) -> list[str]:
    value = manipulation.get("reason_codes", [])
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _strategy_component_scores(
    candidate: SignalCandidate,
    values: dict[str, float | None],
    timeframe_alignment: dict[str, object] | None,
) -> dict[str, float]:
    volume_z = values.get("quote_volume_z_48") or 0.0
    rv = values.get("realized_volatility_20") or 0.0
    benchmark_ret = values.get("benchmark_ret_1h")
    trend_momentum = (
        candidate.component_scores.get("trend", 50.0)
        + candidate.component_scores.get("momentum", 50.0)
    ) / 2
    benchmark_regime = (
        40.0
        if benchmark_ret is not None and benchmark_ret < -0.03
        else candidate.component_scores.get("market_regime", 50.0)
    )
    return {
        "liquidity_quality": candidate.component_scores.get("liquidity", 50.0),
        "trend_momentum": trend_momentum,
        "relative_strength": candidate.component_scores.get("relative_strength", 50.0),
        "benchmark_regime": benchmark_regime,
        "volume_confirmation": clip_score(45 + min(max(volume_z, 0.0), 4.0) * 10),
        "volatility_quality": clip_score(90 - min(rv / 0.08, 1.0) * 45),
        "timeframe_alignment": _timeframe_score(timeframe_alignment),
    }


def _hypothesis(
    candidate: SignalCandidate,
    values: dict[str, float | None],
    manipulation: dict[str, object],
) -> tuple[str, StrategyHypothesis]:
    price_above_ema = (values.get("price_vs_ema20") or 0.0) > 0 and (values.get("price_vs_ema50") or 0.0) > 0
    ema_slope_positive = (values.get("ema20_slope") or 0.0) > 0
    relative_strength = values.get("relative_strength_1h") or 0.0
    ret_1h = values.get("ret_1h") or 0.0
    ret_4h = values.get("ret_4h") or 0.0
    breakdown = values.get("breakout_distance_20")
    if (
        price_above_ema
        and ema_slope_positive
        and ret_1h > 0
        and ret_4h > 0
        and relative_strength > 0
        and _manipulation_risk_level(manipulation) != "high"
        and candidate.benchmark_available
        and candidate.data_quality_status == "pass"
        and candidate.symbol_health_status != "quarantined"
    ):
        return "upside_watch", StrategyHypothesis(
            name="liquid_winner_continuation",
            directional_view="upside_watch",
            evidence_grade="B",
            required_conditions=["trend_confirmed", "positive_relative_strength", "acceptable_liquidity"],
            falsifiers=["benchmark_drawdown", "stale_or_incomplete_data"],
            risk_suppressors=_manipulation_reason_codes(manipulation),
            reason_codes=["liquid_winner_continuation", "requires_confirmation"],
        )
    if (values.get("price_vs_ema20") or 0.0) < 0 and (values.get("ema20_slope") or 0.0) < 0 and relative_strength < 0:
        return "downside_risk_watch", StrategyHypothesis(
            name="relative_weakness_breakdown",
            directional_view="downside_risk_watch",
            evidence_grade="C",
            required_conditions=["negative_relative_strength", "trend_weakness"],
            falsifiers=["close_back_above_ema20", "relative_strength_recovery"],
            risk_suppressors=_manipulation_reason_codes(manipulation),
            reason_codes=["relative_weakness_breakdown", "risk_candidate"],
        )
    if (
        (breakdown or 0.0) < -0.02
        and "falling_knife_suppress" not in candidate.entry_risk_flags
        and _manipulation_risk_level(manipulation) != "high"
        and candidate.benchmark_available
    ):
        return "upside_watch", StrategyHypothesis(
            name="liquid_bottoming_candidate",
            directional_view="upside_watch",
            evidence_grade="C",
            required_conditions=["prior_drawdown", "falling_knife_suppressor_inactive"],
            falsifiers=["support_failure", "benchmark_drawdown"],
            risk_suppressors=_manipulation_reason_codes(manipulation),
            reason_codes=["bottoming_research_candidate", "requires_follow_up_confirmation"],
        )
    return "neutral_holdout", StrategyHypothesis(
        name="insufficient_evidence_holdout",
        directional_view="neutral_holdout",
        evidence_grade="D",
        required_conditions=["more_closed_candle_evidence"],
        falsifiers=[],
        risk_suppressors=_manipulation_reason_codes(manipulation),
        reason_codes=["neutral_holdout", "requires_confirmation"],
    )


def _strategy_penalty(candidate: SignalCandidate, manipulation: dict[str, object]) -> float:
    penalty = _manipulation_score(manipulation) * 0.35
    if candidate.data_quality_status != "pass":
        penalty += 20
    if not candidate.benchmark_available:
        penalty += 15
    if candidate.symbol_health_status == "quarantined":
        penalty += 35
    if candidate.confidence == "low":
        penalty += 10
    return penalty


def _research_priority(strategy_score: float, base_score: float, directional_view: str, evidence_grade: str) -> float:
    if directional_view == "neutral_holdout":
        return min(strategy_score, 50.0)
    grade_bonus = {"A": 8.0, "B": 5.0, "C": 1.0, "D": -8.0}.get(evidence_grade, 0.0)
    return clip_score(strategy_score * 0.72 + base_score * 0.28 + grade_bonus)


def _evidence_grade(
    strategy_score: float,
    candidate: SignalCandidate,
    manipulation: dict[str, object],
) -> str:
    if candidate.data_quality_status != "pass" or candidate.symbol_health_status == "quarantined":
        return "D"
    if not candidate.benchmark_available or manipulation["risk_level"] == "high":
        return "D"
    if strategy_score >= 80 and candidate.confidence == "high":
        return "A"
    if strategy_score >= 70 and candidate.confidence in {"high", "medium"}:
        return "B"
    if strategy_score >= 55:
        return "C"
    return "D"


def _confidence_calibration(strategy_score: float, evidence_grade: str) -> str:
    if evidence_grade == "A" and strategy_score >= 80:
        return "strong"
    if evidence_grade in {"A", "B"} and strategy_score >= 70:
        return "moderate"
    if evidence_grade in {"B", "C"} and strategy_score >= 55:
        return "weak"
    return "unvalidated"


def _liquidity_regime(values: dict[str, float | None], candidate: SignalCandidate) -> str:
    quote_volume = values.get("quote_volume") or 0.0
    if "low_liquidity" in candidate.risk_flags or quote_volume < 2_000_000:
        return "thin"
    if quote_volume >= 20_000_000:
        return "deep"
    return "acceptable"


def _benchmark_context(values: dict[str, float | None], candidate: SignalCandidate) -> dict[str, object]:
    benchmark_ret = values.get("benchmark_ret_1h")
    return {
        "benchmark_available": candidate.benchmark_available,
        "benchmark_ret_1h": benchmark_ret,
        "regime": "risk_off" if benchmark_ret is not None and benchmark_ret < -0.03 else "neutral_or_supportive",
    }


def _timeframe_score(timeframe_alignment: dict[str, object] | None) -> float:
    if not timeframe_alignment:
        return 60.0
    status = str(timeframe_alignment.get("status", "aligned"))
    if "fail" in status or "invalid" in status:
        return 30.0
    return 75.0


def _overlay_risk_flags(overlay: StrategyCandidate) -> list[str]:
    flags: list[str] = []
    if overlay.manipulation_risk["risk_level"] == "high":
        flags.append("high_manipulation_risk")
    if overlay.evidence_grade == "D":
        flags.append("low_evidence_grade")
    if overlay.skipped:
        flags.extend(overlay.skipped_reasons)
    return _unique_strings(flags)


def _is_skipped(candidate: SignalCandidate) -> bool:
    return bool(_skipped_reasons(candidate))


def _skipped_reasons(candidate: SignalCandidate) -> list[str]:
    reasons: list[str] = []
    if candidate.exchange != "binance":
        reasons.append("not_binance_spot")
    if candidate.quote_asset and candidate.quote_asset != "USDT":
        reasons.append("not_usdt_quote")
    if candidate.symbol_health_status == "quarantined":
        reasons.append("symbol_quarantined")
    if not candidate.benchmark_available:
        reasons.append("benchmark_unavailable")
    if not candidate.is_closed_candle_signal:
        reasons.append("incomplete_current_candle")
    if candidate.data_quality_status == "fail":
        reasons.append("failed_data_quality")
    return reasons


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
