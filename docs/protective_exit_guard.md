# Protective Exit Guard Design Foundation

This document describes a future, separate protective exit guard. The current MVP does not place
orders, does not call private exchange endpoints, and does not enable live execution.

## Purpose

The public screener answers which assets deserve research attention. The entry timing layer answers
whether a closed-candle timing pattern is forming. A protective exit guard would be a separate
risk-reduction module for already-held spot assets or already-open futures positions.

It must never become:

- an autonomous entry bot
- an averaging-down module
- a futures position-opening bot
- a withdrawal-capable system
- a profit guarantee or financial advice system

## Safe Defaults

The config foundation is disabled by default:

```env
EXIT_GUARD_ENABLED=false
EXIT_GUARD_DRY_RUN=true
EXIT_GUARD_PRIVATE_READ_ENABLED=false
EXIT_GUARD_LIVE_EXIT_ENABLED=false
EXIT_GUARD_REQUIRE_MANUAL_APPROVAL=true
EXIT_GUARD_REQUIRE_SYMBOL_WHITELIST=true
EXIT_GUARD_DISCORD_ALERTS_ENABLED=false
EXIT_GUARD_TELEGRAM_ENABLED=false
```

In this MVP, enabling private reads or live exits fails closed during config validation.

## Upbit Spot Sell-Only Shape

A future Upbit protective action may only reduce an already-held spot asset. The only allowed
high-level intent is `sell_only` with `side=ask`.

Disallowed:

- buy intent
- `side=bid`
- withdrawal or deposit endpoints
- live order submission in this MVP

## Binance USD-M Futures Close-Only Shape

A future Binance Futures protective action may only reduce existing exposure.

One-way mode:

- long close: `SELL`, `reduceOnly=true`, `positionSide=BOTH` or omitted
- short close: `BUY`, `reduceOnly=true`, `positionSide=BOTH` or omitted

Hedge mode:

- long close: `SELL`, `positionSide=LONG`, no `reduceOnly`
- short close: `BUY`, `positionSide=SHORT`, no `reduceOnly`

Unknown position mode blocks the intent. Any shape that could increase exposure is rejected by the
domain model.

## Discord-Only Exit Alerts

Exit guard alerts are intended to be Discord-only if this module is ever implemented. Telegram is
not used by the exit guard. Discord alerts must include safe `allowed_mentions` behavior from the
existing notification adapter and must not expose webhook URLs.

Required wording for future exit alerts:

```text
Protective exit guard alert.
Risk-reduction only.
Not financial advice.
No new position was opened.
```

See `docs/discord_exit_alerts.md` for the dedicated notification boundary.

## Rollout Phases

1. Design foundation only: config, models, validation, documentation.
2. Dry-run signal generation from closed public candles only.
3. Private read adapters for balances/positions only, still no live orders.
4. Exchange order-test or testnet-only validation, still no live orders.
5. Manual approval flow.
6. Limited live close-only/sell-only execution only after a separate safety review.

The repository is currently in phase 1 for this module.
