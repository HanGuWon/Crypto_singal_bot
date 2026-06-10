from __future__ import annotations

from dataclasses import dataclass, field

from crypto_signal_bot.data.models import Candle
from crypto_signal_bot.features.candle_patterns import body_pct, is_bearish, is_bullish


@dataclass(frozen=True)
class ThreeTickConfig:
    max_scan_bars: int = 12
    min_bearish_body_bps: float = 5.0
    large_transition_body_bps: float = 35.0
    reset_rebound_pct: float = 0.012
    falling_knife_drop_pct: float = 0.045
    falling_knife_bearish_ticks: int = 5


@dataclass(frozen=True)
class ThreeTickState:
    status: str
    bearish_tick_count: int
    recent_drop_pct: float
    small_bearish_merged: int = 0
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
    reasons: list[str] = []
    risks: list[str] = []

    for previous, candle in zip(recent, recent[1:], strict=False):
        close_delta_pct = candle.close / previous.close - 1 if previous.close > 0 else 0.0
        if is_bullish(candle):
            if close_delta_pct > cfg.reset_rebound_pct:
                return ThreeTickState(
                    status="flow_broken_reset",
                    bearish_tick_count=tick_count,
                    recent_drop_pct=recent_drop_pct,
                    small_bearish_merged=small_merged,
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

        if is_bullish(previous) and candle_body_bps < cfg.large_transition_body_bps:
            reasons.append("bullish_to_bearish_transition_not_counted")
            continue

        if is_bullish(previous):
            reasons.append("large_bearish_transition_counted")
        tick_count += 1

    if tick_count >= cfg.falling_knife_bearish_ticks or recent_drop_pct <= -cfg.falling_knife_drop_pct:
        risks.append("falling_knife_suppress")
        return ThreeTickState(
            status="falling_knife_suppress",
            bearish_tick_count=tick_count,
            recent_drop_pct=recent_drop_pct,
            small_bearish_merged=small_merged,
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
        reason_codes=_unique(reasons),
        risk_flags=risks,
        used_closed_candles=len(closed),
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
