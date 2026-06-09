from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.data.models import Candle, utc_now


def make_mock_candles(
    exchange: str,
    quote: str,
    interval: str,
    *,
    limit: int = 120,
) -> list[Candle]:
    symbols = _mock_symbols(exchange, quote)
    candles: list[Candle] = []
    minutes = _interval_minutes(interval)
    end = utc_now().replace(second=0, microsecond=0) - timedelta(minutes=minutes)
    start = end - timedelta(minutes=minutes * (limit - 1))
    for symbol_index, symbol in enumerate(symbols):
        base_price = 100 + symbol_index * 25
        drift = 0.0006 + symbol_index * 0.00045
        for index in range(limit):
            open_time = start + timedelta(minutes=index * minutes)
            close_time = open_time + timedelta(minutes=minutes) - timedelta(milliseconds=1)
            trend = 1 + drift * index
            wave = 0.006 * math.sin(index / 5 + symbol_index)
            close = base_price * trend * (1 + wave)
            open_price = close * (1 - 0.001 * math.cos(index))
            high = max(open_price, close) * 1.004
            low = min(open_price, close) * 0.996
            base_volume = 800 + 20 * index + 200 * symbol_index
            quote_volume = close * base_volume
            candles.append(
                Candle(
                    exchange=exchange,
                    symbol=symbol,
                    interval=interval,
                    open_time_utc=open_time,
                    close_time_utc=close_time,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    base_volume=base_volume,
                    quote_volume=quote_volume,
                    trade_count=100 + index,
                    is_closed=close_time <= datetime.now(tz=UTC),
                )
            )
    return candles


def _mock_symbols(exchange: str, quote: str) -> list[str]:
    if exchange == "upbit":
        return [f"{quote}-BTC", f"{quote}-ETH", f"{quote}-ALPHA"]
    return [f"BTC{quote}", f"ETH{quote}", f"ALPHA{quote}"]


def _interval_minutes(interval: str) -> int:
    if interval.endswith("m"):
        return int(interval[:-1])
    if interval.endswith("h"):
        return int(interval[:-1]) * 60
    raise ValueError(f"Unsupported mock interval: {interval}")
