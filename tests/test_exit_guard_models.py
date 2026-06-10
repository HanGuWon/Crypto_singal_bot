from __future__ import annotations

from datetime import UTC, datetime

import pytest

from crypto_signal_bot.exit_guard.models import (
    BalanceSnapshot,
    ExitGuardValidationError,
    FuturesPositionSnapshot,
    ProtectiveExitOrderRecord,
    ProtectiveExitSignal,
    RiskReducingOrderIntent,
)


def test_upbit_sell_only_intent_is_valid_in_dry_run() -> None:
    intent = RiskReducingOrderIntent(
        exchange="upbit_spot",
        symbol="KRW-BTC",
        action="sell_only",
        side="ask",
        quantity=0.01,
    )

    assert intent.dry_run is True
    assert intent.manual_approval_required is True


def test_upbit_buy_action_is_rejected() -> None:
    with pytest.raises(ExitGuardValidationError):
        RiskReducingOrderIntent(
            exchange="upbit_spot",
            symbol="KRW-BTC",
            action="buy",
            side="bid",
            quantity=0.01,
        )


def test_binance_one_way_long_close_requires_sell_reduce_only() -> None:
    intent = RiskReducingOrderIntent(
        exchange="binance_usdm_futures",
        symbol="BTCUSDT",
        action="close_long",
        side="SELL",
        quantity=0.01,
        position_mode="one_way",
        position_side="BOTH",
        reduce_only=True,
    )

    assert intent.reduce_only is True


def test_binance_one_way_non_reduce_only_is_rejected() -> None:
    with pytest.raises(ExitGuardValidationError):
        RiskReducingOrderIntent(
            exchange="binance_usdm_futures",
            symbol="BTCUSDT",
            action="close_long",
            side="SELL",
            quantity=0.01,
            position_mode="one_way",
            position_side="BOTH",
            reduce_only=False,
        )


def test_binance_short_close_must_use_buy_side() -> None:
    with pytest.raises(ExitGuardValidationError):
        RiskReducingOrderIntent(
            exchange="binance_usdm_futures",
            symbol="BTCUSDT",
            action="close_short",
            side="SELL",
            quantity=0.01,
            position_mode="one_way",
            position_side="BOTH",
            reduce_only=True,
        )


def test_binance_hedge_mode_uses_position_side_without_reduce_only() -> None:
    intent = RiskReducingOrderIntent(
        exchange="binance_usdm_futures",
        symbol="BTCUSDT",
        action="close_short",
        side="BUY",
        quantity=0.01,
        position_mode="hedge",
        position_side="SHORT",
    )

    assert intent.position_side == "SHORT"
    assert intent.reduce_only is None


def test_binance_hedge_mode_reduce_only_is_rejected() -> None:
    with pytest.raises(ExitGuardValidationError):
        RiskReducingOrderIntent(
            exchange="binance_usdm_futures",
            symbol="BTCUSDT",
            action="close_long",
            side="SELL",
            quantity=0.01,
            position_mode="hedge",
            position_side="LONG",
            reduce_only=True,
        )


def test_binance_unknown_mode_is_rejected() -> None:
    with pytest.raises(ExitGuardValidationError):
        RiskReducingOrderIntent(
            exchange="binance_usdm_futures",
            symbol="BTCUSDT",
            action="close_long",
            side="SELL",
            quantity=0.01,
            position_mode="unknown",
            position_side="LONG",
        )


def test_live_intent_is_absent_from_mvp() -> None:
    with pytest.raises(ExitGuardValidationError):
        RiskReducingOrderIntent(
            exchange="upbit_spot",
            symbol="KRW-BTC",
            action="sell_only",
            side="ask",
            quantity=0.01,
            dry_run=False,
        )


def test_signal_and_snapshots_validate_safety_invariants() -> None:
    now = datetime.now(tz=UTC)
    signal = ProtectiveExitSignal(
        signal_id="sig",
        created_at_utc=now,
        exchange="binance_usdm_futures",
        symbol="BTCUSDT",
        interval="5m",
        state="WATCHING",
        exit_score=10.0,
    )
    balance = BalanceSnapshot(
        exchange="upbit_spot",
        asset="BTC",
        total=1.0,
        available=0.9,
        locked=0.1,
        observed_at_utc=now,
    )
    position = FuturesPositionSnapshot(
        exchange="binance_usdm_futures",
        symbol="BTCUSDT",
        position_mode="one_way",
        position_side="BOTH",
        position_amount=0.01,
        entry_price=100_000.0,
        mark_price=99_000.0,
        observed_at_utc=now,
    )

    assert signal.is_closed_candle_signal is True
    assert balance.available == 0.9
    assert position.position_mode == "one_way"


def test_order_record_remains_dry_run_without_provider_order_id() -> None:
    now = datetime.now(tz=UTC)
    intent = RiskReducingOrderIntent(
        exchange="upbit_spot",
        symbol="KRW-BTC",
        action="sell_only",
        side="ask",
        quantity=0.01,
    )
    record = ProtectiveExitOrderRecord(
        record_id="record",
        signal_id="signal",
        created_at_utc=now,
        intent=intent,
        status="dry_run_recorded",
    )

    assert record.provider_order_id is None
    assert "No order was placed" in record.audit_message
