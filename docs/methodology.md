# Methodology

The MVP uses a deterministic, explainable composite score instead of ML.

Data flow:

```text
Public market data
  -> local SQLite candles
  -> exchange/raw/base/quote symbol normalization with canonical asset and pair ids
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
- Market regime: one-hour BTC/benchmark return when available; neutral fallback when unavailable.
- Liquidity: quote volume and spread when orderbook data exists.
- Risk: stale data, failed quality, timestamp drift, missing candles, stale or future-dated
  orderbook snapshots, wide spread, low liquidity, excess volatility, wick risk.

Each feature snapshot carries the closed candle timestamp and freshness in seconds from the data
quality report. Ranked candidates, alert events, and digest rows expose the same freshness value so
research output can be audited without recomputing freshness inside notification adapters.
The data-quality report also records gap classification and policy reason, distinguishing ordinary
missing-candle risk from small Upbit no-trade observation gaps.
UTC remains the internal storage and scoring timezone; CLI output adds separate display timestamps
using `DISPLAY_TIMEZONE` for KST-facing review workflows.

Signals are generated only from closed candles. Backtest entries must occur after the signal candle
close, using the next candle open in the smoke engine.

Diagnostic backtest summaries report event counts, hit rate, average return, average win/loss,
gain/loss factor, profit factor, max drawdown, Sharpe, Sortino, worst return, and 5th-percentile
tail loss. These are event-study diagnostics, not live execution results.

Baseline diagnostics compare the same event windows against BTC/ETH benchmark sets, universe
median/equal-weight returns, deterministic random-symbol selection, and a point-in-time
liquidity-ranked symbol. They also include a point-in-time top-volume equal-weight basket benchmark.
Event turnover and exposure fields describe signal-window overlap only; top-level
turnover/exposure diagnostics repeat those fields explicitly and are not account exposure,
allocation, or order execution.

The research portfolio simulation layer converts eligible event records into a synthetic
equal-weight portfolio with a configurable maximum number of open positions. It applies the same
fee/spread/slippage assumptions, enters only at the next candle open, excludes stale, low-liquidity,
wide-spread, and quarantined candidates, and reports turnover, exposure, final equity, trade-return
summary, and periodic return summary. It is not an exchange execution model and does not use
notification logic.
Universe diagnostics list requested signal symbols, available candle symbols, empty candle symbols,
and delisted-or-missing asset candidates when those gaps are visible in the local input set. This is
a survivorship-bias audit aid only, not a complete exchange delisting database.

Walk-forward diagnostics sort event-study records by signal timestamp, fit only on expanding prior
windows, and summarize later evaluation windows. They are audit aids for temporal robustness, not
claims of predictive certainty.

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
- Normal ranking can add aligned multi-timeframe confirmation summaries with
  `--confirmation-intervals`; these summaries do not replace score, ranking, or alert policy.
- `strategy scan --save-run` persists feature snapshots and entry timing snapshots for audit/export.
- Data-quality failures, incomplete candles, stale data, low liquidity, wide spreads, quarantined
  symbols, `falling_knife_suppress`, and `invalidated` prevent upside alerts.
