from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SignalCandidate:
    exchange: str
    symbol: str
    interval: str
    current_price: float
    score: float
    component_scores: dict[str, float]
    confidence: str
    rank: int | None
    drivers: list[str]
    risk_flags: list[str]
    invalidation_condition: str
    data_timestamp_utc: str
    source_run_id: str
    is_closed_candle_signal: bool
    data_quality_status: str
    data_freshness_seconds: float | None = None
    raw_symbol: str | None = None
    base_asset: str | None = None
    quote_asset: str | None = None
    canonical_asset_id: str | None = None
    canonical_pair_id: str | None = None
    symbol_health_status: str = "unknown"
    quarantine_reason: str | None = None
    history_bars_available: int = 0
    benchmark_available: bool = True
    entry_timing_status: str = "not_evaluated"
    entry_timing_score: float | None = None
    research_priority_score: float | None = None
    entry_strategy: str | None = None
    entry_strategy_timeframe: str | None = None
    entry_reason_codes: list[str] = field(default_factory=list)
    entry_risk_flags: list[str] = field(default_factory=list)
    entry_invalidation_condition: str | None = None
    entry_timeframe_alignment: dict[str, object] | None = None
    entry_confirmation_status: str = "not_requested"
    entry_confirmation_timeframes: list[str] = field(default_factory=list)
    entry_confirmation_reason_codes: list[str] = field(default_factory=list)
    entry_confirmation_risk_flags: list[str] = field(default_factory=list)
    entry_confirmation_details: list[dict[str, object]] = field(default_factory=list)
    directional_view: str = "upside_watch"
    confidence_calibration: str = "unvalidated"
    evidence_grade: str = "C"
    why_not_trade_signal: str = "Research screen only; not a trade instruction."
    next_validation_needed: str = "Needs closed-candle follow-up and benchmark confirmation."
    strategy_overlay: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "raw_symbol": self.raw_symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "canonical_asset_id": self.canonical_asset_id,
            "canonical_pair_id": self.canonical_pair_id,
            "interval": self.interval,
            "current_price": self.current_price,
            "score": self.score,
            "component_scores": self.component_scores,
            "confidence": self.confidence,
            "rank": self.rank,
            "drivers": self.drivers,
            "risk_flags": self.risk_flags,
            "invalidation_condition": self.invalidation_condition,
            "data_timestamp_utc": self.data_timestamp_utc,
            "source_run_id": self.source_run_id,
            "is_closed_candle_signal": self.is_closed_candle_signal,
            "data_quality_status": self.data_quality_status,
            "data_freshness_seconds": self.data_freshness_seconds,
            "symbol_health_status": self.symbol_health_status,
            "quarantine_reason": self.quarantine_reason,
            "history_bars_available": self.history_bars_available,
            "benchmark_available": self.benchmark_available,
            "entry_timing_status": self.entry_timing_status,
            "entry_timing_score": self.entry_timing_score,
            "research_priority_score": self.research_priority_score,
            "entry_strategy": self.entry_strategy,
            "entry_strategy_timeframe": self.entry_strategy_timeframe,
            "entry_reason_codes": self.entry_reason_codes,
            "entry_risk_flags": self.entry_risk_flags,
            "entry_invalidation_condition": self.entry_invalidation_condition,
            "entry_timeframe_alignment": self.entry_timeframe_alignment,
            "entry_confirmation_status": self.entry_confirmation_status,
            "entry_confirmation_timeframes": self.entry_confirmation_timeframes,
            "entry_confirmation_reason_codes": self.entry_confirmation_reason_codes,
            "entry_confirmation_risk_flags": self.entry_confirmation_risk_flags,
            "entry_confirmation_details": self.entry_confirmation_details,
            "directional_view": self.directional_view,
            "confidence_calibration": self.confidence_calibration,
            "evidence_grade": self.evidence_grade,
            "why_not_trade_signal": self.why_not_trade_signal,
            "next_validation_needed": self.next_validation_needed,
            "strategy_overlay": self.strategy_overlay,
        }

    def with_rank(self, rank: int) -> SignalCandidate:
        return SignalCandidate(**{**self.to_dict(), "rank": rank})


@dataclass(frozen=True)
class RankingResult:
    source_run_id: str
    generated_at_utc: str
    candidates: list[SignalCandidate] = field(default_factory=list)
    research_warning: str = "Research watchlist only. Not financial advice. No order was placed."
