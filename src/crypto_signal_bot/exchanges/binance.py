from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from crypto_signal_bot.data.models import (
    Candle,
    MarketSymbol,
    OrderBook,
    PriceLevel,
    Ticker,
    utc_now,
)
from crypto_signal_bot.exchanges.base import ExchangeClientError, ExchangeRateLimitError
from crypto_signal_bot.exchanges.rate_limit import BinanceWeightLimiter, RetryPolicy, parse_retry_after_seconds
from crypto_signal_bot.exchanges.safety import assert_public_endpoint

try:  # pragma: no cover - exercised when httpx is installed
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


class BinancePublicClient:
    exchange = "binance"

    def __init__(
        self,
        base_url: str = "https://data-api.binance.vision",
        *,
        http_client: Any | None = None,
        timeout: float = 10.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.retry_policy = retry_policy or RetryPolicy()
        self.limiter = BinanceWeightLimiter()
        if http_client is not None:
            self.http_client = http_client
        elif httpx is not None:
            self.http_client = httpx.Client(timeout=timeout)
        else:
            raise ExchangeClientError("httpx is required for live Binance requests.")
        self.cooldown_until_monotonic = 0.0

    def get_markets(self, quote: str = "USDT") -> list[MarketSymbol]:
        payload = self._get("/api/v3/exchangeInfo", params={}, weight=20)
        self._update_rate_limits_from_exchange_info(payload)
        symbols = [parse_binance_symbol(item) for item in payload.get("symbols", [])]
        return [symbol for symbol in symbols if symbol.quote_asset == quote]

    def get_candles(self, symbol: str, interval: str = "5m", limit: int = 200) -> list[Candle]:
        payload = self._get(
            "/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": min(limit, 1000)},
            weight=2,
        )
        return [parse_binance_kline(row, symbol=symbol, interval=interval) for row in payload]

    def get_ticker(self, symbol: str | None = None) -> list[Ticker]:
        params = {"symbol": symbol} if symbol else {"type": "MINI"}
        payload = self._get("/api/v3/ticker/24hr", params=params, weight=2 if symbol else 80)
        if isinstance(payload, dict):
            payload = [payload]
        return [parse_binance_ticker(item) for item in payload]

    def get_orderbook(self, symbol: str, limit: int = 100) -> OrderBook:
        payload = self._get(
            "/api/v3/depth",
            params={"symbol": symbol, "limit": limit},
            weight=binance_depth_request_weight(limit),
        )
        return parse_binance_orderbook(payload, symbol=symbol)

    def _get(self, path: str, *, params: dict[str, Any], weight: int) -> Any:
        assert_public_endpoint(self.exchange, "GET", path)
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            if time.monotonic() < self.cooldown_until_monotonic:
                raise ExchangeRateLimitError("Binance client is cooling down after a rate-limit block.")
            if self.limiter.should_backoff(weight):
                time.sleep(self.retry_policy.sleep_for_attempt(attempt))
            response = self.http_client.get(url, params=params, headers={"Accept": "application/json"})
            self.limiter.update_from_headers(dict(response.headers))
            retry_after = _retry_after_seconds(response)
            if response.status_code == 418:
                if retry_after is not None:
                    self.cooldown_until_monotonic = time.monotonic() + retry_after
                raise ExchangeRateLimitError("Binance temporary block returned HTTP 418.")
            if response.status_code == 429:
                time.sleep(self.retry_policy.sleep_for_attempt(attempt, retry_after=retry_after))
                last_error = ExchangeRateLimitError("Binance rate limit returned HTTP 429.")
                continue
            if response.status_code >= 500:
                time.sleep(self.retry_policy.sleep_for_attempt(attempt))
                last_error = ExchangeClientError(f"Binance server error HTTP {response.status_code}.")
                continue
            if response.status_code >= 400:
                raise ExchangeClientError(f"Binance request failed HTTP {response.status_code}.")
            return response.json()
        if last_error:
            raise last_error
        raise ExchangeClientError("Binance request failed.")

    def _update_rate_limits_from_exchange_info(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        for item in payload.get("rateLimits", []):
            if not isinstance(item, dict):
                continue
            try:
                interval_num = int(item.get("intervalNum") or 0)
            except (TypeError, ValueError):
                continue
            if (
                item.get("rateLimitType") == "REQUEST_WEIGHT"
                and item.get("interval") == "MINUTE"
                and interval_num == 1
            ):
                try:
                    self.limiter.max_weight_per_minute = int(item["limit"])
                except (KeyError, TypeError, ValueError):
                    return
                return


def parse_binance_symbol(item: dict[str, Any]) -> MarketSymbol:
    status = str(item.get("status", ""))
    quote = str(item.get("quoteAsset", ""))
    base = str(item.get("baseAsset", ""))
    spot_allowed = bool(item.get("isSpotTradingAllowed", False))
    return MarketSymbol(
        exchange="binance",
        raw_symbol=str(item["symbol"]),
        base_asset=base,
        quote_asset=quote,
        status="TRADING" if status == "TRADING" and spot_allowed else status or "INACTIVE",
    )


def parse_binance_kline(row: list[Any], *, symbol: str, interval: str) -> Candle:
    open_ms = int(row[0])
    close_ms = int(row[6])
    close_time = datetime.fromtimestamp(close_ms / 1000, tz=UTC)
    return Candle(
        exchange="binance",
        symbol=symbol,
        interval=interval,
        open_time_utc=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
        close_time_utc=close_time,
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        base_volume=float(row[5]),
        quote_volume=float(row[7]),
        trade_count=int(row[8]) if row[8] is not None else None,
        is_closed=close_time <= utc_now(),
    )


def parse_binance_ticker(item: dict[str, Any]) -> Ticker:
    close_time = int(item.get("closeTime") or int(utc_now().timestamp() * 1000))
    return Ticker(
        exchange="binance",
        symbol=str(item["symbol"]),
        price=float(item["lastPrice"]),
        quote_volume_24h=float(item.get("quoteVolume") or 0.0),
        base_volume_24h=float(item.get("volume") or 0.0),
        price_change_pct_24h=float(item.get("priceChangePercent") or 0.0),
        event_time_utc=datetime.fromtimestamp(close_time / 1000, tz=UTC),
    )


def parse_binance_orderbook(item: dict[str, Any], *, symbol: str) -> OrderBook:
    bids = [PriceLevel(float(price), float(quantity)) for price, quantity in item.get("bids", [])]
    asks = [PriceLevel(float(price), float(quantity)) for price, quantity in item.get("asks", [])]
    return OrderBook("binance", symbol, utc_now(), bids=bids, asks=asks)


def binance_depth_request_weight(limit: int) -> int:
    if limit <= 100:
        return 5
    if limit <= 500:
        return 25
    if limit <= 1000:
        return 50
    return 250


def _retry_after_seconds(response: Any) -> float | None:
    value = response.headers.get("Retry-After") if hasattr(response, "headers") else None
    return parse_retry_after_seconds(value)
