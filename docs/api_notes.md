# API Notes

The MVP uses exchange-specific clients and public endpoints only.

Upbit:

- Base URL: `https://api.upbit.com`
- Market list: `/v1/market/all`
- Minute candles: `/v1/candles/minutes/{unit}`
- Ticker: `/v1/ticker`
- Orderbook: `/v1/orderbook`

Upbit rate-limit handling parses `Remaining-Req` and uses the `sec` field. The deprecated `min`
field is ignored. HTTP 429 is retried with bounded backoff. `Retry-After` may be seconds or an
HTTP-date. HTTP 418 fails the client request. Server-side collectors do not send an `Origin`
header, avoiding Upbit's stricter browser-origin polling policy.

Binance:

- Base URL: `https://data-api.binance.vision`
- Exchange info: `/api/v3/exchangeInfo`
- Klines: `/api/v3/klines`
- 24h ticker: `/api/v3/ticker/24hr`
- Depth/orderbook: `/api/v3/depth`

Collection policy:

- Candle collection remains the primary polling path.
- Public 24h ticker snapshots are stored during collection unless `--skip-tickers` is used.
- Public shallow orderbook snapshots are opt-in via `--with-orderbook` and capped by
  `--max-orderbook-symbols`.
- Ranking uses the latest stored orderbook snapshot when present; otherwise the candidate carries an
  `orderbook_unavailable` research risk flag.
- Ranking marks snapshots older than `MAX_ORDERBOOK_AGE_SECONDS` as `stale_orderbook` and snapshots
  timestamped in the future as `orderbook_timestamp_drift`.

Binance request weights are tracked from `X-MBX-USED-WEIGHT-1M`. HTTP 429 is retried with bounded
backoff and `Retry-After` when present as seconds or an HTTP-date. HTTP 418 fails the client
request. The public `exchangeInfo.rateLimits` `REQUEST_WEIGHT` per-minute limit updates the local
soft weight limiter when available.
