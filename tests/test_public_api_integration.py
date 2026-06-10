from __future__ import annotations

import pytest

from crypto_signal_bot.exchanges.binance import BinancePublicClient
from crypto_signal_bot.exchanges.rate_limit import RetryPolicy
from crypto_signal_bot.exchanges.upbit import UpbitPublicClient

pytestmark = pytest.mark.integration


def test_binance_public_market_data_integration_smoke() -> None:
    client = BinancePublicClient(
        timeout=5.0,
        retry_policy=RetryPolicy(max_attempts=2, base_sleep_seconds=0.1, jitter_seconds=0),
    )

    markets = client.get_markets("USDT")
    assert any(market.raw_symbol == "BTCUSDT" for market in markets)

    candles = client.get_candles("BTCUSDT", "5m", limit=3)
    assert candles
    assert all(candle.exchange == "binance" for candle in candles)
    assert all(candle.symbol == "BTCUSDT" for candle in candles)


def test_upbit_public_market_data_integration_smoke() -> None:
    client = UpbitPublicClient(
        timeout=5.0,
        retry_policy=RetryPolicy(max_attempts=2, base_sleep_seconds=0.1, jitter_seconds=0),
    )

    markets = client.get_markets("KRW")
    assert any(market.raw_symbol == "KRW-BTC" for market in markets)

    candles = client.get_candles("KRW-BTC", "5m", limit=3)
    assert candles
    assert all(candle.exchange == "upbit" for candle in candles)
    assert all(candle.symbol == "KRW-BTC" for candle in candles)
