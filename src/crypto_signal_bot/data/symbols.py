from __future__ import annotations

from crypto_signal_bot.data.models import SymbolIdentity

BINANCE_QUOTE_ASSETS = (
    "FDUSD",
    "USDT",
    "USDC",
    "BUSD",
    "TUSD",
    "BTC",
    "ETH",
    "BNB",
    "EUR",
    "TRY",
    "BRL",
)

CANONICAL_ASSET_ALIASES = {
    "XBT": "BTC",
    "BCC": "BCH",
}


def normalize_symbol(exchange: str, raw_symbol: str, *, quote_asset: str | None = None) -> SymbolIdentity:
    exchange_key = exchange.lower()
    raw = raw_symbol.upper()
    if exchange_key == "upbit":
        base, quote = _normalize_upbit(raw)
    elif exchange_key == "binance":
        base, quote = _normalize_binance(raw, quote_asset=quote_asset)
    else:
        raise ValueError(f"Unsupported exchange for symbol normalization: {exchange}")
    canonical_base = canonical_asset_id(base)
    canonical_quote = canonical_asset_id(quote)
    return SymbolIdentity(
        exchange=exchange_key,
        raw_symbol=raw,
        base_asset=base,
        quote_asset=quote,
        canonical_asset_id=canonical_base,
        canonical_pair_id=f"{canonical_base}/{canonical_quote}",
    )


def canonical_asset_id(asset: str) -> str:
    normalized = asset.strip().upper()
    if not normalized:
        raise ValueError("Asset cannot be empty.")
    return CANONICAL_ASSET_ALIASES.get(normalized, normalized)


def _normalize_upbit(raw_symbol: str) -> tuple[str, str]:
    if "-" not in raw_symbol:
        raise ValueError(f"Unsupported Upbit symbol format: {raw_symbol}")
    quote, base = raw_symbol.split("-", 1)
    if not quote or not base:
        raise ValueError(f"Unsupported Upbit symbol format: {raw_symbol}")
    return base, quote


def _normalize_binance(raw_symbol: str, *, quote_asset: str | None) -> tuple[str, str]:
    if quote_asset:
        quote = quote_asset.upper()
        if not raw_symbol.endswith(quote):
            raise ValueError(f"Binance symbol {raw_symbol} does not end with quote asset {quote}.")
        base = raw_symbol[: -len(quote)]
        if not base:
            raise ValueError(f"Unsupported Binance symbol format: {raw_symbol}")
        return base, quote
    for quote in BINANCE_QUOTE_ASSETS:
        if raw_symbol.endswith(quote) and len(raw_symbol) > len(quote):
            return raw_symbol[: -len(quote)], quote
    raise ValueError(f"Unsupported Binance symbol format: {raw_symbol}")
