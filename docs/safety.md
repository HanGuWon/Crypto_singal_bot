# Safety

This project is public-market-data research software.

Hard defaults:

```env
LIVE_TRADING_ENABLED=false
PRIVATE_API_ENABLED=false
REQUIRE_MANUAL_APPROVAL=true
NOTIFICATIONS_ENABLED=false
TELEGRAM_ENABLED=false
DISCORD_WEBHOOK_ENABLED=false
```

Unsafe modes fail closed during config validation. There is no live trading code path in the MVP.
Numeric environment values are parsed through config-owned validators, so malformed or unsafe
threshold/rate-limit values fail with `ConfigError` before collection, scoring, or notification
dispatch starts.
System/data/API failure alerts use `SYSTEM_ERROR` events with CRITICAL severity and research-only
wording. They are audit events, not buy/sell instructions.
CLI exchange/API failures are recorded as `SYSTEM_ERROR` alert events for auditability, without
creating notification outbox rows or any trading action.

The exchange safety guard uses explicit allowlists. Unknown endpoints are rejected by default.
Private, account, execution, funding, deposit, and withdrawal paths are not part of the client
interfaces.

Data-quality quarantine:

- Symbol health is stored locally for each exchange, symbol, and interval.
- Stale candles, incomplete candles, invalid OHLCV, timestamp drift, missing candles, warning or
  inactive markets, and insufficient history are quarantined conservatively.
- Upbit can omit candles when no trade occurred. Small internal Upbit gaps are marked as
  `upbit_possible_no_trade_gap` instead of `missing_candles`; this remains a data-quality warning
  and does not create alert eligibility by itself.
- Quarantined symbols can remain visible as research candidates with risk flags, but they cannot
  trigger upside alerts.
- Missing benchmarks lower alert eligibility; this is a research-data-quality guard, not a market
  prediction.

Research run exports:

- Saved runs are reproducibility artifacts for research review.
- Exports include safe config hashes and score explanations, not raw secrets.
- Exports are not financial advice, not trade instructions, and not performance claims.

Backtest diagnostics:

- Backtest output is a hypothetical diagnostic event study.
- It uses next-candle entries for leakage checks but does not model execution or portfolio
  management.
- Output flags explicitly mark that it is not a portfolio simulator, not financial advice, and no
  order was placed.

Entry timing research:

- Entry timing uses closed public candles only.
- It is a second-stage research overlay on top of the upside score.
- `falling_knife_suppress` and `invalidated` block upside alerts.
- Stochastic confirmation is not a standalone signal.
- The layer does not place orders, does not read balances, and does not call private exchange APIs.

Protective exit guard note:

- Current protective exit guard work is a design foundation only.
- It adds safe defaults, model-level validation, and public orderbook slippage preflight checks, not
  exchange adapters or order submission.
- The orderbook preflight uses public depth snapshots only and blocks dry-run review when the
  snapshot is missing, stale, shallow, or above the configured slippage threshold.
- The exit guard symbol allowlist is required by default. A symbol that is not listed in
  `EXIT_GUARD_SYMBOL_ALLOWLIST` produces a blocked dry-run event and cannot create a manual
  approval request.
- Preflight age and slippage thresholds are configurable, but invalid non-positive values fail
  closed during config validation.
- Manual approval requests are audit records only. Recording an approval does not enable private
  reads, live execution, or exchange order endpoints. Each request includes a binding hash tying
  the approval record to its source event, exchange, symbol, action, side, quantity, and position
  scope for later audit review.
- Protective exit alert events are Discord-only research events and remain gated by disabled-by-default
  notification settings.
- Any future private-account or execution safety feature is out of scope for this public-data MVP.
- Such a feature would need a separate safety review and must stay outside the public-data
  screener path.
- The current repository contains no live trading code path.

Secrets:

- No private exchange keys are needed.
- Telegram tokens and Discord webhook URLs are treated as secrets.
- `.env` is ignored.
- Logging redacts Telegram and Discord secrets.

Research wording:

- Outputs use candidate, watchlist, score, drivers, and risk flags.
- Outputs must not claim certainty or profit prediction.
- Alerts include: `Research alert only. Not financial advice. No order was placed.`

Repository governance:

- Configure GitHub branch protection or a ruleset for `main`.
- Require the `test` GitHub Actions job.
- Require pull requests and at least one review.
- Disable force pushes and branch deletions.
- Apply the rule to administrators when practical.
- Consider signed commits if this repository is shared beyond a private research workflow.
