from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from crypto_signal_bot.data.models import ensure_utc


class ExitGuardValidationError(ValueError):
    """Raised when a protective exit guard intent is not risk-reducing."""


@dataclass(frozen=True)
class ProtectiveExitSignal:
    signal_id: str
    created_at_utc: datetime
    exchange: str
    symbol: str
    interval: str
    state: str
    exit_score: float
    drivers: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    is_closed_candle_signal: bool = True
    data_quality_status: str = "pass"

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at_utc", ensure_utc(self.created_at_utc))
        if not self.is_closed_candle_signal:
            raise ExitGuardValidationError("Protective exit signals must use closed candles only.")
        if self.data_quality_status != "pass":
            raise ExitGuardValidationError("Protective exit signals require passing data quality.")


@dataclass(frozen=True)
class BalanceSnapshot:
    exchange: str
    asset: str
    total: float
    available: float
    locked: float
    observed_at_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at_utc", ensure_utc(self.observed_at_utc))
        if min(self.total, self.available, self.locked) < 0:
            raise ExitGuardValidationError("Balances cannot be negative.")
        if self.available > self.total:
            raise ExitGuardValidationError("Available balance cannot exceed total balance.")


@dataclass(frozen=True)
class FuturesPositionSnapshot:
    exchange: str
    symbol: str
    position_mode: str
    position_side: str
    position_amount: float
    entry_price: float
    mark_price: float
    observed_at_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at_utc", ensure_utc(self.observed_at_utc))
        if self.position_mode not in {"one_way", "hedge"}:
            raise ExitGuardValidationError("Futures position mode must be known before any close intent.")
        if self.position_side not in {"BOTH", "LONG", "SHORT"}:
            raise ExitGuardValidationError("Unsupported futures position side.")
        if self.entry_price < 0 or self.mark_price <= 0:
            raise ExitGuardValidationError("Invalid futures position prices.")


@dataclass(frozen=True)
class RiskReducingOrderIntent:
    exchange: str
    symbol: str
    action: str
    side: str
    quantity: float
    position_mode: str | None = None
    position_side: str | None = None
    reduce_only: bool | None = None
    dry_run: bool = True
    manual_approval_required: bool = True
    opens_new_position: bool = False

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ExitGuardValidationError("Quantity must be positive.")
        if not self.dry_run:
            raise ExitGuardValidationError("Live protective exit intents are absent from this MVP.")
        if not self.manual_approval_required:
            raise ExitGuardValidationError("Manual approval must remain required.")
        if self.opens_new_position:
            raise ExitGuardValidationError("Protective exit intents cannot open new exposure.")
        if self.exchange == "upbit_spot":
            _validate_upbit_spot_sell_only(self)
            return
        if self.exchange == "binance_usdm_futures":
            _validate_binance_futures_close_only(self)
            return
        raise ExitGuardValidationError(f"Unsupported exit guard exchange: {self.exchange}")


@dataclass(frozen=True)
class ProtectiveExitOrderRecord:
    record_id: str
    signal_id: str
    created_at_utc: datetime
    intent: RiskReducingOrderIntent
    status: str
    audit_message: str = "Dry-run protective exit record only. No order was placed."
    provider_order_id: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at_utc", ensure_utc(self.created_at_utc))
        if self.provider_order_id is not None:
            raise ExitGuardValidationError("Provider order ids are not created in the MVP dry-run foundation.")


def _validate_upbit_spot_sell_only(intent: RiskReducingOrderIntent) -> None:
    if intent.action != "sell_only":
        raise ExitGuardValidationError("Upbit protective exit supports sell_only action only.")
    if intent.side != "ask":
        raise ExitGuardValidationError("Upbit protective exit must use side=ask.")
    if intent.position_mode is not None or intent.position_side is not None:
        raise ExitGuardValidationError("Upbit spot intents must not carry futures position fields.")
    if intent.reduce_only is True:
        raise ExitGuardValidationError("Upbit spot does not use reduce_only.")


def _validate_binance_futures_close_only(intent: RiskReducingOrderIntent) -> None:
    if intent.action not in {"close_long", "close_short"}:
        raise ExitGuardValidationError("Binance Futures protective exit supports close_long/close_short only.")
    if intent.position_mode not in {"one_way", "hedge"}:
        raise ExitGuardValidationError("Binance Futures position mode must be known.")

    expected_side = "SELL" if intent.action == "close_long" else "BUY"
    if intent.side != expected_side:
        raise ExitGuardValidationError(f"{intent.action} must use side={expected_side}.")

    if intent.position_mode == "one_way":
        if intent.position_side not in {None, "BOTH"}:
            raise ExitGuardValidationError("One-way Futures close intents must use positionSide=BOTH or omit it.")
        if intent.reduce_only is not True:
            raise ExitGuardValidationError("One-way Futures close intents require reduceOnly=true.")
        return

    expected_position_side = "LONG" if intent.action == "close_long" else "SHORT"
    if intent.position_side != expected_position_side:
        raise ExitGuardValidationError(
            f"Hedge Futures {intent.action} must use positionSide={expected_position_side}."
        )
    if intent.reduce_only is True:
        raise ExitGuardValidationError("Hedge Mode Futures close intents must not set reduceOnly.")
