from __future__ import annotations

from datetime import UTC, datetime

import pytest

from crypto_signal_bot.exchanges.base import ExchangeClientError, ExchangeRateLimitError
from crypto_signal_bot.exchanges.binance import BinancePublicClient, binance_depth_request_weight
from crypto_signal_bot.exchanges.rate_limit import (
    BinanceWeightLimiter,
    RetryPolicy,
    parse_retry_after_seconds,
    parse_upbit_remaining_req,
)
from crypto_signal_bot.exchanges.upbit import UpbitPublicClient


class FakeResponse:
    def __init__(self, status_code: int, payload: object | None = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        self.headers = headers or {}

    def json(self) -> object:
        return self._payload


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url: str, *, params: dict, headers: dict) -> FakeResponse:
        self.calls.append((url, params, headers))
        return self.responses.pop(0)


def test_upbit_remaining_req_uses_sec_and_ignores_min() -> None:
    group, sec = parse_upbit_remaining_req("group=candle; min=1800; sec=2")
    assert group == "candle"
    assert sec == 2


def test_binance_weight_limiter_tracks_used_weight() -> None:
    limiter = BinanceWeightLimiter(max_weight_per_minute=100, safety_margin=0.8)
    limiter.update_from_headers({"X-MBX-USED-WEIGHT-1M": "79"})
    assert limiter.should_backoff(1)


def test_binance_depth_weight_depends_on_limit() -> None:
    assert binance_depth_request_weight(100) == 5
    assert binance_depth_request_weight(500) == 25
    assert binance_depth_request_weight(1000) == 50
    assert binance_depth_request_weight(5000) == 250


def test_retry_after_parser_accepts_seconds_and_http_date() -> None:
    now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    assert parse_retry_after_seconds("2.5", now_utc=now) == 2.5
    assert parse_retry_after_seconds("Thu, 01 Jan 2026 00:00:05 GMT", now_utc=now) == 5.0
    assert parse_retry_after_seconds("Thu, 01 Jan 2026 00:00:00 GMT", now_utc=now) == 0.0
    assert parse_retry_after_seconds("not-a-date", now_utc=now) is None


def test_public_clients_do_not_send_origin_header() -> None:
    upbit_http = FakeHttpClient([FakeResponse(200, payload=[])])
    binance_http = FakeHttpClient([FakeResponse(200, payload={"symbols": []})])

    UpbitPublicClient(http_client=upbit_http)._get("/v1/market/all", params={"is_details": "true"}, group="market")
    BinancePublicClient(http_client=binance_http)._get("/api/v3/exchangeInfo", params={}, weight=20)

    assert "Origin" not in upbit_http.calls[0][2]
    assert "origin" not in {key.lower() for key in upbit_http.calls[0][2]}
    assert "Origin" not in binance_http.calls[0][2]
    assert "origin" not in {key.lower() for key in binance_http.calls[0][2]}


def test_binance_429_retry_after_retries_then_succeeds(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    monkeypatch.setattr("crypto_signal_bot.exchanges.binance.time.sleep", sleeps.append)
    http_client = FakeHttpClient([
        FakeResponse(429, headers={"Retry-After": "2"}),
        FakeResponse(200, payload={"ok": True}),
    ])
    client = BinancePublicClient(
        http_client=http_client,
        retry_policy=RetryPolicy(max_attempts=2, max_sleep_seconds=10, jitter_seconds=0),
    )

    assert client._get("/api/v3/ticker/24hr", params={"symbol": "BTCUSDT"}, weight=2) == {"ok": True}
    assert sleeps == [2.0]
    assert len(http_client.calls) == 2


def test_binance_429_exhaustion_is_bounded(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    monkeypatch.setattr("crypto_signal_bot.exchanges.binance.time.sleep", sleeps.append)
    http_client = FakeHttpClient([FakeResponse(429), FakeResponse(429)])
    client = BinancePublicClient(
        http_client=http_client,
        retry_policy=RetryPolicy(max_attempts=2, jitter_seconds=0),
    )

    with pytest.raises(ExchangeRateLimitError):
        client._get("/api/v3/ticker/24hr", params={"symbol": "BTCUSDT"}, weight=2)
    assert len(http_client.calls) == 2
    assert len(sleeps) == 2


def test_binance_418_sets_cooldown_and_blocks_next_request(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("crypto_signal_bot.exchanges.binance.time.monotonic", lambda: 100.0)
    http_client = FakeHttpClient([FakeResponse(418, headers={"Retry-After": "10"})])
    client = BinancePublicClient(http_client=http_client, retry_policy=RetryPolicy(max_attempts=1))

    with pytest.raises(ExchangeRateLimitError):
        client._get("/api/v3/ticker/24hr", params={"symbol": "BTCUSDT"}, weight=2)
    with pytest.raises(ExchangeRateLimitError):
        client._get("/api/v3/ticker/24hr", params={"symbol": "BTCUSDT"}, weight=2)
    assert len(http_client.calls) == 1


def test_upbit_418_sets_cooldown_and_blocks_next_request(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("crypto_signal_bot.exchanges.upbit.time.monotonic", lambda: 100.0)
    http_client = FakeHttpClient([FakeResponse(418, headers={"Retry-After": "10"})])
    client = UpbitPublicClient(http_client=http_client, retry_policy=RetryPolicy(max_attempts=1))

    with pytest.raises(ExchangeRateLimitError):
        client._get("/v1/market/all", params={"is_details": "true"}, group="market")
    with pytest.raises(ExchangeRateLimitError):
        client._get("/v1/market/all", params={"is_details": "true"}, group="market")
    assert len(http_client.calls) == 1


def test_upbit_429_retry_after_retries_then_succeeds(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    monkeypatch.setattr("crypto_signal_bot.exchanges.upbit.time.sleep", sleeps.append)
    http_client = FakeHttpClient([
        FakeResponse(429, headers={"Retry-After": "1.5"}),
        FakeResponse(200, payload={"ok": True}),
    ])
    client = UpbitPublicClient(
        http_client=http_client,
        retry_policy=RetryPolicy(max_attempts=2, max_sleep_seconds=10, jitter_seconds=0),
    )

    assert client._get("/v1/market/all", params={"is_details": "true"}, group="market") == {"ok": True}
    assert sleeps == [1.5]
    assert len(http_client.calls) == 2


def test_upbit_5xx_retry_is_bounded(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    monkeypatch.setattr("crypto_signal_bot.exchanges.upbit.time.sleep", sleeps.append)
    http_client = FakeHttpClient([FakeResponse(503), FakeResponse(200, payload={"ok": True})])
    client = UpbitPublicClient(
        http_client=http_client,
        retry_policy=RetryPolicy(max_attempts=2, jitter_seconds=0),
    )

    assert client._get("/v1/market/all", params={"is_details": "true"}, group="market") == {"ok": True}
    assert len(http_client.calls) == 2
    assert len(sleeps) == 1


def test_upbit_4xx_does_not_retry() -> None:
    http_client = FakeHttpClient([FakeResponse(404)])
    client = UpbitPublicClient(http_client=http_client, retry_policy=RetryPolicy(max_attempts=3))

    with pytest.raises(ExchangeClientError):
        client._get("/v1/market/all", params={"is_details": "true"}, group="market")
    assert len(http_client.calls) == 1


def test_binance_5xx_retry_is_bounded(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    monkeypatch.setattr("crypto_signal_bot.exchanges.binance.time.sleep", sleeps.append)
    http_client = FakeHttpClient([FakeResponse(503), FakeResponse(200, payload={"ok": True})])
    client = BinancePublicClient(
        http_client=http_client,
        retry_policy=RetryPolicy(max_attempts=2, jitter_seconds=0),
    )

    assert client._get("/api/v3/ticker/24hr", params={"symbol": "BTCUSDT"}, weight=2) == {"ok": True}
    assert len(http_client.calls) == 2
    assert len(sleeps) == 1


def test_binance_4xx_does_not_retry() -> None:
    http_client = FakeHttpClient([FakeResponse(404)])
    client = BinancePublicClient(http_client=http_client, retry_policy=RetryPolicy(max_attempts=3))

    with pytest.raises(ExchangeClientError):
        client._get("/api/v3/ticker/24hr", params={"symbol": "BTCUSDT"}, weight=2)
    assert len(http_client.calls) == 1
