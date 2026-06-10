# Notifications

Notifications are output adapters only. They do not affect scoring, ranking, data collection, or
backtesting.

Flow:

```text
SignalCandidate
  -> AlertPolicy
  -> AlertEvent
  -> Notification rate limiter
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
- single-extreme-component suppression
- low-liquidity, wide-spread, missing-orderbook, and stale-orderbook suppression
- symbol quarantine and missing-benchmark suppression

Alert events and formatted messages carry both `data_timestamp_utc` and `data_freshness_seconds`.
This makes freshness visible to downstream output adapters without letting notification code affect
scoring or ranking.

Dedupe, cooldown, and hysteresis:

- Dedupe keys include exchange, symbol, interval, event type, score bucket, and driver hash.
- Cooldown is per exchange/symbol/interval/event type.
- Hysteresis enters at the alert threshold and exits only below the exit threshold.
- Global notification limits cap event fan-out per minute.
- Per-symbol notification limits cap repeated alerts per hour.
- Safety-priority warnings use separate bounded quota from normal watchlist alerts.
- Rate-limited events are saved with `suppressed_by_rate_limit` delivery status for audit.
- Terminal channel failures such as Telegram 401/403 and Discord 401/403/404 are quarantined in
  `notification_channel_state` until manual reset/configuration repair.
- Provider 429 failures preserve parsed `retry_after` metadata after bounded retries are exhausted,
  so cooldown state and outbox audit rows can explain the next retry window.
- The CLI creates `notification_outbox` rows before provider sends, then claims and completes those
  rows during dispatch.
- Digest support is a separate disabled-by-default policy path. `DigestPolicy` can build a
  research-only digest preview with top candidates and major score changes, but it does not dispatch
  provider messages and does not affect instant alert policy. Digest rows include candidate data
  timestamps and freshness seconds for auditability.

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
