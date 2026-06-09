from __future__ import annotations

from crypto_signal_bot.exchanges.binance import binance_depth_request_weight
from crypto_signal_bot.exchanges.rate_limit import BinanceWeightLimiter, parse_upbit_remaining_req


def test_upbit_remaining_req_uses_sec_and_ignores_min() -> None:
    group, sec = parse_upbit_remaining_req("group=candle; min=1800; sec=2")
    assert group == "candle"
    assert sec == 2


def test_binance_weight_limiter_tracks_used_weight() -> None:
    limiter = BinanceWeightLimiter(max_weight_per_minute=100, safety_margin=0.8)
    limiter.update_from_headers({"X-MBX-USED-WEIGHT-1M": "79"})
    assert limiter.should_backoff(1)


def test_binance_depth_weight_depends_on_limit() -> None:
    assert binance_depth_request_weight(100) == 5
    assert binance_depth_request_weight(500) == 25
    assert binance_depth_request_weight(1000) == 50
    assert binance_depth_request_weight(5000) == 250
