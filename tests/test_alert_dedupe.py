from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conftest import make_alert, make_candidate
from crypto_signal_bot.alerts.dedupe import DedupeCache, make_dedupe_key


def test_dedupe_key_is_stable_for_same_driver_bucket() -> None:
    candidate = make_candidate(score=86.1)
    same_bucket = make_candidate(score=87.9)
    assert make_dedupe_key(candidate, "TOP_N_ENTRY") == make_dedupe_key(same_bucket, "TOP_N_ENTRY")


def test_dedupe_cache_blocks_recent_duplicate() -> None:
    now = datetime.now(tz=UTC)
    cache = DedupeCache(ttl_minutes=60)
    event = make_alert()
    assert cache.should_send(event, now)
    assert not cache.should_send(event, now + timedelta(minutes=5))
