# Methodology

The MVP uses a deterministic, explainable composite score instead of ML.

Data flow:

```text
Public market data
  -> local SQLite candles
  -> data quality checks
  -> closed-candle feature snapshot
  -> composite scoring
  -> ranked research watchlist
  -> optional entry timing research overlay
  -> optional alert policy
  -> optional notification adapter
```

Feature groups:

- Trend: price versus EMA20/EMA50 and EMA20 slope.
- Momentum: short and medium horizon log returns.
- Volume: quote-volume z-score and acceleration.
- Breakout: close versus prior rolling high.
- Relative strength: asset return minus BTC benchmark return when available.
- Liquidity: quote volume and spread when orderbook data exists.
- Risk: stale data, failed quality, wide spread, low liquidity, excess volatility, wick risk.

Signals are generated only from closed candles. Backtest entries must occur after the signal candle
close, using the next candle open in the smoke engine.

Diagnostic backtest summaries report event counts, hit rate, average return, average win/loss,
gain/loss factor, max drawdown, Sharpe, Sortino, worst return, and 5th-percentile tail loss. These
are event-study diagnostics, not a portfolio execution model.

Entry timing research:

- The original upside score remains the first-stage candidate score.
- Entry timing adds `entry_timing_score` and `research_priority_score` for review workflows.
- Three-tick and bottoming evidence describe whether a setup is not ready, forming, on watch,
  confirmed as a research candidate, reset, suppressed, or invalidated.
- Stochastic is confirmation/invalidation evidence only, never a standalone signal.
- Data-quality failures, incomplete candles, stale data, low liquidity, wide spreads, quarantined
  symbols, `falling_knife_suppress`, and `invalidated` prevent upside alerts.
