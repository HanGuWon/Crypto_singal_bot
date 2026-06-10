# Discord Exit Alerts

This document covers future protective exit guard alerts only. The current MVP does not send exit
guard alerts, does not call private exchange APIs, and does not submit orders.

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

Every future exit guard alert must include:

- exchange and symbol
- position or balance context, if a future private-read phase is implemented
- state and risk-reduction reason
- safety-block reasons, if any
- dry-run/manual-approval/live phase label
- audit id
- research and safety warning

Required wording:

```text
Protective exit guard alert.
Risk-reduction only.
Not financial advice.
No new position was opened.
```

## Mention Safety

Discord payloads must use safe mention handling. The existing Discord webhook adapter defaults to
`allowed_mentions: {"parse": []}` unless explicitly configured otherwise. Exit guard alerts should
keep mention parsing disabled.

## Failure Isolation

Notification failure must not influence public-data scoring, ranking, backtesting, or any future
exit guard state transition. Webhook URLs must be redacted in logs and shown only as destination
hashes in operational output.
