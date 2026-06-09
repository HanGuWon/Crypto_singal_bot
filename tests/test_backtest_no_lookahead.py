from __future__ import annotations

from datetime import timedelta

import pytest

from crypto_signal_bot.backtest.leakage_checks import assert_next_candle_entry
from crypto_signal_bot.data.collector import make_mock_candles


def test_entry_must_be_after_signal_close() -> None:
    candles = [c for c in make_mock_candles("binance", "USDT", "5m", limit=5) if c.symbol == "BTCUSDT"]
    assert_next_candle_entry(candles[0], candles[1])
    bad_entry = candles[1].__class__(
        **{**candles[1].__dict__, "open_time_utc": candles[0].close_time_utc - timedelta(seconds=1)}
    )
    with pytest.raises(AssertionError):
        assert_next_candle_entry(candles[0], bad_entry)
