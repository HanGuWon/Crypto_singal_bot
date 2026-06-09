from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from crypto_signal_bot.config import Settings

SAFE_CONFIG_FIELDS = (
    "max_symbols_per_collect",
    "polling_interval_seconds",
    "min_quote_volume_upbit_krw",
    "min_quote_volume_binance_usdt",
    "max_spread_bps",
    "max_staleness_seconds",
    "min_history_bars",
    "symbol_quarantine_minutes",
    "alert_score_threshold",
    "alert_exit_threshold",
    "alert_score_delta_threshold",
    "alert_cooldown_minutes",
    "alert_top_n",
    "alert_global_max_per_minute",
    "alert_per_symbol_max_per_hour",
)


def safe_config(settings: Settings) -> dict[str, Any]:
    raw = asdict(settings)
    return {field: _json_safe(raw[field]) for field in SAFE_CONFIG_FIELDS}


def config_hash(settings: Settings) -> str:
    payload = json.dumps(safe_config(settings), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _json_safe(value: Any) -> Any:
    if hasattr(value, "as_posix"):
        return str(value)
    return value
