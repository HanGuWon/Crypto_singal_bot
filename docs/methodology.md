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
