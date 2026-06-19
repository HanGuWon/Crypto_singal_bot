from __future__ import annotations

import os

import pytest

from crypto_signal_bot.exchanges.binance import BinancePublicClient
from crypto_signal_bot.exchanges.rate_limit import RetryPolicy

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_PUBLIC_BINANCE_INTEGRATION") != "true",
        reason="Set RUN_PUBLIC_BINANCE_INTEGRATION=true to hit Binance public market-data endpoints.",
    ),
]


def test_binance_public_low_weight_market_data_smoke() -> None:
    client = BinancePublicClient(
        timeout=5.0,
        retry_policy=RetryPolicy(max_attempts=2, base_sleep_seconds=0.1, jitter_seconds=0),
    )

    markets = client.get_markets("USDT")
    assert any(market.raw_symbol == "BTCUSDT" for market in markets)

    candles = client.get_candles("BTCUSDT", "5m", limit=3)
    assert len(candles) <= 3
    assert all(candle.exchange == "binance" for candle in candles)
    assert all(candle.symbol == "BTCUSDT" for candle in candles)
