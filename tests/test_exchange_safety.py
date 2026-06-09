from __future__ import annotations

import pytest

from crypto_signal_bot.exchanges.base import EndpointRejected
from crypto_signal_bot.exchanges.safety import assert_public_endpoint


def test_public_endpoint_allowlist_accepts_market_data() -> None:
    assert_public_endpoint("upbit", "GET", "/v1/candles/minutes/5")
    assert_public_endpoint("binance", "GET", "/api/v3/klines")


@pytest.mark.parametrize(
    ("exchange", "path"),
    [
        ("upbit", "/v1/orders"),
        ("upbit", "/v1/withdraws"),
        ("binance", "/api/v3/order"),
        ("binance", "/api/v3/account"),
        ("binance", "/sapi/v1/capital/withdraw/apply"),
    ],
)
def test_private_or_trading_paths_are_blocked(exchange: str, path: str) -> None:
    with pytest.raises(EndpointRejected):
        assert_public_endpoint(exchange, "GET", path)
