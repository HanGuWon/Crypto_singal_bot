from __future__ import annotations

import pytest

from crypto_signal_bot.data.symbols import canonical_asset_id, normalize_symbol


def test_normalize_upbit_symbol_identity() -> None:
    identity = normalize_symbol("upbit", "KRW-BTC")

    assert identity.exchange == "upbit"
    assert identity.raw_symbol == "KRW-BTC"
    assert identity.base_asset == "BTC"
    assert identity.quote_asset == "KRW"
    assert identity.canonical_asset_id == "BTC"
    assert identity.canonical_pair_id == "BTC/KRW"


def test_normalize_binance_symbol_identity_from_known_quote_suffix() -> None:
    identity = normalize_symbol("binance", "ETHUSDT")

    assert identity.exchange == "binance"
    assert identity.raw_symbol == "ETHUSDT"
    assert identity.base_asset == "ETH"
    assert identity.quote_asset == "USDT"
    assert identity.canonical_asset_id == "ETH"
    assert identity.canonical_pair_id == "ETH/USDT"


def test_normalize_binance_symbol_identity_with_explicit_quote() -> None:
    identity = normalize_symbol("binance", "BTCFDUSD", quote_asset="FDUSD")

    assert identity.base_asset == "BTC"
    assert identity.quote_asset == "FDUSD"


def test_canonical_asset_id_groups_cross_exchange_base_assets() -> None:
    upbit = normalize_symbol("upbit", "KRW-BTC")
    binance = normalize_symbol("binance", "BTCUSDT")

    assert upbit.canonical_asset_id == binance.canonical_asset_id == "BTC"
    assert upbit.canonical_pair_id == "BTC/KRW"
    assert binance.canonical_pair_id == "BTC/USDT"


def test_canonical_asset_aliases_are_stable() -> None:
    assert canonical_asset_id("xbt") == "BTC"
    assert canonical_asset_id("BCC") == "BCH"


def test_unknown_symbol_format_fails_closed() -> None:
    with pytest.raises(ValueError):
        normalize_symbol("binance", "UNKNOWN")
