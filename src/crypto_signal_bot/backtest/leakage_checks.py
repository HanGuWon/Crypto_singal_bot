from __future__ import annotations

from crypto_signal_bot.data.models import Candle


def assert_signal_uses_closed_candle(signal_time_utc: object, candles: list[Candle]) -> None:
    for candle in candles:
        if candle.close_time_utc <= signal_time_utc and not candle.is_closed:  # type: ignore[operator]
            raise AssertionError("Signal includes an incomplete candle.")


def assert_next_candle_entry(signal_candle: Candle, entry_candle: Candle) -> None:
    if entry_candle.open_time_utc <= signal_candle.close_time_utc:
        raise AssertionError("Backtest entry must occur after the signal candle close.")
