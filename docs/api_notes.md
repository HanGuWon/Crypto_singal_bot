# API Notes

The MVP uses exchange-specific clients and public endpoints only.

Upbit:

- Base URL: `https://api.upbit.com`
- Market list: `/v1/market/all`
- Minute candles: `/v1/candles/minutes/{unit}`
- Ticker: `/v1/ticker`
- Orderbook: `/v1/orderbook`

Upbit rate-limit handling parses `Remaining-Req` and uses the `sec` field. The deprecated `min`
field is ignored. HTTP 429 is retried with bounded backoff. HTTP 418 fails the client request.

Binance:

- Base URL: `https://data-api.binance.vision`
- Exchange info: `/api/v3/exchangeInfo`
- Klines: `/api/v3/klines`
- 24h ticker: `/api/v3/ticker/24hr`
- Depth/orderbook: `/api/v3/depth`

Binance request weights are tracked from `X-MBX-USED-WEIGHT-1M`. HTTP 429 is retried with bounded
backoff and `Retry-After` when present. HTTP 418 fails the client request.
