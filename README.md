# Crypto Signal Bot

Research-only crypto market signal screener for public Upbit and Binance market data.

This project is not a live trading bot, does not place orders, does not use private exchange
endpoints, and is not financial advice. It outputs a ranked research watchlist with transparent
component scores, drivers, risk flags, confidence, timestamps, and data-quality status.

## Supported Public Data

- Upbit KRW public quotation endpoints: market list, minute candles, ticker, orderbook.
- Binance spot public market-data endpoints on `data-api.binance.vision`: exchange info, klines,
  24h ticker, depth/orderbook.
- UTC is used internally. CLI JSON/table output also includes display timestamps using
  `DISPLAY_TIMEZONE` (default `Asia/Seoul`) for KST-facing review workflows.

Current endpoint choices were checked against official docs:

- [Upbit market list](https://docs.upbit.com/kr/reference/list-trading-pairs)
- [Upbit minute candles](https://docs.upbit.com/kr/reference/list-candles-minutes)
- [Upbit rate limits](https://docs.upbit.com/kr/reference/rate-limits)
- [Binance market-data-only domain](https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only)
- [Binance market data endpoints](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)
- [Binance limits](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/limits)

## Setup

```bash
python -m pip install -e ".[dev]"
copy .env.example .env
```

The MVP does not require exchange API keys.

## CLI Examples

Use mocked fixture data without live internet:

```bash
python -m crypto_signal_bot.cli collect --exchange binance --quote USDT --interval 5m --limit 120 --mock
python -m crypto_signal_bot.cli rank --exchange binance --quote USDT --interval 5m --top 10 --format table
python -m crypto_signal_bot.cli rank --exchange binance --quote USDT --interval 5m --top 10 --format json
python -m crypto_signal_bot.cli rank --exchange binance --quote USDT --interval 5m --top 10 --format json --save-run
python -m crypto_signal_bot.cli rank --exchange binance --quote USDT --interval 5m --top 10 --format json --include-entry-timing
python -m crypto_signal_bot.cli strategy scan --exchange binance --quote USDT --base-interval 5m --timeframes 5m,15m,30m --strategy three_tick --top 20 --format json --mock
python -m crypto_signal_bot.cli strategy event-study --exchange binance --quote USDT --interval 5m --horizons 1,3,6,12 --format json --mock
```

Use public live collection with conservative caps:

```bash
python -m crypto_signal_bot.cli collect --exchange upbit --quote KRW --interval 5m --limit 200 --max-symbols 20
python -m crypto_signal_bot.cli collect --exchange binance --quote USDT --interval 5m --limit 200 --max-symbols 20
python -m crypto_signal_bot.cli collect --exchange binance --quote USDT --interval 5m --limit 200 --max-symbols 20 --with-orderbook --max-orderbook-symbols 10
```

Collection stores closed public candles and 24h ticker snapshots by default. Shallow orderbook
snapshots are opt-in with `--with-orderbook` and capped by `--max-orderbook-symbols` to avoid
expensive polling loops. Ranking treats stored orderbook snapshots older than
`MAX_ORDERBOOK_AGE_SECONDS` as `stale_orderbook` research risk instead of silently trusting the
spread.
For Upbit, small internal candle gaps can be marked as `upbit_possible_no_trade_gap` because Upbit
may omit intervals with no trades. This is still a data-quality warning, not an alert trigger.

Backtest smoke check:

```bash
python -m crypto_signal_bot.cli backtest --exchange binance --quote USDT --interval 15m --mock
python -m crypto_signal_bot.cli backtest --exchange binance --quote USDT --interval 15m --from 2026-01-01 --to 2026-01-31 --mock
```

Backtest output is marked with `diagnostic_event_study_only=true`,
`not_portfolio_simulator=true`, `no_execution_model=true`, and `hypothetical_diagnostic_only=true`.
The MVP backtest path is a leakage-safety diagnostic with next-candle entries, benchmark/universe
context, cost sensitivity, data-quality-conditioned summaries, and return-distribution metrics such
as hit rate, average win/loss, gain/loss factor, profit factor, Sharpe, Sortino, max drawdown, and
tail loss. It also exposes diagnostic turnover and event-overlap exposure fields that describe
signal windows, not order turnover or account exposure. It is not a trading recommendation, not
financial advice, and no order is placed. Diagnostic comparisons include BTC/ETH benchmark-set
context, universe context, and deterministic random-symbol and liquidity-ranked baselines using the
same point-in-time windows. Baselines also include a point-in-time top-volume equal-weight basket.
Walk-forward diagnostics use expanding prior windows before later evaluation windows.
Universe diagnostics list requested symbols, evaluable symbols, empty candle symbols, and
delisted-or-missing asset candidates where the local candle inputs make that detectable. They are
survivorship-bias audit aids, not a complete delisting database.
Stress and calibration sections summarize high-volatility, thin-liquidity, benchmark-drawdown,
API-outage-flagged, and score-bucket windows when the required diagnostic inputs are available.
`--from` and `--to` are applied as UTC candle-open bounds; date-only `--to` includes that full UTC
calendar day.

The entry timing strategy event-study utilities are diagnostic-only and keep the same closed-candle
signal / next-candle-open entry rule. They compare strategy variants, forward horizons, benchmark
windows, fee/spread/slippage cost sensitivity, and falling-knife exclusion effects without using
notification logic. The CLI entry point is `strategy event-study`; use `--fee-bps`, `--spread-bps`,
and `--slippage-bps` to adjust the diagnostic cost model.

Notification formatting test:

```bash
python -m crypto_signal_bot.cli alert-test --channel noop
```

When notifications and a specific channel are explicitly enabled, `alert-test` sends the sample
research alert through the same audited outbox and delivery-log path used by ranking alerts.

Protective exit guard dry-run preflight:

```bash
python -m crypto_signal_bot.cli exit-guard signal --exchange binance_usdm_futures --symbol BTCUSDT --interval 5m --exposure-side long --mock-candles --save-event
python -m crypto_signal_bot.cli exit-guard preflight --exchange binance_usdm_futures --symbol BTCUSDT --action close_long --side SELL --quantity 0.003 --position-mode one_way --position-side BOTH --reduce-only --mock-orderbook
python -m crypto_signal_bot.cli exit-guard preflight --exchange upbit_spot --symbol KRW-BTC --action sell_only --side ask --quantity 0.01 --mock-orderbook --save-event --notify
python -m crypto_signal_bot.cli exit-guard preflight --exchange binance_usdm_futures --symbol BTCUSDT --action close_short --side BUY --quantity 0.003 --position-mode one_way --position-side BOTH --reduce-only --mock-orderbook --request-approval
python -m crypto_signal_bot.cli exit-guard signals list --limit 10
python -m crypto_signal_bot.cli exit-guard signals show SIGNAL_ID
python -m crypto_signal_bot.cli exit-guard events list --limit 10
python -m crypto_signal_bot.cli exit-guard events show ALERT_EVENT_ID
python -m crypto_signal_bot.cli exit-guard approvals list --status pending
python -m crypto_signal_bot.cli exit-guard approvals approve REQUEST_ID --confirm --note "reviewed"
```

The preflight command builds a research JSON event from public orderbook data only. The `--notify`
flag still does nothing unless global notifications, Discord webhook notifications, and
`EXIT_GUARD_DISCORD_ALERTS_ENABLED=true` are explicitly configured. Default preflight thresholds
are `EXIT_GUARD_MAX_ORDERBOOK_AGE_SECONDS=30` and `EXIT_GUARD_MAX_SLIPPAGE_PCT=1.0`; both can be
overridden per dry-run command. `EXIT_GUARD_REQUIRE_SYMBOL_WHITELIST=true` is also the default; set
`EXIT_GUARD_SYMBOL_ALLOWLIST` to comma-separated symbols such as `BTCUSDT,upbit_spot:KRW-BTC`
before expecting a dry-run preflight to become approval-eligible. `--save-event` persists the
dry-run `AlertEvent` to the local audit table without sending a notification or placing an order.
When `--notify` is used, the generated `AlertEvent` is also persisted for auditability and each
delivery attempt, failure, or disabled skip is recorded in `notification_deliveries`. `exit-guard
events show ALERT_EVENT_ID` includes the saved event and its notification delivery audit rows.
`--request-approval` creates a bounded manual approval audit record with a binding hash for the
source event, exchange, symbol, side, quantity, and position scope only when the public preflight
passes. Approval decisions re-check that binding before recording the decision. They are records
only; they do not unlock live execution. When `--notify` and `--request-approval` are used together,
the Discord-safe alert drivers include the manual approval request id for audit lookup.

The `exit-guard signal` command builds a public-candle trend-break research signal before any
orderbook preflight. It reads stored candles or deterministic mock candles, ignores open candles,
can include optional confirmation intervals, and can save the resulting `AlertEvent` for audit. It
also stores a dedicated protective-exit signal snapshot when saving or notifying. It does not read
balances or positions and does not create approval requests.

Database maintenance:

```bash
python -m crypto_signal_bot.cli db migrate
python -m crypto_signal_bot.cli db doctor
python -m crypto_signal_bot.cli db prune-retention --profile configs/gcp_free_tier.yaml
python -m crypto_signal_bot.cli db prune-retention --profile configs/gcp_free_tier.yaml --execute --vacuum
```

The local SQLite schema uses versioned migrations and `db doctor` validates required tables,
columns, and audit indexes. Retention pruning is dry-run by default; `--execute` is required before
rows are deleted.

Notification operations:

```bash
python -m crypto_signal_bot.cli notifications status
python -m crypto_signal_bot.cli notifications digest preview --exchange binance --quote USDT --interval 5m --mock --force-preview
python -m crypto_signal_bot.cli notifications channel-state list
python -m crypto_signal_bot.cli notifications channel-state reset --channel discord --destination-hash HASH --confirm
python -m crypto_signal_bot.cli notifications outbox list --status failed_retryable
python -m crypto_signal_bot.cli notifications outbox drain --max 10 --max-retries 3 --dry-run
```

Notification operations display destination hashes only. They do not print Telegram tokens or
Discord webhook URLs. Digest preview builds local JSON only; it never dispatches a provider
message and `--force-preview` does not enable scheduled digest delivery.

Research run reproducibility:

```bash
python -m crypto_signal_bot.cli runs list
python -m crypto_signal_bot.cli runs show RUN_ID
python -m crypto_signal_bot.cli runs export RUN_ID --format json
```

Saved runs include a commit SHA, safe config hash, data window, candidate count, feature snapshots,
component contributions, penalties, risk flags, freshness, data-quality notes, symbol-health notes,
optional entry timing snapshots, and the research-only warning. Exports are research artifacts only, not
financial advice or performance claims, and they do not include Telegram tokens, Discord webhook
URLs, or exchange secrets.

## Entry Timing Research Layer

`rank --include-entry-timing` keeps the original upside score intact and adds a second-stage,
closed-candle research view. This layer reports `entry_timing_status`, `entry_timing_score`,
`research_priority_score`, strategy metadata, reason codes, and entry-specific risk flags.

Supported statuses are:

- `not_ready`
- `forming`
- `watch`
- `confirmed_candidate`
- `flow_broken_reset`
- `falling_knife_suppress`
- `invalidated`

The stochastic oscillator is used only as confirmation or invalidation evidence. It is not a
standalone signal. `falling_knife_suppress` and `invalidated` suppress upside alerts. The strategy
scan CLI ranks by `research_priority_score`, and the three-tick layer uses adaptive movement
thresholds to avoid treating tiny bearish noise as separate ticks. It remains a research watchlist,
not a trade instruction.

See `docs/strategy_three_tick_bottoming.md` for details.

## Protective Exit Guard Foundation

The repository also contains a disabled-by-default protective exit guard design foundation. It adds
safe config defaults and domain model validation for future sell-only / close-only risk-reduction
research, plus a public orderbook slippage preflight that can block dry-run review when depth is
missing, stale, shallow, or too costly. It also includes a public-candle trend-break dry-run signal
engine that uses closed candles only to report `WATCHING`, `WARNING`, `EXIT_CANDIDATE`,
`EXIT_CONFIRMED`, `SEVERE_EXIT_CANDIDATE`, or `SAFETY_BLOCKED` research states. It can build
Discord-safe research alert events for protective-exit review, but dispatch remains disabled by
default. It does not add private exchange calls or live order submission.

See `docs/protective_exit_guard.md` and `docs/discord_exit_alerts.md` for the safety boundary.

See `docs/acceptance_audit.md` for the current requirement-by-requirement evidence map and known
gaps.

## GCP Free-Tier Profile

`configs/gcp_free_tier.yaml` and `docs/deploy_gcp_free_tier.md` provide a conservative VM-oriented
deployment profile for small REST-only research runs. The profile disables WebSockets, dashboards,
large backtests, notifications, and exit guard execution by default.

## Output Format

Each candidate includes:

- exchange, symbol, raw symbol, base asset, quote asset, interval
- current price
- score from 0 to 100
- component scores, including benchmark-aware market regime when benchmark data is available
- confidence tier
- rank
- drivers
- risk flags
- invalidation condition
- data timestamp UTC, display timestamp/timezone, and data freshness in seconds
- source run id
- closed-candle and data-quality status
- symbol health status, quarantine reason, history bars available, and benchmark availability
- optional entry timing status, score, research priority, reasons, and risk flags

All human-readable outputs include:

> Research watchlist only. Not financial advice. No order was placed.

## Notifications

Notifications are disabled by default:

```env
NOTIFICATIONS_ENABLED=false
TELEGRAM_ENABLED=false
DISCORD_WEBHOOK_ENABLED=false
```

The `--notify` flag does nothing unless global notifications and at least one concrete channel are
enabled. Alerts are research output only and cannot influence scoring, ranking, or backtesting.
Before dispatch, alert events are saved locally and filtered by the configured global and per-symbol
notification rate limits. Rate-limited alerts are recorded with `suppressed_by_rate_limit` status.
Safety-priority alerts such as risk warnings and invalidations use a separate bounded quota so they
are not blocked by earlier watchlist alerts. Terminal Telegram/Discord authorization or destination
failures are quarantined in local channel state until configuration is fixed.
Upside alerts are suppressed for quarantined symbols, stale, incomplete, or missing candle data,
low-liquidity candidates, candidates missing a usable benchmark or fresh orderbook, stale orderbook
snapshots, and high scores driven by only one extreme component.
Telegram, Discord, and digest payloads include the candidate data timestamp plus freshness in
seconds/minutes so stale-data decisions are visible in the research output.
Digest support is a disabled-by-default policy path that can build a research-only preview from top
candidates and major score changes. Use `notifications digest preview`; it does not dispatch
messages by itself.

Telegram placeholders:

```env
NOTIFICATIONS_ENABLED=true
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Discord placeholders:

```env
NOTIFICATIONS_ENABLED=true
DISCORD_WEBHOOK_ENABLED=true
DISCORD_WEBHOOK_URL=
DISCORD_ALLOW_MENTIONS=false
```

Secrets must never be committed. `.env`, local databases, logs, and caches are ignored by git.

## Tests

```bash
python -m pytest
python -m ruff check .
python -m mypy src
```

External API tests are not required by default. Use mocked CLI paths and unit tests for normal
development. Tests marked `integration` are excluded by default. Run
`python -m pytest -m integration tests/test_public_api_integration.py` only when intentionally
checking real public Upbit/Binance API behavior.

## Known Limitations

- This is an MVP screener, not a production research platform.
- Live collection is REST-only; WebSocket support is intentionally absent for now.
- Backtesting is a leakage-safe smoke engine, not a full portfolio simulator yet.
- Symbol health quarantine is conservative and local; it is intended to suppress weak research
  inputs, not to predict asset quality.
- Notification delivery audit includes a CLI outbox drain path and optional systemd timer example,
  including bounded retry terminalization, but a long-running outbox worker/daemon is still a
  production follow-up.
- Scoring is interpretable and deterministic but not a profit prediction.
- Symbol identity normalization is implemented for Upbit and common Binance spot quote suffixes,
  but full cross-exchange asset mapping remains intentionally simple.
- Entry timing logic is an MVP research overlay. It is not connected to orders, private APIs, or
  protective execution features.
- Protective exit guard work covers the design foundation, intent validation models, public
  orderbook preflight checks, disabled-by-default Discord-safe alert events, and public-candle
  trend-break dry-run signals. There are still no private exchange calls, order-test adapters, or
  live execution paths.
- GCP deployment artifacts are examples only; check current Google Cloud pricing before creating
  resources.
