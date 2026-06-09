from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
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
from crypto_signal_bot.exchanges.rate_limit import RetryPolicy, UpbitRemainingReqLimiter
from crypto_signal_bot.exchanges.safety import assert_public_endpoint
from crypto_signal_bot.features.indicators import interval_to_minutes

try:  # pragma: no cover - exercised when httpx is installed
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


UPBIT_INTERVAL_UNITS = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


class UpbitPublicClient:
    exchange = "upbit"

    def __init__(
        self,
        base_url: str = "https://api.upbit.com",
        *,
        http_client: Any | None = None,
        timeout: float = 10.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.retry_policy = retry_policy or RetryPolicy()
        self.limiter = UpbitRemainingReqLimiter()
        if http_client is not None:
            self.http_client = http_client
        elif httpx is not None:
            self.http_client = httpx.Client(timeout=timeout)
        else:
            raise ExchangeClientError("httpx is required for live Upbit requests.")

    def get_markets(self, quote: str = "KRW") -> list[MarketSymbol]:
        payload = self._get("/v1/market/all", params={"is_details": "true"}, group="market")
        markets = [parse_upbit_market(item) for item in payload]
        return [market for market in markets if market.quote_asset == quote and market.status == "TRADING"]

    def get_candles(self, symbol: str, interval: str = "5m", limit: int = 200) -> list[Candle]:
        unit = UPBIT_INTERVAL_UNITS.get(interval)
        if unit is None:
            raise ValueError(f"Unsupported Upbit minute interval: {interval}")
        path = f"/v1/candles/minutes/{unit}"
        payload = self._get(path, params={"market": symbol, "count": min(limit, 200)}, group="candle")
        candles = [parse_upbit_candle(item, interval=interval) for item in payload]
        return sorted(candles, key=lambda candle: candle.open_time_utc)

    def get_ticker(self, symbols: list[str]) -> list[Ticker]:
        payload = self._get("/v1/ticker", params={"markets": ",".join(symbols)}, group="ticker")
        return [parse_upbit_ticker(item) for item in payload]

    def get_orderbook(self, symbols: list[str]) -> list[OrderBook]:
        payload = self._get("/v1/orderbook", params={"markets": ",".join(symbols)}, group="orderbook")
        return [parse_upbit_orderbook(item) for item in payload]

    def _get(self, path: str, *, params: dict[str, Any], group: str) -> Any:
        assert_public_endpoint(self.exchange, "GET", path)
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            self.limiter.throttle_if_needed(group)
            response = self.http_client.get(url, params=params, headers={"Accept": "application/json"})
            self.limiter.update_from_header(response.headers.get("Remaining-Req"))
            if response.status_code == 418:
                raise ExchangeRateLimitError("Upbit temporary block returned HTTP 418.")
            if response.status_code == 429:
                sleep = self.retry_policy.sleep_for_attempt(attempt)
                time.sleep(sleep)
                last_error = ExchangeRateLimitError("Upbit rate limit returned HTTP 429.")
                continue
            if response.status_code >= 500:
                time.sleep(self.retry_policy.sleep_for_attempt(attempt))
                last_error = ExchangeClientError(f"Upbit server error HTTP {response.status_code}.")
                continue
            if response.status_code >= 400:
                raise ExchangeClientError(f"Upbit request failed HTTP {response.status_code}.")
            return response.json()
        if last_error:
            raise last_error
        raise ExchangeClientError("Upbit request failed.")


def parse_upbit_market(item: dict[str, Any]) -> MarketSymbol:
    raw = str(item["market"])
    quote, base = raw.split("-", 1)
    warning = str(item.get("market_warning", "NONE"))
    status = "TRADING" if warning == "NONE" else "WARNING"
    return MarketSymbol("upbit", raw, base, quote, status)


def parse_upbit_candle(item: dict[str, Any], *, interval: str) -> Candle:
    open_time = datetime.fromisoformat(item["candle_date_time_utc"]).replace(tzinfo=UTC)
    close_time = open_time + timedelta(minutes=interval_to_minutes(interval)) - timedelta(milliseconds=1)
    return Candle(
        exchange="upbit",
        symbol=str(item["market"]),
        interval=interval,
        open_time_utc=open_time,
        close_time_utc=close_time,
        open=float(item["opening_price"]),
        high=float(item["high_price"]),
        low=float(item["low_price"]),
        close=float(item["trade_price"]),
        base_volume=float(item.get("candle_acc_trade_volume") or 0.0),
        quote_volume=float(item.get("candle_acc_trade_price") or 0.0),
        trade_count=None,
        is_closed=close_time <= utc_now(),
    )


def parse_upbit_ticker(item: dict[str, Any]) -> Ticker:
    event_ms = int(item.get("timestamp") or int(utc_now().timestamp() * 1000))
    return Ticker(
        exchange="upbit",
        symbol=str(item["market"]),
        price=float(item["trade_price"]),
        quote_volume_24h=float(item.get("acc_trade_price_24h") or 0.0),
        base_volume_24h=float(item.get("acc_trade_volume_24h") or 0.0),
        price_change_pct_24h=float(item.get("signed_change_rate") or 0.0) * 100,
        event_time_utc=datetime.fromtimestamp(event_ms / 1000, tz=UTC),
    )


def parse_upbit_orderbook(item: dict[str, Any]) -> OrderBook:
    units = item.get("orderbook_units", [])
    bids = [PriceLevel(float(unit["bid_price"]), float(unit["bid_size"])) for unit in units]
    asks = [PriceLevel(float(unit["ask_price"]), float(unit["ask_size"])) for unit in units]
    timestamp = int(item.get("timestamp") or int(utc_now().timestamp() * 1000))
    return OrderBook(
        exchange="upbit",
        symbol=str(item["market"]),
        event_time_utc=datetime.fromtimestamp(timestamp / 1000, tz=UTC),
        bids=bids,
        asks=asks,
    )
