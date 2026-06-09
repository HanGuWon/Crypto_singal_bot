from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from crypto_signal_bot.data.store import SQLiteStore


@dataclass
class AlertState:
    active: bool = False
    last_score: float | None = None
    last_dedupe_key: str | None = None
    last_alerted_at_utc: datetime | None = None


class AlertStateStore(Protocol):
    def get(self, exchange: str, symbol: str, interval: str, event_type: str) -> AlertState:
        ...

    def set_active(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        event_type: str,
        *,
        active: bool,
        score: float | None,
        dedupe_key: str | None = None,
        alerted_at_utc: datetime | None = None,
    ) -> None:
        ...


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
        dedupe_key: str | None = None,
        alerted_at_utc: datetime | None = None,
    ) -> None:
        state = self.get(exchange, symbol, interval, event_type)
        state.active = active
        state.last_score = score
        state.last_dedupe_key = dedupe_key
        if alerted_at_utc is not None:
            state.last_alerted_at_utc = alerted_at_utc


class SQLiteAlertStateStore:
    def __init__(self, path: str | Path) -> None:
        self.store = SQLiteStore(path)
        self.store.init_schema()

    def get(self, exchange: str, symbol: str, interval: str, event_type: str) -> AlertState:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT active, last_alerted_at_utc, last_score, last_dedupe_key
                FROM alert_state
                WHERE exchange=? AND symbol=? AND interval=? AND event_type=?
                """,
                (exchange, symbol, interval, event_type),
            ).fetchone()
        if row is None:
            return AlertState()
        last_alerted = (
            datetime.fromisoformat(row["last_alerted_at_utc"])
            if row["last_alerted_at_utc"]
            else None
        )
        return AlertState(
            active=bool(row["active"]),
            last_score=None if row["last_score"] is None else float(row["last_score"]),
            last_dedupe_key=row["last_dedupe_key"],
            last_alerted_at_utc=last_alerted,
        )

    def set_active(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        event_type: str,
        *,
        active: bool,
        score: float | None,
        dedupe_key: str | None = None,
        alerted_at_utc: datetime | None = None,
    ) -> None:
        now_text = alerted_at_utc.isoformat() if alerted_at_utc is not None else None
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_state (
                  exchange, symbol, interval, event_type, active,
                  entered_at_utc, exited_at_utc, last_alerted_at_utc,
                  last_score, last_dedupe_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, symbol, interval, event_type) DO UPDATE SET
                  active=excluded.active,
                  exited_at_utc=CASE
                    WHEN excluded.active=0 THEN excluded.exited_at_utc
                    ELSE alert_state.exited_at_utc
                  END,
                  last_alerted_at_utc=COALESCE(excluded.last_alerted_at_utc, alert_state.last_alerted_at_utc),
                  last_score=excluded.last_score,
                  last_dedupe_key=COALESCE(excluded.last_dedupe_key, alert_state.last_dedupe_key)
                """,
                (
                    exchange,
                    symbol,
                    interval,
                    event_type,
                    int(active),
                    now_text if active else None,
                    now_text if not active else None,
                    now_text,
                    score,
                    dedupe_key,
                ),
            )
