from __future__ import annotations

import pytest

from crypto_signal_bot.data.symbols import normalize_symbol


def test_normalize_upbit_symbol_identity() -> None:
    identity = normalize_symbol("upbit", "KRW-BTC")

    assert identity.exchange == "upbit"
    assert identity.raw_symbol == "KRW-BTC"
    assert identity.base_asset == "BTC"
    assert identity.quote_asset == "KRW"


def test_normalize_binance_symbol_identity_from_known_quote_suffix() -> None:
    identity = normalize_symbol("binance", "ETHUSDT")

    assert identity.exchange == "binance"
    assert identity.raw_symbol == "ETHUSDT"
    assert identity.base_asset == "ETH"
    assert identity.quote_asset == "USDT"


def test_normalize_binance_symbol_identity_with_explicit_quote() -> None:
    identity = normalize_symbol("binance", "BTCFDUSD", quote_asset="FDUSD")

    assert identity.base_asset == "BTC"
    assert identity.quote_asset == "FDUSD"


def test_unknown_symbol_format_fails_closed() -> None:
    with pytest.raises(ValueError):
        normalize_symbol("binance", "UNKNOWN")
