from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from crypto_signal_bot.data.models import Candle
from crypto_signal_bot.features.candle_patterns import body_pct, body_size, is_bearish, is_bullish, range_pct
from crypto_signal_bot.features.indicators import atr


@dataclass(frozen=True)
class ThreeTickConfig:
    max_scan_bars: int = 12
    min_bearish_body_bps: float = 5.0
    large_transition_body_bps: float = 35.0
    large_transition_body_mult: float = 1.8
    large_transition_range_mult: float = 1.8
    tick_lookback_bars: int = 20
    min_tick_move_bps: float = 12.0
    atr_fraction: float = 0.20
    body_fraction: float = 0.60
    reset_rebound_pct: float = 0.012
    falling_knife_drop_pct: float = 0.045
    falling_knife_bearish_ticks: int = 5


@dataclass(frozen=True)
class ThreeTickState:
    status: str
    bearish_tick_count: int
    recent_drop_pct: float
    small_bearish_merged: int = 0
    insignificant_moves_merged: int = 0
    last_tick_unit_abs: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    used_closed_candles: int = 0


def compute_three_tick_state(
    candles: list[Candle],
    config: ThreeTickConfig | None = None,
) -> ThreeTickState:
    cfg = config or ThreeTickConfig()
    closed = [candle for candle in candles if candle.is_closed]
    if len(closed) < 4:
        return ThreeTickState(
            status="not_ready",
            bearish_tick_count=0,
            recent_drop_pct=0.0,
            reason_codes=["insufficient_closed_candles"],
            used_closed_candles=len(closed),
        )

    recent = closed[-cfg.max_scan_bars :]
    highest_close = max(candle.close for candle in recent)
    latest_close = recent[-1].close
    recent_drop_pct = latest_close / highest_close - 1 if highest_close > 0 else 0.0

    tick_count = 0
    small_merged = 0
    insignificant_merged = 0
    last_counted_tick_close: float | None = None
    last_counted_tick_low: float | None = None
    last_tick_unit_abs = 0.0
    reasons: list[str] = []
    risks: list[str] = []

    for offset, (previous, candle) in enumerate(zip(recent, recent[1:], strict=False), start=1):
        close_delta_pct = candle.close / previous.close - 1 if previous.close > 0 else 0.0
        if is_bullish(candle):
            if close_delta_pct > cfg.reset_rebound_pct:
                return ThreeTickState(
                    status="flow_broken_reset",
                    bearish_tick_count=tick_count,
                    recent_drop_pct=recent_drop_pct,
                    small_bearish_merged=small_merged,
                    insignificant_moves_merged=insignificant_merged,
                    last_tick_unit_abs=last_tick_unit_abs,
                    reason_codes=_unique([*reasons, "large_bullish_rebound_reset"]),
                    risk_flags=risks,
                    used_closed_candles=len(closed),
                )
            reasons.append("small_bullish_rebound_allowed")
            continue

        if not is_bearish(candle):
            reasons.append("flat_candle_ignored")
            continue

        candle_body_bps = body_pct(candle) * 10000
        if candle_body_bps < cfg.min_bearish_body_bps:
            small_merged += 1
            reasons.append("small_bearish_candle_merged")
            continue

        current_index = max(0, len(closed) - len(recent) + offset)
        prior_history = closed[:current_index]
        current_history = closed[: current_index + 1]
        if is_bullish(previous) and not _is_large_transition(candle, prior_history, cfg):
            reasons.append("bullish_to_bearish_transition_not_counted")
            continue

        tick_unit = _tick_unit_abs(current_history, candle, cfg)
        last_tick_unit_abs = tick_unit
        if not _meaningful_tick_progress(
            candle,
            last_counted_tick_close=last_counted_tick_close,
            last_counted_tick_low=last_counted_tick_low,
            tick_unit_abs=tick_unit,
        ):
            insignificant_merged += 1
            reasons.append("insignificant_bearish_progress_merged")
            continue

        if is_bullish(previous):
            reasons.append("large_bearish_transition_counted")
        tick_count += 1
        last_counted_tick_close = candle.close
        last_counted_tick_low = candle.low

    if tick_count >= cfg.falling_knife_bearish_ticks or recent_drop_pct <= -cfg.falling_knife_drop_pct:
        risks.append("falling_knife_suppress")
        return ThreeTickState(
            status="falling_knife_suppress",
            bearish_tick_count=tick_count,
            recent_drop_pct=recent_drop_pct,
            small_bearish_merged=small_merged,
            insignificant_moves_merged=insignificant_merged,
            last_tick_unit_abs=last_tick_unit_abs,
            reason_codes=_unique([*reasons, "steep_unconfirmed_decline"]),
            risk_flags=risks,
            used_closed_candles=len(closed),
        )

    if tick_count >= 3:
        status = "watch"
        reasons.append("three_tick_down_sequence")
    elif tick_count > 0:
        status = "forming"
        reasons.append("partial_down_sequence")
    else:
        status = "not_ready"
        reasons.append("no_actionable_down_sequence")

    return ThreeTickState(
        status=status,
        bearish_tick_count=tick_count,
        recent_drop_pct=recent_drop_pct,
        small_bearish_merged=small_merged,
        insignificant_moves_merged=insignificant_merged,
        last_tick_unit_abs=last_tick_unit_abs,
        reason_codes=_unique(reasons),
        risk_flags=risks,
        used_closed_candles=len(closed),
    )


def _is_large_transition(candle: Candle, history: list[Candle], cfg: ThreeTickConfig) -> bool:
    candle_body_bps = body_pct(candle) * 10000
    if candle_body_bps >= cfg.large_transition_body_bps:
        return True
    sample = [item for item in history[-cfg.tick_lookback_bars :] if item.is_closed]
    if len(sample) < 3:
        return False
    median_body_pct = median([body_pct(item) for item in sample])
    median_range_pct = median([range_pct(item) for item in sample])
    return (
        median_body_pct > 0
        and body_pct(candle) >= median_body_pct * cfg.large_transition_body_mult
    ) or (
        median_range_pct > 0
        and range_pct(candle) >= median_range_pct * cfg.large_transition_range_mult
    )


def _tick_unit_abs(history: list[Candle], candle: Candle, cfg: ThreeTickConfig) -> float:
    sample = [item for item in history[-cfg.tick_lookback_bars :] if item.is_closed]
    price_part = candle.close * cfg.min_tick_move_bps / 10000
    atr_value = atr(
        [item.high for item in sample],
        [item.low for item in sample],
        [item.close for item in sample],
        14,
    )
    atr_part = (atr_value or 0.0) * cfg.atr_fraction
    body_sample = [body_size(item) for item in sample if body_size(item) > 0]
    body_part = (median(body_sample) if body_sample else 0.0) * cfg.body_fraction
    return max(price_part, atr_part, body_part)


def _meaningful_tick_progress(
    candle: Candle,
    *,
    last_counted_tick_close: float | None,
    last_counted_tick_low: float | None,
    tick_unit_abs: float,
) -> bool:
    if last_counted_tick_close is None or last_counted_tick_low is None:
        return True
    return (
        candle.close <= last_counted_tick_close - tick_unit_abs
        or candle.low <= last_counted_tick_low - tick_unit_abs
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
