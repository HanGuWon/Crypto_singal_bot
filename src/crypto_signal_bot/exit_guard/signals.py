from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_signal_bot.data.models import Candle, DataQualityReport
from crypto_signal_bot.exit_guard.models import ExitGuardValidationError, ProtectiveExitSignal
from crypto_signal_bot.features.indicators import atr, ema, rolling_zscore

EXIT_GUARD_STATES = (
    "WATCHING",
    "WARNING",
    "EXIT_CANDIDATE",
    "EXIT_CONFIRMED",
    "SEVERE_EXIT_CANDIDATE",
    "SAFETY_BLOCKED",
)
RISK_REDUCING_EXPOSURE_SIDES = ("spot_long", "long", "short")


@dataclass(frozen=True)
class TrendBreakExitConfig:
    min_closed_candles: int = 60
    swing_lookback: int = 12
    ema_fast_period: int = 20
    ema_slow_period: int = 50
    atr_period: int = 14
    atr_break_fraction: float = 0.35
    warning_atr_fraction: float = 0.20
    volume_z_window: int = 20
    min_volume_z: float = 0.5
    severe_adverse_move_pct: float = 0.08


@dataclass(frozen=True)
class TrendBreakDiagnostics:
    exposure_side: str
    state: str
    exit_score: float
    latest_close: float | None
    swing_level: float | None
    atr_value: float | None
    break_distance_atr: float | None
    ema_fast: float | None
    ema_slow: float | None
    volume_zscore: float | None
    adverse_move_pct: float
    rebound_pct: float
    used_closed_candles: int
    ignored_open_candles: int
    drivers: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)


def build_trend_break_exit_signal(
    candles: list[Candle],
    *,
    exposure_side: str,
    quality: DataQualityReport | None = None,
    config: TrendBreakExitConfig | None = None,
    source_run_id: str | None = None,
    exchange: str | None = None,
    symbol: str | None = None,
    interval: str | None = None,
) -> ProtectiveExitSignal:
    diagnostics = compute_trend_break_diagnostics(
        candles,
        exposure_side=exposure_side,
        quality=quality,
        config=config,
    )
    closed = _closed_candles(candles)
    latest = closed[-1] if closed else None
    now = latest.close_time_utc if latest is not None else datetime.now(tz=UTC)
    event_exchange = exchange or (latest.exchange if latest is not None else "unknown")
    event_symbol = symbol or (latest.symbol if latest is not None else "unknown")
    event_interval = interval or (latest.interval if latest is not None else "unknown")
    return ProtectiveExitSignal(
        signal_id=source_run_id or f"exit-guard-{event_exchange}-{event_symbol}-{event_interval}-{now.isoformat()}",
        created_at_utc=now,
        exchange=event_exchange,
        symbol=event_symbol,
        interval=event_interval,
        state=diagnostics.state,
        exit_score=diagnostics.exit_score,
        drivers=diagnostics.drivers,
        risk_flags=diagnostics.risk_flags,
        is_closed_candle_signal=True,
        data_quality_status=quality.status if quality is not None else "pass",
    )


def compute_trend_break_diagnostics(
    candles: list[Candle],
    *,
    exposure_side: str,
    quality: DataQualityReport | None = None,
    config: TrendBreakExitConfig | None = None,
) -> TrendBreakDiagnostics:
    if exposure_side not in RISK_REDUCING_EXPOSURE_SIDES:
        raise ExitGuardValidationError(f"Unsupported protective exit exposure side: {exposure_side}")

    cfg = config or TrendBreakExitConfig()
    closed = _closed_candles(candles)
    ignored_open = len(candles) - len(closed)
    risks: list[str] = []
    drivers: list[str] = ["closed_candle_trend_break_engine", f"exposure_side:{exposure_side}"]
    if ignored_open:
        drivers.append("open_candles_ignored")

    if quality is not None and not quality.passed:
        risks.extend(["exit_guard_data_quality_block", *quality.warnings])
        return _diagnostics(
            exposure_side=exposure_side,
            state="SAFETY_BLOCKED",
            exit_score=0.0,
            used_closed_candles=len(closed),
            ignored_open_candles=ignored_open,
            drivers=drivers,
            risk_flags=risks,
        )

    required = max(cfg.min_closed_candles, cfg.ema_slow_period, cfg.swing_lookback + 2, cfg.atr_period + 1)
    if len(closed) < required:
        return _diagnostics(
            exposure_side=exposure_side,
            state="SAFETY_BLOCKED",
            exit_score=0.0,
            used_closed_candles=len(closed),
            ignored_open_candles=ignored_open,
            drivers=[*drivers, "insufficient_closed_candle_history"],
            risk_flags=["insufficient_closed_candle_history"],
        )

    latest = closed[-1]
    highs = [candle.high for candle in closed]
    lows = [candle.low for candle in closed]
    closes = [candle.close for candle in closed]
    volumes = [_volume_value(candle) for candle in closed]
    atr_value = atr(highs, lows, closes, cfg.atr_period)
    ema_fast_values = ema(closes, cfg.ema_fast_period)
    ema_slow_values = ema(closes, cfg.ema_slow_period)
    ema_fast = ema_fast_values[-1] if ema_fast_values else None
    ema_slow = ema_slow_values[-1] if ema_slow_values else None
    volume_z = rolling_zscore(volumes, cfg.volume_z_window)

    if atr_value is None or atr_value <= 0 or ema_fast is None or ema_slow is None:
        return _diagnostics(
            exposure_side=exposure_side,
            state="SAFETY_BLOCKED",
            exit_score=0.0,
            latest_close=latest.close,
            atr_value=atr_value,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            used_closed_candles=len(closed),
            ignored_open_candles=ignored_open,
            drivers=[*drivers, "indicator_history_unavailable"],
            risk_flags=["indicator_history_unavailable"],
        )

    prior = closed[-cfg.swing_lookback - 1 : -1]
    short_exposure = exposure_side == "short"
    swing_level = max(candle.high for candle in prior) if short_exposure else min(candle.low for candle in prior)
    if short_exposure:
        break_distance = latest.close - swing_level
        break_distance_atr = break_distance / atr_value
        trend_confirmed = latest.close > ema_fast and ema_fast > ema_slow
        warning_zone = latest.close >= swing_level - atr_value * cfg.warning_atr_fraction or latest.close > ema_fast
        adverse_move_pct = _pct_change(latest.close, min(candle.close for candle in closed[-cfg.swing_lookback :]))
        rebound_pct = adverse_move_pct
    else:
        break_distance = swing_level - latest.close
        break_distance_atr = break_distance / atr_value
        trend_confirmed = latest.close < ema_fast and ema_fast < ema_slow
        warning_zone = latest.close <= swing_level + atr_value * cfg.warning_atr_fraction or latest.close < ema_fast
        adverse_move_pct = -_pct_change(latest.close, max(candle.close for candle in closed[-cfg.swing_lookback :]))
        rebound_pct = _pct_change(latest.close, min(candle.close for candle in closed[-cfg.swing_lookback :]))

    break_confirmed = break_distance_atr >= cfg.atr_break_fraction
    volume_confirmed = volume_z is not None and volume_z >= cfg.min_volume_z
    severe_move = adverse_move_pct >= cfg.severe_adverse_move_pct

    if break_confirmed:
        drivers.append("swing_level_break")
    if trend_confirmed:
        drivers.append("ema_trend_break_confirmation")
    if volume_confirmed:
        drivers.append("volume_confirmation")
    if severe_move:
        drivers.append("severe_adverse_move")
    if volume_z is None:
        risks.append("volume_confirmation_unavailable")

    state = _trend_break_state(
        break_confirmed=break_confirmed,
        trend_confirmed=trend_confirmed,
        volume_confirmed=volume_confirmed,
        severe_move=severe_move,
        warning_zone=warning_zone,
    )
    score = _trend_break_score(
        break_distance_atr=break_distance_atr,
        trend_confirmed=trend_confirmed,
        volume_confirmed=volume_confirmed,
        severe_move=severe_move,
        warning_zone=warning_zone,
    )

    return _diagnostics(
        exposure_side=exposure_side,
        state=state,
        exit_score=score,
        latest_close=latest.close,
        swing_level=swing_level,
        atr_value=atr_value,
        break_distance_atr=break_distance_atr,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        volume_zscore=volume_z,
        adverse_move_pct=adverse_move_pct,
        rebound_pct=rebound_pct,
        used_closed_candles=len(closed),
        ignored_open_candles=ignored_open,
        drivers=drivers,
        risk_flags=risks,
    )


def combine_multi_timeframe_exit_signals(
    primary: ProtectiveExitSignal,
    confirmations: list[ProtectiveExitSignal],
) -> ProtectiveExitSignal:
    blocked = [signal for signal in [primary, *confirmations] if signal.state == "SAFETY_BLOCKED"]
    if blocked and primary.state == "SAFETY_BLOCKED":
        return primary

    confirming = [
        signal
        for signal in confirmations
        if signal.state in {"EXIT_CANDIDATE", "EXIT_CONFIRMED", "SEVERE_EXIT_CANDIDATE"}
    ]
    state = primary.state
    score = primary.exit_score
    drivers = [*primary.drivers]
    risks = [*primary.risk_flags]
    if confirming:
        drivers.extend(f"mtf_confirmation:{signal.interval}:{signal.state}" for signal in confirming)
        score = min(100.0, score + min(15.0, 5.0 * len(confirming)))
        if state == "WARNING":
            state = "EXIT_CANDIDATE"
        elif state == "EXIT_CANDIDATE":
            state = "EXIT_CONFIRMED"
    if any(signal.state == "SEVERE_EXIT_CANDIDATE" for signal in [primary, *confirming]):
        state = "SEVERE_EXIT_CANDIDATE"
        score = max(score, 85.0)
    if blocked:
        risks.extend(f"mtf_blocked:{signal.interval}" for signal in blocked)

    return ProtectiveExitSignal(
        signal_id=primary.signal_id,
        created_at_utc=primary.created_at_utc,
        exchange=primary.exchange,
        symbol=primary.symbol,
        interval=primary.interval,
        state=state,
        exit_score=round(score, 2),
        drivers=_unique(drivers)[:16],
        risk_flags=_unique(risks)[:16],
        is_closed_candle_signal=True,
        data_quality_status="pass",
    )


def _trend_break_state(
    *,
    break_confirmed: bool,
    trend_confirmed: bool,
    volume_confirmed: bool,
    severe_move: bool,
    warning_zone: bool,
) -> str:
    if break_confirmed and trend_confirmed and volume_confirmed and severe_move:
        return "SEVERE_EXIT_CANDIDATE"
    if break_confirmed and trend_confirmed and volume_confirmed:
        return "EXIT_CONFIRMED"
    if break_confirmed and (trend_confirmed or volume_confirmed):
        return "EXIT_CANDIDATE"
    if warning_zone:
        return "WARNING"
    return "WATCHING"


def _trend_break_score(
    *,
    break_distance_atr: float,
    trend_confirmed: bool,
    volume_confirmed: bool,
    severe_move: bool,
    warning_zone: bool,
) -> float:
    score = 20.0
    if warning_zone:
        score += 15.0
    if break_distance_atr > 0:
        score += min(35.0, break_distance_atr * 30.0)
    if trend_confirmed:
        score += 20.0
    if volume_confirmed:
        score += 10.0
    if severe_move:
        score += 15.0
    return round(max(0.0, min(100.0, score)), 2)


def _diagnostics(
    *,
    exposure_side: str,
    state: str,
    exit_score: float,
    latest_close: float | None = None,
    swing_level: float | None = None,
    atr_value: float | None = None,
    break_distance_atr: float | None = None,
    ema_fast: float | None = None,
    ema_slow: float | None = None,
    volume_zscore: float | None = None,
    adverse_move_pct: float = 0.0,
    rebound_pct: float = 0.0,
    used_closed_candles: int = 0,
    ignored_open_candles: int = 0,
    drivers: list[str] | None = None,
    risk_flags: list[str] | None = None,
) -> TrendBreakDiagnostics:
    return TrendBreakDiagnostics(
        exposure_side=exposure_side,
        state=state,
        exit_score=round(max(0.0, min(100.0, exit_score)), 2),
        latest_close=latest_close,
        swing_level=swing_level,
        atr_value=atr_value,
        break_distance_atr=None if break_distance_atr is None else round(break_distance_atr, 6),
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        volume_zscore=volume_zscore,
        adverse_move_pct=round(adverse_move_pct, 6),
        rebound_pct=round(rebound_pct, 6),
        used_closed_candles=used_closed_candles,
        ignored_open_candles=ignored_open_candles,
        drivers=_unique(drivers or [])[:16],
        risk_flags=_unique(risk_flags or [])[:16],
    )


def _closed_candles(candles: list[Candle]) -> list[Candle]:
    return sorted((candle for candle in candles if candle.is_closed), key=lambda candle: candle.close_time_utc)


def _volume_value(candle: Candle) -> float:
    if candle.quote_volume is not None:
        return max(candle.quote_volume, 0.0)
    if candle.base_volume is not None:
        return max(candle.base_volume, 0.0)
    return 0.0


def _pct_change(current: float, reference: float) -> float:
    if reference <= 0:
        return 0.0
    return current / reference - 1


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
