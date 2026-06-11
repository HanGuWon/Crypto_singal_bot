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
- top-N entry when the candidate also meets the alert score threshold
- score acceleration
- breakout watch on known component threshold crossing with volume and liquidity confirmation
- system/data/API failure events as `SYSTEM_ERROR` with CRITICAL severity; these are not trading signals
- risk warning
- invalidation
- data-quality invalidation flags for previously alerted candidates
- non-stale data-quality warning events for previously alerted candidates with warn-level quality
- stale, missing-candle, and failed-quality suppression
- closed-candle only suppression
- single-extreme-component suppression
- low-liquidity, wide-spread, missing-orderbook, and stale-orderbook suppression
- symbol quarantine and missing-benchmark suppression

Alert events and formatted messages carry both `data_timestamp_utc` and `data_freshness_seconds`.
This makes freshness visible to downstream output adapters without letting notification code affect
scoring or ranking.
When saved research runs are available, CLI notification evaluation uses the previous compatible
exchange/quote/interval run snapshots for previous score, rank, and component-crossing context.

Dedupe, cooldown, and hysteresis:

- Dedupe keys include exchange, symbol, interval, event type, score bucket, and driver hash.
- Cooldown is per exchange/symbol/interval/event type.
- Hysteresis enters at the alert threshold and exits only below the exit threshold.
- Global notification limits cap event fan-out per minute.
- Per-symbol notification limits cap repeated alerts per hour.
- Safety-priority warnings use separate bounded quota from normal watchlist alerts.
- Rate-limited events are saved with `suppressed_by_rate_limit` delivery status for audit.
- `alert-test --channel noop` formats only; enabled Telegram/Discord `alert-test` runs persist
  sample alert events, outbox rows, and delivery audit rows.
- Terminal channel failures such as Telegram 401/403 and Discord 401/403/404 are quarantined in
  `notification_channel_state` until manual reset/configuration repair.
- Provider 429 failures preserve parsed `retry_after` metadata after bounded retries are exhausted,
  so cooldown state and outbox audit rows can explain the next retry window.
- The CLI creates `notification_outbox` rows before provider sends, then claims and completes those
  rows during dispatch.
- The outbox drain command records undeliverable rows instead of silently skipping them: missing
  alert payloads become terminal failures, while currently unavailable channel/destination matches
  remain retryable with an explicit error code.
- Outbox drain `--max` and `--max-retries` must be positive, so manual or timer-based drains stay
  bounded. `failed_retryable` rows that already reached `--max-retries` are terminalized with
  `outbox_retry_limit_exceeded` before any provider call is attempted.
- Digest support is a separate disabled-by-default policy path. `DigestPolicy` can build a
  research-only digest preview with top candidates and major score changes, but it does not dispatch
  provider messages and does not affect instant alert policy. Digest rows include candidate data
  timestamps and freshness seconds for auditability.
- `notifications digest preview` can build a local JSON digest from stored or mocked public-market
  candidates. If `ALERT_DIGEST_ENABLED=false`, it skips unless `--force-preview` is passed; even
  forced previews do not create outbox rows or send Telegram/Discord messages.

Telegram:

- Uses Bot API `sendMessage`.
- Enforces message length and preserves the research-only warning.
- Handles HTTP 429 `retry_after`.
- Does not retry 401/403 indefinitely.

Discord:

- Uses a webhook payload with embeds.
- Includes `allowed_mentions: {"parse": []}` by default.
- Clips long embed field values before dispatch while preserving the research-only warning in
  top-level content and embed description.
- Handles HTTP 429 `Retry-After` or JSON `retry_after`.
- Does not retry 401/403/404 indefinitely.
