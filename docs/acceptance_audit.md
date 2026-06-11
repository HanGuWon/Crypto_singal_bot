# Acceptance Audit

This audit maps the current repository to the pasted research and architecture notes. It is a
progress artifact, not a completion certificate. The project remains a research-only public-market
data screener unless a future safety review explicitly approves a separate private-account module.

Status labels:

- `Proved`: implementation exists and is covered by tests or validation commands.
- `Implemented with MVP limitations`: implementation exists, but intentionally stops short of a
  production-grade version.
- `Evidence gap`: the repository may contain partial work, but the requirement is not fully proved.
- `Intentional follow-up`: deliberately out of scope for this public-data MVP.

## Current Evidence

Latest local and CI evidence should be refreshed whenever this file changes. The most recent audit
cycle used these checks:

```bash
python -m pytest
python -m ruff check .
git diff --check
rg ...  # private/order/account/funding endpoint safety search
rg ...  # forbidden recommendation wording safety search
uv run --with mypy mypy src
```

The current commit's CI result should be checked in GitHub Actions after every push. A previously
successful run when this audit was introduced was:

- https://github.com/HanGuWon/Crypto_singal_bot/actions/runs/27299681163

## Safety Boundary

| Requirement | Status | Evidence |
| --- | --- | --- |
| Research-only public screener, not financial advice | Proved | `README.md`, `docs/safety.md`, alert formatters, CLI output warnings |
| No live trading path in the MVP | Proved | `docs/safety.md`, `src/crypto_signal_bot/exchanges/safety.py`, safety grep, tests |
| Default config disables trading, private APIs, notifications | Proved | `src/crypto_signal_bot/config.py`, `.env.example`, `tests/test_config.py` |
| Unknown exchange endpoints reject by default | Proved | `src/crypto_signal_bot/exchanges/safety.py`, `tests/test_exchange_safety.py` |
| No committed secrets | Proved | `.gitignore`, `.env.example`, notification redaction tests |
| Forbidden recommendation wording is blocked | Proved | Formatter blocklist and wording safety tests |
| Future live-trading code path absent | Proved for MVP | The current code has no private order submission adapters or execution modules |
| Protective exit guard stays separate from screener | Proved | `src/crypto_signal_bot/exit_guard`, `docs/protective_exit_guard.md` |
| Protective exit guard private/live behavior | Intentional follow-up | Private reads, order-test adapters, and live execution are explicitly absent |

## Public Data And Exchange Layer

| Requirement | Status | Evidence |
| --- | --- | --- |
| Upbit KRW market universe | Proved | `src/crypto_signal_bot/exchanges/upbit.py`, mocked CLI tests |
| Binance USDT spot universe | Proved | `src/crypto_signal_bot/exchanges/binance.py`, mocked CLI tests |
| Recent public candles | Proved | Exchange clients and collector path |
| Ticker / 24h summary snapshots | Proved | `src/crypto_signal_bot/data/store.py`, `src/crypto_signal_bot/data/collector.py` |
| Shallow orderbook snapshots with conservative caps | Proved | Collector flags, orderbook age checks, slippage/preflight tests |
| SQLite local storage with migrations | Proved | `SQLiteStore`, migration tests, `db doctor` |
| Upbit missing no-trade candles handled carefully | Proved | Data quality emits `upbit_possible_no_trade_gap`, gap classification, and policy reason; scoring and CLI tests |
| Cross-exchange canonical asset mapping | Proved | `data/symbols.py` emits canonical asset/pair ids, ranked candidates expose them, symbol normalization tests |
| WebSocket support | Intentional follow-up | REST-only MVP by design |

## Features, Scoring, And Ranking

| Requirement | Status | Evidence |
| --- | --- | --- |
| EMA, RSI, volatility, ATR-like range, breakout, volume z-score | Proved | `features/indicators.py`, `features/feature_builder.py`, tests |
| Relative strength and benchmark-aware diagnostics | Proved | Feature builder, scoring, ranking tests |
| Deterministic interpretable 0-100 score | Proved | `signals/scoring.py`, `tests/test_scoring.py` |
| Component scores, drivers, risk flags, confidence | Proved | `signals/schemas.py`, CLI smoke tests |
| Closed-candle only signal generation | Proved | Data models, backtest leakage checks, entry timing tests |
| Entry timing layer from pasted notes | Proved | Stochastic, three-tick, bottoming, rank overlay, `strategy scan --save-run`, entry timing snapshots, tests |
| Stochastic alone must not create a candidate | Proved | `signals/entry_timing.py`, `tests/test_entry_timing.py` |
| Falling-knife suppression | Proved | `features/three_tick.py`, `features/bottoming.py`, tests |
| Multi-timeframe confirmation | Proved | `rank --include-entry-timing --confirmation-intervals`, `strategy scan`, alignment validation, CLI tests |

## Alerts And Notifications

| Requirement | Status | Evidence |
| --- | --- | --- |
| Notification code is independent from scoring | Proved | `alerts/` and `notifications/` are separated from `signals/` |
| Noop notifier default | Proved | Config defaults, notification disabled tests |
| Telegram and Discord disabled by default | Proved | Config and `.env.example` |
| Telegram bounded retry and safe truncation | Proved | `notifications/telegram.py`, tests |
| Discord safe `allowed_mentions` | Proved | `notifications/discord_webhook.py`, tests |
| Alert policy suppresses stale, incomplete, low-liquidity, critical-risk candidates | Proved | `alerts/policy.py`, alert policy tests |
| Cooldown, dedupe, hysteresis | Proved | Alert tests and SQLite state |
| Outbox delivery audit and retry terminalization | Proved | Dispatcher/store/outbox CLI tests; `alert_events` stores key event metadata as searchable columns plus payload JSON |
| Digest | Implemented with MVP limitations | Disabled policy path and local preview CLI, no scheduler daemon |
| System/API failure events | Proved | CLI exchange/API failures and unexpected runtime failures create redacted `SYSTEM_ERROR` events; system alert tests |

## Backtesting And Research Diagnostics

| Requirement | Status | Evidence |
| --- | --- | --- |
| No lookahead, entry after signal candle | Proved | `backtest/leakage_checks.py`, tests |
| Fees, spread, slippage sensitivity | Proved | `backtest/engine.py`, CLI docs |
| Benchmarks and deterministic baselines | Proved | Backtest engine and strategy event-study |
| Walk-forward and stress/calibration diagnostics | Implemented with MVP limitations | Diagnostic output exists where local inputs are available |
| Research portfolio simulator | Implemented with MVP limitations | Synthetic equal-weight capped portfolio simulation exists; production execution/account simulation remains out of scope |
| Notification logic excluded from performance computation | Proved | Backtest and strategy event-study paths do not dispatch alerts |

## Deployment And Operations

| Requirement | Status | Evidence |
| --- | --- | --- |
| GCP free-tier conservative profile | Proved | `configs/gcp_free_tier.yaml`, `docs/deploy_gcp_free_tier.md` |
| Systemd/logrotate/backup examples | Proved | `scripts/systemd`, `scripts/logrotate`, `scripts/sqlite_backup.sh` |
| Notifications disabled in deployment profile | Proved | GCP profile and systemd outbox guard |
| Pricing/current cloud constraints | Implemented with MVP limitations | Dated official-doc check in `docs/deploy_gcp_free_tier.md`; users must still re-check billing pages |

## Protective Exit Guard Audit

The pasted integrated report introduced a higher-risk future module. The repository currently
contains only the safe foundation:

- domain models that reject non-risk-reducing intent shapes
- dry-run public orderbook preflight
- closed-candle public trend-break research signals
- audit persistence for protective exit signal/event records
- Discord-safe alert event construction
- manual approval records that are audit-only and do not unlock execution

Still absent by design:

- Upbit private account reads
- Upbit order-test or live sell adapter
- Binance Futures private position reads
- Binance order-test or live close adapter
- any private key requirement
- any live order submission path

## Remaining Follow-Ups

1. Run a fresh full validation cycle after every meaningful implementation batch.
2. Expand the acceptance matrix only when new code is backed by tests.
3. Keep private-account Protective Exit Guard work in a separate safety-reviewed phase.
4. If private reads are ever added, keep them isolated from scoring, ranking, and public-data
   backtesting.
5. Treat full portfolio simulation, WebSockets, and production daemons as later architecture work,
   not hidden MVP scope.
