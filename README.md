# Crypto Signal Bot

Research-only crypto market signal screener for public Upbit and Binance market data.

This project is not a live trading bot, does not place orders, does not use private exchange
endpoints, and is not financial advice. It outputs a ranked research watchlist with transparent
component scores, drivers, risk flags, confidence, timestamps, and data-quality status.

## Supported Public Data

- Upbit KRW public quotation endpoints: market list, minute candles, ticker, orderbook.
- Binance spot public market-data endpoints on `data-api.binance.vision`: exchange info, klines,
  24h ticker, depth/orderbook.
- UTC is used internally. KST can be used for display-facing workflows later.

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
```

Use public live collection with conservative caps:

```bash
python -m crypto_signal_bot.cli collect --exchange upbit --quote KRW --interval 5m --limit 200 --max-symbols 20
python -m crypto_signal_bot.cli collect --exchange binance --quote USDT --interval 5m --limit 200 --max-symbols 20
```

Backtest smoke check:

```bash
python -m crypto_signal_bot.cli backtest --exchange binance --quote USDT --interval 15m --mock
```

Notification formatting test:

```bash
python -m crypto_signal_bot.cli alert-test --channel noop
```

## Output Format

Each candidate includes:

- exchange, symbol, interval
- current price
- score from 0 to 100
- component scores
- confidence tier
- rank
- drivers
- risk flags
- invalidation condition
- data timestamp UTC
- source run id
- closed-candle and data-quality status

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
development.

## Known Limitations

- This is an MVP screener, not a production research platform.
- Live collection is REST-only; WebSocket support is intentionally absent for now.
- Backtesting is a leakage-safe smoke engine, not a full portfolio simulator yet.
- Scoring is interpretable and deterministic but not a profit prediction.
- Cross-exchange normalization is not implemented.
