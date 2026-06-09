from __future__ import annotations

import re
from dataclasses import dataclass
from re import Pattern

from crypto_signal_bot.exchanges.base import EndpointRejected


@dataclass(frozen=True)
class EndpointRule:
    method: str
    pattern: Pattern[str]

    def matches(self, method: str, path: str) -> bool:
        return self.method == method.upper() and bool(self.pattern.fullmatch(path))


PUBLIC_ENDPOINT_ALLOWLIST: dict[str, tuple[EndpointRule, ...]] = {
    "upbit": (
        EndpointRule("GET", re.compile(r"/v1/market/all")),
        EndpointRule("GET", re.compile(r"/v1/candles/minutes/(1|3|5|10|15|30|60|240)")),
        EndpointRule("GET", re.compile(r"/v1/ticker")),
        EndpointRule("GET", re.compile(r"/v1/orderbook")),
        EndpointRule("GET", re.compile(r"/v1/trades/ticks")),
    ),
    "binance": (
        EndpointRule("GET", re.compile(r"/api/v3/ping")),
        EndpointRule("GET", re.compile(r"/api/v3/time")),
        EndpointRule("GET", re.compile(r"/api/v3/exchangeInfo")),
        EndpointRule("GET", re.compile(r"/api/v3/klines")),
        EndpointRule("GET", re.compile(r"/api/v3/uiKlines")),
        EndpointRule("GET", re.compile(r"/api/v3/ticker")),
        EndpointRule("GET", re.compile(r"/api/v3/ticker/24hr")),
        EndpointRule("GET", re.compile(r"/api/v3/ticker/bookTicker")),
        EndpointRule("GET", re.compile(r"/api/v3/ticker/price")),
        EndpointRule("GET", re.compile(r"/api/v3/depth")),
        EndpointRule("GET", re.compile(r"/api/v3/trades")),
        EndpointRule("GET", re.compile(r"/api/v3/aggTrades")),
        EndpointRule("GET", re.compile(r"/api/v3/avgPrice")),
    ),
}


def assert_public_endpoint(exchange: str, method: str, path: str) -> None:
    rules = PUBLIC_ENDPOINT_ALLOWLIST.get(exchange.lower())
    if not rules:
        raise EndpointRejected(f"Unknown exchange: {exchange}")
    if not any(rule.matches(method, path) for rule in rules):
        raise EndpointRejected(f"Endpoint is not public-allowlisted: {exchange} {method} {path}")
