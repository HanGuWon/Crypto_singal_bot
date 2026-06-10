# Methodology

The MVP uses a deterministic, explainable composite score instead of ML.

Data flow:

```text
Public market data
  -> local SQLite candles
  -> exchange/raw/base/quote symbol normalization
  -> data quality checks
  -> closed-candle feature snapshot
  -> data freshness propagation
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
- Risk: stale data, failed quality, timestamp drift, wide spread, low liquidity, excess volatility,
  wick risk.

Each feature snapshot carries the closed candle timestamp and freshness in seconds from the data
quality report. Ranked candidates, alert events, and digest rows expose the same freshness value so
research output can be audited without recomputing freshness inside notification adapters.
UTC remains the internal storage and scoring timezone; CLI output adds separate display timestamps
using `DISPLAY_TIMEZONE` for KST-facing review workflows.

Signals are generated only from closed candles. Backtest entries must occur after the signal candle
close, using the next candle open in the smoke engine.

Diagnostic backtest summaries report event counts, hit rate, average return, average win/loss,
gain/loss factor, max drawdown, Sharpe, Sortino, worst return, and 5th-percentile tail loss. These
are event-study diagnostics, not a portfolio execution model.

Baseline diagnostics compare the same event windows against BTC, universe median/equal-weight
returns, deterministic random-symbol selection, and a point-in-time liquidity-ranked symbol. Event
turnover and exposure fields describe signal-window overlap only; they are not account exposure,
allocation, or order execution.

Stress diagnostics split the same event-study records into high-volatility, thin-liquidity,
benchmark-drawdown, and API-outage-flagged windows. Calibration diagnostics bucket available
condition scores against later event returns. These sections are audit aids only and do not claim
predictive certainty.

Entry timing research:

- The original upside score remains the first-stage candidate score.
- Entry timing adds `entry_timing_score` and `research_priority_score` for review workflows.
- Three-tick and bottoming evidence describe whether a setup is not ready, forming, on watch,
  confirmed as a research candidate, reset, suppressed, or invalidated.
- Stochastic is confirmation/invalidation evidence only, never a standalone signal.
- Data-quality failures, incomplete candles, stale data, low liquidity, wide spreads, quarantined
  symbols, `falling_knife_suppress`, and `invalidated` prevent upside alerts.
