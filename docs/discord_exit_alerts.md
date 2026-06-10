# Discord Exit Alerts

This document covers protective exit guard alert boundaries. The current MVP can build structured
exit guard `AlertEvent` objects for research review, but it does not dispatch them unless global
notifications and Discord exit guard alerts are explicitly enabled. It does not call private
exchange APIs and does not submit orders.

## Channel Boundary

Protective exit guard alerts are Discord-only by design. Telegram is intentionally not used for this
module. The exit guard alert flag is disabled by default and is valid only when global notifications,
Discord webhook notifications, and a Discord webhook URL are configured.

```env
NOTIFICATIONS_ENABLED=false
DISCORD_WEBHOOK_ENABLED=false
DISCORD_WEBHOOK_URL=
EXIT_GUARD_DISCORD_ALERTS_ENABLED=false
EXIT_GUARD_TELEGRAM_ENABLED=false
```

## Message Requirements

Every exit guard alert payload must include:

- exchange and symbol
- position or balance context, if a future private-read phase is implemented
- state and risk-reduction reason
- safety-block reasons, if any
- dry-run/manual-approval/live phase label
- audit id (`alert_event_id`) and source run id (`source_run_id`)
- manual approval request id when `--request-approval` created a pending audit record
- research and safety warning

When a manual approval request id is attached to an exit alert, the saved and dispatched event uses
a dedupe key recomputed from that final driver set and risk-flag set.

Required wording:

```text
Protective exit guard alert.
Risk-reduction only.
Not financial advice.
No new position was opened.
No order was placed.
```

Current event types are:

- `PROTECTIVE_EXIT_WATCH`
- `PROTECTIVE_EXIT_BLOCKED`

Blocked events are warnings for research review only. Public-candle `SAFETY_BLOCKED` signals and
blocked public orderbook preflights both format as `PROTECTIVE_EXIT_BLOCKED`; they are not
execution instructions.

## Mention Safety

Discord payloads must use safe mention handling. The existing Discord webhook adapter defaults to
`allowed_mentions: {"parse": []}` unless explicitly configured otherwise. Exit guard alerts should
keep mention parsing disabled.

## Failure Isolation

Notification failure must not influence public-data scoring, ranking, backtesting, or any future
exit guard state transition. Webhook URLs must be redacted in logs and shown only as destination
hashes in operational output.
