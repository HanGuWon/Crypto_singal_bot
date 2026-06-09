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
    symbol_health_status: str = "unknown"
    quarantine_reason: str | None = None
    history_bars_available: int = 0
    benchmark_available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
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
            "symbol_health_status": self.symbol_health_status,
            "quarantine_reason": self.quarantine_reason,
            "history_bars_available": self.history_bars_available,
            "benchmark_available": self.benchmark_available,
        }

    def with_rank(self, rank: int) -> SignalCandidate:
        return SignalCandidate(**{**self.to_dict(), "rank": rank})


@dataclass(frozen=True)
class RankingResult:
    source_run_id: str
    generated_at_utc: str
    candidates: list[SignalCandidate] = field(default_factory=list)
    research_warning: str = "Research watchlist only. Not financial advice. No order was placed."
