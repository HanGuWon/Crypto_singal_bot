from __future__ import annotations

from dataclasses import dataclass, field

from crypto_signal_bot.data.models import Candle, DataQualityReport
from crypto_signal_bot.features.bottoming import BottomingConfig, compute_bottoming_state
from crypto_signal_bot.features.indicators import (
    clip_score,
    stochastic_cross_down,
    stochastic_cross_up,
    stochastic_kd,
)
from crypto_signal_bot.features.three_tick import ThreeTickConfig, compute_three_tick_state
from crypto_signal_bot.signals.risk_filters import has_critical_risk
from crypto_signal_bot.signals.schemas import SignalCandidate

ENTRY_TIMING_BLOCKING_STATUSES = {"falling_knife_suppress", "invalidated"}


@dataclass(frozen=True)
class EntryTimingConfig:
    strategy: str = "three_tick_bottoming"
    min_upside_score: float = 60.0
    min_liquidity_component: float = 50.0
    stochastic_k_period: int = 14
    stochastic_k_smoothing: int = 3
    stochastic_d_period: int = 3
    three_tick: ThreeTickConfig = field(default_factory=ThreeTickConfig)
    bottoming: BottomingConfig = field(default_factory=BottomingConfig)


@dataclass(frozen=True)
class EntryTimingResult:
    status: str
    entry_timing_score: float
    research_priority_score: float
    strategy: str
    strategy_timeframe: str
    reason_codes: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    invalidation_condition: str = (
        "Entry timing research view invalidates if data becomes stale, support fails, "
        "falling-knife risk appears, or stochastic confirmation turns down."
    )


class EntryTimingScorer:
    def __init__(self, config: EntryTimingConfig | None = None) -> None:
        self.config = config or EntryTimingConfig()

    def score(
        self,
        candidate: SignalCandidate,
        candles: list[Candle],
        *,
        quality: DataQualityReport | None = None,
    ) -> EntryTimingResult:
        closed = [candle for candle in candles if candle.is_closed]
        reasons: list[str] = []
        risks: list[str] = []
        if not closed:
            return self._blocked(
                candidate,
                "invalidated",
                ["no_closed_candles"],
                ["failed_data_quality"],
            )

        quality_status = quality.status if quality is not None else candidate.data_quality_status
        quality_warnings = quality.warnings if quality is not None else []
        if (
            quality_status != "pass"
            or not candidate.is_closed_candle_signal
            or "stale_data" in candidate.risk_flags
            or "incomplete_current_candle" in candidate.risk_flags
            or "stale_data" in quality_warnings
            or "incomplete_current_candle" in quality_warnings
        ):
            return self._blocked(
                candidate,
                "invalidated",
                ["data_quality_blocks_entry_timing"],
                _unique([
                    *candidate.risk_flags,
                    *quality_warnings,
                    "entry_timing_data_quality_block",
                ]),
            )

        if has_critical_risk(candidate.risk_flags):
            return self._blocked(
                candidate,
                "invalidated",
                ["critical_risk_blocks_entry_timing"],
                candidate.risk_flags,
            )

        three_tick = compute_three_tick_state(closed, self.config.three_tick)
        bottoming = compute_bottoming_state(closed, self.config.bottoming)
        reasons.extend(f"three_tick:{reason}" for reason in three_tick.reason_codes)
        reasons.extend(f"bottoming:{reason}" for reason in bottoming.reason_codes)
        risks.extend(three_tick.risk_flags)
        risks.extend(bottoming.risk_flags)

        highs = [candle.high for candle in closed]
        lows = [candle.low for candle in closed]
        closes = [candle.close for candle in closed]
        k_values, d_values = stochastic_kd(
            highs,
            lows,
            closes,
            k_period=self.config.stochastic_k_period,
            k_smoothing=self.config.stochastic_k_smoothing,
            d_period=self.config.stochastic_d_period,
        )
        stoch_cross_up = stochastic_cross_up(k_values, d_values)
        stoch_cross_down = stochastic_cross_down(k_values, d_values)
        if stoch_cross_up:
            reasons.append("stochastic_confirmation_cross_up")
        if stoch_cross_down:
            reasons.append("stochastic_invalidation_cross_down")
            risks.append("stochastic_cross_down")

        timing_score = self._timing_score(
            candidate,
            three_tick_status=three_tick.status,
            bottoming_status=bottoming.status,
            stoch_cross_up=stoch_cross_up,
            stoch_cross_down=stoch_cross_down,
        )
        liquidity_ok = candidate.component_scores.get("liquidity", 0.0) >= self.config.min_liquidity_component
        if not liquidity_ok:
            risks.append("entry_timing_liquidity_filter")

        if three_tick.status in ENTRY_TIMING_BLOCKING_STATUSES:
            risks.append(three_tick.status)
            return self._result(
                candidate,
                status="falling_knife_suppress" if three_tick.status == "falling_knife_suppress" else "invalidated",
                timing_score=timing_score,
                reasons=reasons,
                risks=risks,
            )
        if bottoming.status in ENTRY_TIMING_BLOCKING_STATUSES:
            risks.append(bottoming.status)
            return self._result(
                candidate,
                status="falling_knife_suppress" if bottoming.status == "falling_knife_suppress" else "invalidated",
                timing_score=timing_score,
                reasons=reasons,
                risks=risks,
            )
        if stoch_cross_down and (three_tick.status == "watch" or bottoming.status in {"watch", "confirmed"}):
            return self._result(
                candidate,
                status="invalidated",
                timing_score=timing_score,
                reasons=reasons,
                risks=risks,
            )

        setup_confirmed = (
            (three_tick.status == "watch" and stoch_cross_up)
            or bottoming.status == "confirmed"
        )
        if (
            setup_confirmed
            and liquidity_ok
            and candidate.confidence != "low"
            and candidate.score >= self.config.min_upside_score
        ):
            status = "confirmed_candidate"
            reasons.append("second_stage_confirmation")
        elif three_tick.status == "watch" or bottoming.status in {"watch", "confirmed"}:
            status = "watch"
            reasons.append("entry_timing_watch")
        elif three_tick.status == "forming" or bottoming.status == "forming":
            status = "forming"
            reasons.append("entry_timing_forming")
        else:
            status = "not_ready"
            reasons.append("entry_timing_not_ready")

        return self._result(
            candidate,
            status=status,
            timing_score=timing_score,
            reasons=reasons,
            risks=risks,
        )

    def _timing_score(
        self,
        candidate: SignalCandidate,
        *,
        three_tick_status: str,
        bottoming_status: str,
        stoch_cross_up: bool,
        stoch_cross_down: bool,
    ) -> float:
        score = 20.0
        score += {
            "watch": 30.0,
            "forming": 12.0,
            "not_ready": 0.0,
            "flow_broken_reset": -10.0,
            "falling_knife_suppress": -30.0,
            "invalidated": -35.0,
        }.get(three_tick_status, 0.0)
        score += {
            "confirmed": 25.0,
            "watch": 15.0,
            "forming": 8.0,
            "not_ready": 0.0,
            "falling_knife_suppress": -25.0,
            "invalidated": -30.0,
        }.get(bottoming_status, 0.0)
        if stoch_cross_up:
            score += 15.0
        if stoch_cross_down:
            score -= 20.0
        if candidate.component_scores.get("liquidity", 0.0) >= 70:
            score += 5.0
        if candidate.component_scores.get("volume", 0.0) >= 60:
            score += 5.0
        return round(clip_score(score), 2)

    def _blocked(
        self,
        candidate: SignalCandidate,
        status: str,
        reasons: list[str],
        risks: list[str],
    ) -> EntryTimingResult:
        return self._result(
            candidate,
            status=status,
            timing_score=0.0,
            reasons=reasons,
            risks=risks,
        )

    def _result(
        self,
        candidate: SignalCandidate,
        *,
        status: str,
        timing_score: float,
        reasons: list[str],
        risks: list[str],
    ) -> EntryTimingResult:
        if status in ENTRY_TIMING_BLOCKING_STATUSES:
            priority = min(candidate.score * 0.35, 35.0)
        else:
            priority = candidate.score * 0.70 + timing_score * 0.30
        return EntryTimingResult(
            status=status,
            entry_timing_score=round(clip_score(timing_score), 2),
            research_priority_score=round(clip_score(priority), 2),
            strategy=self.config.strategy,
            strategy_timeframe=candidate.interval,
            reason_codes=_unique(reasons)[:12],
            risk_flags=_unique(risks)[:12],
        )


def apply_entry_timing_result(
    candidate: SignalCandidate,
    result: EntryTimingResult,
) -> SignalCandidate:
    data = candidate.to_dict()
    data.update(
        {
            "entry_timing_status": result.status,
            "entry_timing_score": result.entry_timing_score,
            "research_priority_score": result.research_priority_score,
            "entry_strategy": result.strategy,
            "entry_strategy_timeframe": result.strategy_timeframe,
            "entry_reason_codes": result.reason_codes,
            "entry_risk_flags": result.risk_flags,
            "entry_invalidation_condition": result.invalidation_condition,
        }
    )
    return SignalCandidate(**data)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
