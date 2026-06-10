# Three-Tick Bottoming Research Strategy

This strategy is a research-only entry timing overlay. It does not trade, does not place orders,
does not call private exchange APIs, and is not financial advice.

## Purpose

The main screener produces an interpretable upside score. The three-tick bottoming layer keeps that
score intact and adds a second-stage timing view for review:

- `entry_timing_status`
- `entry_timing_score`
- `research_priority_score`
- strategy and timeframe metadata
- reason codes
- entry-specific risk flags
- entry timing invalidation text

## Statuses

- `not_ready`: insufficient or unconvincing closed-candle evidence.
- `forming`: partial evidence exists, but the setup is not ready for the watchlist overlay.
- `watch`: three-tick or bottoming evidence is present, but confirmation is incomplete.
- `confirmed_candidate`: research-only confirmation from three-tick plus stochastic confirmation, or
  confirmed bottoming evidence with acceptable liquidity and data quality.
- `flow_broken_reset`: a large bullish rebound broke the three-tick down-flow pattern.
- `falling_knife_suppress`: decline is too steep or too persistent without enough bottoming evidence.
- `invalidated`: data quality failed, support failed, a critical risk is present, or confirmation
  turned down.

These are research states, not trading instructions.

## Evidence

Three-tick evidence:

- Counts meaningful bearish pressure on closed candles.
- Merges tiny bearish candles instead of over-counting noise, using an adaptive movement unit based
  on minimum bps, ATR, and median body size.
- Does not count a normal bullish-to-bearish transition unless the bearish transition is large
  versus either fixed bps or recent body/range context.
- Allows small bullish rebounds, but a large rebound resets the flow.
- Suppresses steep unconfirmed declines as `falling_knife_suppress`.

Bottoming evidence:

- Looks for shrinking candle bodies.
- Looks for compressed closes.
- Looks for repeated lower-wick support.
- Invalidates when support fails.
- Suppresses steep unconfirmed declines.

Stochastic evidence:

- A cross up can confirm an existing setup.
- A cross down can invalidate a watched setup.
- A stochastic cross by itself cannot create a confirmed candidate.

## CLI

Add entry timing fields to normal ranking:

```bash
python -m crypto_signal_bot.cli rank --exchange binance --quote USDT --interval 5m --top 20 --format json --include-entry-timing
```

Run a strategy scan across timeframes:

```bash
python -m crypto_signal_bot.cli strategy scan --exchange binance --quote USDT --base-interval 5m --timeframes 5m,15m,30m --strategy three_tick --top 20 --format json --mock
```

The strategy scan ranks by `research_priority_score`. The original upside `score` is still included
for transparency. Strategy scans accept only the public candle intervals `1m`, `3m`, `5m`, `15m`,
and `30m`, and the JSON output includes a `timeframe_alignment` block showing the UTC alignment
anchor used for the requested interval set.

Run a diagnostic strategy event study:

```bash
python -m crypto_signal_bot.cli strategy event-study --exchange binance --quote USDT --interval 5m --horizons 1,3,6,12 --fee-bps 10 --spread-bps 5 --slippage-bps 5 --format json --mock
```

The event study compares research variants across forward bar horizons. It uses closed-candle
signals, next-candle-open diagnostic entries, BTC/ETH benchmark windows, and falling-knife
exclusion summaries. It reports the configured fee/spread/slippage model and zero/configured/
double-cost sensitivity summaries. It includes deterministic random-symbol and liquidity-ranked
baselines using the same point-in-time windows. It also reports diagnostic high-volatility,
thin-liquidity, benchmark-drawdown, and API-outage timestamp-gap slices. It is not a portfolio
simulator and does not use notification logic.

## Alert Safety

Upside alerts are suppressed when:

- the current candle is incomplete
- data is stale or failed
- the symbol is quarantined
- liquidity or spread checks fail
- a critical risk flag is present
- entry timing status is `falling_knife_suppress`
- entry timing status is `invalidated`

Notifications remain disabled by default and are output adapters only.
