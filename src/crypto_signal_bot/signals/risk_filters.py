from __future__ import annotations

from dataclasses import dataclass

from crypto_signal_bot.features.feature_builder import FeatureSnapshot

CRITICAL_RISK_FLAGS = {
    "stale_data",
    "failed_data_quality",
    "incomplete_current_candle",
    "low_liquidity",
    "wide_spread",
    "symbol_quarantined",
    "insufficient_history",
    "inactive_market",
}


@dataclass(frozen=True)
class RiskThresholds:
    min_quote_volume: float = 1_000.0
    max_spread_bps: float = 30.0


def derive_risk_flags(
    snapshot: FeatureSnapshot,
    thresholds: RiskThresholds | None = None,
) -> list[str]:
    thresholds = thresholds or RiskThresholds()
    flags: list[str] = []
    if snapshot.data_quality_status == "fail":
        flags.append("failed_data_quality")
    if "stale_data" in snapshot.data_quality_warnings:
        flags.append("stale_data")
    if not snapshot.is_closed_candle_signal or "incomplete_current_candle" in snapshot.data_quality_warnings:
        flags.append("incomplete_current_candle")
    spread = snapshot.values.get("spread_bps")
    if spread is not None and spread > thresholds.max_spread_bps:
        flags.append("wide_spread")
    quote_volume = snapshot.values.get("quote_volume")
    if quote_volume is not None and quote_volume < thresholds.min_quote_volume:
        flags.append("low_liquidity")
    rv = snapshot.values.get("realized_volatility_20")
    if rv is not None and rv > 0.08:
        flags.append("excessive_volatility")
    rsi = snapshot.values.get("rsi_14")
    if rsi is not None and rsi > 85:
        flags.append("overextended_rsi")
    wick = snapshot.values.get("upper_wick_ratio")
    ret_15m = snapshot.values.get("ret_15m") or 0.0
    if wick is not None and wick > 0.6 and ret_15m > 0.02:
        flags.append("upper_wick_reversal_risk")
    return flags


def has_critical_risk(flags: list[str]) -> bool:
    return bool(CRITICAL_RISK_FLAGS.intersection(flags))
