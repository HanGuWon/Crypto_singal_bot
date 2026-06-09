from __future__ import annotations

from dataclasses import dataclass

from crypto_signal_bot.backtest.leakage_checks import assert_next_candle_entry
from crypto_signal_bot.backtest.metrics import summarize_returns
from crypto_signal_bot.data.models import Candle


@dataclass(frozen=True)
class BacktestAssumptions:
    fee_bps: float = 10.0
    spread_bps: float = 5.0
    slippage_bps: float = 5.0
    holding_bars: int = 3

    @property
    def round_trip_cost(self) -> float:
        return (self.fee_bps + self.spread_bps + self.slippage_bps) / 10000


def event_study_next_open(
    candles: list[Candle],
    signal_indices: list[int],
    *,
    assumptions: BacktestAssumptions | None = None,
) -> dict[str, float]:
    assumptions = assumptions or BacktestAssumptions()
    returns: list[float] = []
    for index in signal_indices:
        entry_index = index + 1
        exit_index = entry_index + assumptions.holding_bars
        if exit_index >= len(candles):
            continue
        signal = candles[index]
        entry = candles[entry_index]
        assert_next_candle_entry(signal, entry)
        entry_price = entry.open
        exit_price = candles[exit_index].close
        returns.append(exit_price / entry_price - 1 - assumptions.round_trip_cost)
    return summarize_returns(returns)
