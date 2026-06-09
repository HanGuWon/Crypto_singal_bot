# Notifications

Notifications are output adapters only. They do not affect scoring, ranking, data collection, or
backtesting.

Flow:

```text
SignalCandidate
  -> AlertPolicy
  -> AlertEvent
  -> NotificationDispatcher
  -> NoopNotifier / TelegramNotifier / DiscordWebhookNotifier
```

`NoopNotifier` is the default. Telegram and Discord are disabled unless both global notifications
and the specific channel are enabled.

AlertPolicy handles:

- score threshold crossing
- top-N entry
- score acceleration
- breakout watch
- risk warning
- invalidation
- stale and failed-quality suppression
- closed-candle only suppression
- low-liquidity and wide-spread suppression

Dedupe, cooldown, and hysteresis:

- Dedupe keys include exchange, symbol, interval, event type, score bucket, and driver hash.
- Cooldown is per exchange/symbol/interval/event type.
- Hysteresis enters at the alert threshold and exits only below the exit threshold.

Telegram:

- Uses Bot API `sendMessage`.
- Enforces message length and preserves the research-only warning.
- Handles HTTP 429 `retry_after`.
- Does not retry 401/403 indefinitely.

Discord:

- Uses a webhook payload with embeds.
- Includes `allowed_mentions: {"parse": []}` by default.
- Handles HTTP 429 `Retry-After` or JSON `retry_after`.
- Does not retry 401/403/404 indefinitely.
