from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class MarketSymbol:
    exchange: str
    raw_symbol: str
    base_asset: str
    quote_asset: str
    status: str = "TRADING"

    @property
    def symbol(self) -> str:
        return self.raw_symbol


@dataclass(frozen=True)
class SymbolIdentity:
    exchange: str
    raw_symbol: str
    base_asset: str
    quote_asset: str


@dataclass(frozen=True)
class Candle:
    exchange: str
    symbol: str
    interval: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: float
    high: float
    low: float
    close: float
    base_volume: float | None
    quote_volume: float | None
    trade_count: int | None = None
    is_closed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_time_utc", ensure_utc(self.open_time_utc))
        object.__setattr__(self, "close_time_utc", ensure_utc(self.close_time_utc))

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.exchange,
            self.symbol,
            self.interval,
            self.open_time_utc.isoformat(),
            self.close_time_utc.isoformat(),
            self.open,
            self.high,
            self.low,
            self.close,
            self.base_volume,
            self.quote_volume,
            self.trade_count,
            int(self.is_closed),
        )


@dataclass(frozen=True)
class Ticker:
    exchange: str
    symbol: str
    price: float
    quote_volume_24h: float | None
    base_volume_24h: float | None
    price_change_pct_24h: float | None
    event_time_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_time_utc", ensure_utc(self.event_time_utc))


@dataclass(frozen=True)
class PriceLevel:
    price: float
    quantity: float

    @property
    def quote_notional(self) -> float:
        return self.price * self.quantity


@dataclass(frozen=True)
class OrderBook:
    exchange: str
    symbol: str
    event_time_utc: datetime
    bids: list[PriceLevel] = field(default_factory=list)
    asks: list[PriceLevel] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_time_utc", ensure_utc(self.event_time_utc))

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def spread_bps(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        mid = (self.best_bid + self.best_ask) / 2
        if mid <= 0:
            return None
        return 10000 * (self.best_ask - self.best_bid) / mid


@dataclass(frozen=True)
class DataQualityReport:
    status: str
    warnings: list[str]
    coverage_ratio: float
    stale_seconds: float | None
    latest_close_time_utc: datetime | None
    missing_candle_count: int = 0
    max_gap_intervals: int = 0

    @property
    def passed(self) -> bool:
        return self.status == "pass"


@dataclass(frozen=True)
class SymbolHealth:
    exchange: str
    symbol: str
    interval: str
    status: str
    first_seen_utc: datetime
    last_seen_utc: datetime
    last_good_candle_utc: datetime | None
    history_bars_available: int
    quarantine_reason: str | None
    quarantine_until_utc: datetime | None
    benchmark_available: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "first_seen_utc", ensure_utc(self.first_seen_utc))
        object.__setattr__(self, "last_seen_utc", ensure_utc(self.last_seen_utc))
        if self.last_good_candle_utc is not None:
            object.__setattr__(self, "last_good_candle_utc", ensure_utc(self.last_good_candle_utc))
        if self.quarantine_until_utc is not None:
            object.__setattr__(
                self,
                "quarantine_until_utc",
                ensure_utc(self.quarantine_until_utc),
            )

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.exchange,
            self.symbol,
            self.interval,
            self.status,
            self.first_seen_utc.isoformat(),
            self.last_seen_utc.isoformat(),
            None if self.last_good_candle_utc is None else self.last_good_candle_utc.isoformat(),
            self.history_bars_available,
            self.quarantine_reason,
            None if self.quarantine_until_utc is None else self.quarantine_until_utc.isoformat(),
            int(self.benchmark_available),
            utc_now().isoformat(),
        )
