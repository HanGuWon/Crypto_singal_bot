from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AlertState:
    active: bool = False
    last_score: float | None = None
    last_rank: int | None = None
    last_dedupe_key: str | None = None


class InMemoryAlertStateStore:
    def __init__(self) -> None:
        self._state: dict[tuple[str, str, str, str], AlertState] = {}

    def get(self, exchange: str, symbol: str, interval: str, event_type: str) -> AlertState:
        key = (exchange, symbol, interval, event_type)
        return self._state.setdefault(key, AlertState())

    def set_active(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        event_type: str,
        *,
        active: bool,
        score: float | None,
        rank: int | None = None,
        dedupe_key: str | None = None,
    ) -> None:
        state = self.get(exchange, symbol, interval, event_type)
        state.active = active
        state.last_score = score
        state.last_rank = rank
        state.last_dedupe_key = dedupe_key
