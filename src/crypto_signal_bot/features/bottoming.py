from __future__ import annotations

from dataclasses import dataclass, field

from crypto_signal_bot.data.models import Candle
from crypto_signal_bot.features.candle_patterns import body_pct, close_compression, lower_wick_ratio


@dataclass(frozen=True)
class BottomingConfig:
    lookback_bars: int = 6
    shrink_bars: int = 3
    compression_bars: int = 4
    max_close_band_pct: float = 0.008
    min_lower_wick_ratio: float = 0.30
    support_tolerance_bps: float = 30.0
    falling_knife_drop_pct: float = 0.05


@dataclass(frozen=True)
class BottomingState:
    status: str
    body_shrinking: bool
    close_compressed: bool
    lower_wick_support: bool
    support_failed: bool
    recent_drop_pct: float
    reason_codes: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    used_closed_candles: int = 0


def compute_bottoming_state(
    candles: list[Candle],
    config: BottomingConfig | None = None,
) -> BottomingState:
    cfg = config or BottomingConfig()
    closed = [candle for candle in candles if candle.is_closed]
    if len(closed) < max(cfg.shrink_bars, cfg.compression_bars, 3):
        return BottomingState(
            status="not_ready",
            body_shrinking=False,
            close_compressed=False,
            lower_wick_support=False,
            support_failed=False,
            recent_drop_pct=0.0,
            reason_codes=["insufficient_closed_candles"],
            used_closed_candles=len(closed),
        )

    recent = closed[-cfg.lookback_bars :]
    latest = recent[-1]
    highest_close = max(candle.close for candle in recent)
    recent_drop_pct = latest.close / highest_close - 1 if highest_close > 0 else 0.0
    prior_support = min(candle.low for candle in recent[:-1])
    support_failed = latest.close < prior_support * (1 - cfg.support_tolerance_bps / 10000)

    shrink_sample = closed[-cfg.shrink_bars :]
    body_values = [body_pct(candle) for candle in shrink_sample]
    body_shrinking = all(
        later <= earlier
        for earlier, later in zip(body_values, body_values[1:], strict=False)
    ) and body_values[-1] <= body_values[0] * 0.85

    compression = close_compression(closed[-cfg.compression_bars :])
    close_compressed = compression is not None and compression <= cfg.max_close_band_pct
    lower_wick_count = sum(
        1
        for candle in closed[-cfg.compression_bars :]
        if lower_wick_ratio(candle) >= cfg.min_lower_wick_ratio
    )
    lower_wick_support = lower_wick_count >= 2

    reasons: list[str] = []
    risks: list[str] = []
    if body_shrinking:
        reasons.append("body_shrinking")
    if close_compressed:
        reasons.append("close_compression")
    if lower_wick_support:
        reasons.append("lower_wick_support")

    if support_failed:
        return BottomingState(
            status="invalidated",
            body_shrinking=body_shrinking,
            close_compressed=close_compressed,
            lower_wick_support=lower_wick_support,
            support_failed=True,
            recent_drop_pct=recent_drop_pct,
            reason_codes=_unique([*reasons, "support_failed"]),
            risk_flags=["support_failed"],
            used_closed_candles=len(closed),
        )

    if recent_drop_pct <= -cfg.falling_knife_drop_pct and not (close_compressed and lower_wick_support):
        return BottomingState(
            status="falling_knife_suppress",
            body_shrinking=body_shrinking,
            close_compressed=close_compressed,
            lower_wick_support=lower_wick_support,
            support_failed=False,
            recent_drop_pct=recent_drop_pct,
            reason_codes=_unique([*reasons, "steep_unconfirmed_decline"]),
            risk_flags=["falling_knife_suppress"],
            used_closed_candles=len(closed),
        )

    evidence_count = sum([body_shrinking, close_compressed, lower_wick_support])
    if evidence_count == 3:
        status = "confirmed"
        reasons.append("bottoming_evidence_confirmed")
    elif evidence_count == 2:
        status = "watch"
        reasons.append("bottoming_evidence_watch")
    elif evidence_count == 1:
        status = "forming"
        reasons.append("bottoming_evidence_forming")
    else:
        status = "not_ready"
        reasons.append("no_bottoming_evidence")

    return BottomingState(
        status=status,
        body_shrinking=body_shrinking,
        close_compressed=close_compressed,
        lower_wick_support=lower_wick_support,
        support_failed=False,
        recent_drop_pct=recent_drop_pct,
        reason_codes=_unique(reasons),
        risk_flags=risks,
        used_closed_candles=len(closed),
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
