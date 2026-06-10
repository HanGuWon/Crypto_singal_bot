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
EXIT_GUARD_SYMBOL_ALLOWLIST=
EXIT_GUARD_DISCORD_ALERTS_ENABLED=false
EXIT_GUARD_TELEGRAM_ENABLED=false
EXIT_GUARD_MAX_ORDERBOOK_AGE_SECONDS=30
EXIT_GUARD_MAX_SLIPPAGE_PCT=1.0
```

In this MVP, enabling private reads or live exits fails closed during config validation.

## Public Orderbook Slippage Preflight

The phase-1 code can assess a dry-run protective intent against a public orderbook snapshot before
any future human review. This is a research safety check only. It does not read balances, does not
open private sessions, and does not submit orders.

The preflight blocks when:

- `EXIT_GUARD_REQUIRE_SYMBOL_WHITELIST=true` and the symbol is not listed in
  `EXIT_GUARD_SYMBOL_ALLOWLIST`
- no public orderbook snapshot is available
- the snapshot is stale or timestamped in the future
- the relevant bid or ask side has no usable depth
- visible depth cannot cover the requested quantity
- estimated adverse slippage is above the configured threshold

The default public orderbook preflight thresholds are 30 seconds of maximum snapshot age and 1.0%
maximum estimated adverse slippage. They can be adjusted with
`EXIT_GUARD_MAX_ORDERBOOK_AGE_SECONDS` and `EXIT_GUARD_MAX_SLIPPAGE_PCT`, or overridden per CLI
dry-run with `--max-orderbook-age-seconds` and `--max-slippage-pct`.
The allowlist accepts comma-separated raw symbols or exchange-scoped symbols, for example
`BTCUSDT,upbit_spot:KRW-BTC`.

For sell-only spot review and close-long futures review, the preflight walks public bids. For
close-short futures review, it walks public asks. The result is an assessment with `pass` or
`blocked` status, estimated slippage, filled quantity, and risk flags for audit output.

## Closed-Candle Trend-Break Dry Run

The phase-2 foundation can build a protective-exit research signal from public candles only. It is
not connected to balances, positions, private exchange endpoints, or order submission. The signal
engine ignores open candles and uses only closed candles for:

- recent swing low or swing high break detection
- EMA trend confirmation
- ATR-scaled break distance
- quote/base volume z-score confirmation
- adverse move and rebound diagnostics
- optional multi-timeframe confirmation summaries

Supported dry-run states are:

- `WATCHING`
- `WARNING`
- `EXIT_CANDIDATE`
- `EXIT_CONFIRMED`
- `SEVERE_EXIT_CANDIDATE`
- `SAFETY_BLOCKED`

`SAFETY_BLOCKED` is used for failed data quality, insufficient closed-candle history, or missing
indicator history. It is a warning/audit state only and does not unlock execution. Long and spot
exposures look for downside swing breaks. Short exposures look for upside swing breaks. These are
risk-reduction research states, not performance claims.

## Research Alert Event Boundary

The phase-1 code can convert a protective exit signal and public orderbook preflight result into a
structured `AlertEvent`. This is only an event-building boundary. Dispatch still goes through the
existing notification dispatcher, remains disabled by default, and is valid only for Discord when
the global Discord notification settings are explicitly enabled.

Protective exit alert events include dry-run/manual-approval drivers and use event types such as
`PROTECTIVE_EXIT_WATCH` and `PROTECTIVE_EXIT_BLOCKED`. A blocked public orderbook preflight is a
warning event, not an execution instruction.

CLI dry-run example:

```bash
python -m crypto_signal_bot.cli exit-guard signal --exchange binance_usdm_futures --symbol BTCUSDT --interval 5m --exposure-side long --mock-candles --save-event
python -m crypto_signal_bot.cli exit-guard signal --exchange binance_usdm_futures --symbol BTCUSDT --interval 5m --exposure-side short --confirmation-intervals 15m,30m --mock-candles
python -m crypto_signal_bot.cli exit-guard preflight --exchange binance_usdm_futures --symbol BTCUSDT --action close_long --side SELL --quantity 0.003 --position-mode one_way --position-side BOTH --reduce-only --mock-orderbook --save-event
python -m crypto_signal_bot.cli exit-guard preflight --exchange binance_usdm_futures --symbol BTCUSDT --action close_short --side BUY --quantity 0.003 --position-mode one_way --position-side BOTH --reduce-only --mock-orderbook --request-approval
python -m crypto_signal_bot.cli exit-guard events list --limit 10
python -m crypto_signal_bot.cli exit-guard events show ALERT_EVENT_ID
python -m crypto_signal_bot.cli exit-guard approvals list --status pending
python -m crypto_signal_bot.cli exit-guard approvals approve REQUEST_ID --confirm --note "reviewed"
```

Adding `--notify` does not send anything unless global notifications, Discord webhook notifications,
and `EXIT_GUARD_DISCORD_ALERTS_ENABLED=true` are all enabled. Telegram remains disallowed for this
module. Adding `--save-event` stores the generated dry-run `AlertEvent` in the local
`alert_events` audit table, and the `events` commands read those saved research events without
sending notifications. If `--notify` is requested, the dry-run `AlertEvent` is persisted even when
`--save-event` is omitted, and every delivery outcome is recorded in `notification_deliveries`.
With default disabled notification settings this creates a skipped `noop` delivery record rather
than contacting Discord. The `exit-guard events show` command returns both the saved event and the
matching delivery audit rows, so dry-run notification behavior can be inspected without exposing
secrets or sending an order.

Adding `--request-approval` creates a manual approval request bound to the dry-run event and the
validated risk-reducing intent. Each request stores a deterministic binding hash over the source
event, exchange, symbol, action, side, quantity, position mode, and position side so later audit
inspection can verify the approval scope. Approval requests expire, can be approved or rejected
only with `--confirm`, and remain audit records only. Requests are not created when the public
preflight is blocked, including when the symbol is not allowlisted. They do not enable private
reads, live orders, sell orders, close orders, or any exchange endpoint.

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

1. Design foundation only: config, models, validation, public orderbook preflight, alert-event
   boundary, documentation.
2. Dry-run signal generation from closed public candles only.
3. Private read adapters for balances/positions only, still no live orders.
4. Exchange order-test or testnet-only validation, still no live orders.
5. Manual approval flow for audit-only approvals.
6. Limited live close-only/sell-only execution only after a separate safety review.

The repository currently has phase 1 and the public-candle portion of phase 2. It still has no
private read adapter, no order-test adapter, and no live execution path.
