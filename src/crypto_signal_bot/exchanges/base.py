from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ExchangeClientError(RuntimeError):
    """Base exchange client error."""


class EndpointRejected(ExchangeClientError):
    """Raised when an endpoint is not explicitly public-allowlisted."""


class ExchangeRateLimitError(ExchangeClientError):
    """Raised when the exchange asks the client to back off."""


class PublicMarketDataClient(Protocol):
    exchange: str

    def get_markets(self, quote: str) -> list[Any]:
        ...

    def get_candles(self, symbol: str, interval: str, limit: int) -> list[Any]:
        ...


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    sleep_seconds: float
    reason: str
