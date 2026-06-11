from __future__ import annotations

from datetime import UTC, datetime

from conftest import make_candidate
from crypto_signal_bot.alerts.digest import DigestPolicy, DigestPolicyConfig


def test_digest_policy_disabled_by_default() -> None:
    digest = DigestPolicy().build_digest([make_candidate()])

    assert digest is None


def test_digest_schedule_status_is_disabled_by_default() -> None:
    status = DigestPolicy().schedule_status(now=datetime(2026, 1, 1, tzinfo=UTC))

    payload = status.to_dict()
    assert payload["enabled"] is False
    assert payload["due"] is False
    assert payload["notification_status"] == "disabled"
    assert payload["separate_policy_path"] is True
    assert payload["scheduler_daemon_required"] is False
    assert payload["no_notification_was_sent"] is True
    assert payload["research_warning"].endswith("No order was placed.")


def test_digest_schedule_status_tracks_due_window() -> None:
    policy = DigestPolicy(DigestPolicyConfig(enabled=True, interval_minutes=60))
    last_digest_at = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    not_due = policy.schedule_status(
        last_digest_at=last_digest_at,
        now=datetime(2026, 1, 1, 0, 59, tzinfo=UTC),
    ).to_dict()
    due = policy.schedule_status(
        last_digest_at=last_digest_at,
        now=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
    ).to_dict()
    first = policy.schedule_status(now=datetime(2026, 1, 1, 0, 0, tzinfo=UTC)).to_dict()

    assert not_due["due"] is False
    assert not_due["notification_status"] == "not_due"
    assert not_due["next_digest_at_utc"] == "2026-01-01T01:00:00+00:00"
    assert due["due"] is True
    assert due["notification_status"] == "due"
    assert first["due"] is True
    assert first["notification_status"] == "due_no_previous_digest"


def test_digest_policy_builds_top_candidates_and_major_changes() -> None:
    candidates = [
        make_candidate(symbol="BTCUSDT", rank=2, score=82.0),
        make_candidate(symbol="ETHUSDT", rank=1, score=90.0),
        make_candidate(symbol="ALPHAUSDT", rank=3, score=70.0),
    ]
    digest = DigestPolicy(DigestPolicyConfig(enabled=True, top_n=2, major_score_delta=8.0)).build_digest(
        candidates,
        previous_scores={"BTCUSDT": 70.0, "ETHUSDT": 89.0, "ALPHAUSDT": 55.0},
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert digest is not None
    payload = digest.to_dict()
    assert payload["notification_status"] == "not_scheduled"
    assert payload["research_warning"].startswith("Research digest only")
    assert [candidate["symbol"] for candidate in payload["top_candidates"]] == ["ETHUSDT", "BTCUSDT"]
    assert payload["top_candidates"][0]["data_freshness_seconds"] == 42.0
    assert [change["symbol"] for change in payload["major_changes"]] == ["ALPHAUSDT", "BTCUSDT"]


def test_digest_policy_excludes_failed_quality_and_critical_risk() -> None:
    candidates = [
        make_candidate(symbol="BTCUSDT", rank=1, score=90.0),
        make_candidate(
            symbol="STALEUSDT",
            rank=2,
            score=95.0,
            data_quality_status="warn",
            risk_flags=["stale_data"],
        ),
        make_candidate(symbol="SPREADUSDT", rank=3, score=96.0, risk_flags=["wide_spread"]),
    ]
    digest = DigestPolicy(DigestPolicyConfig(enabled=True, top_n=5)).build_digest(candidates)

    assert digest is not None
    assert [candidate["symbol"] for candidate in digest.to_dict()["top_candidates"]] == ["BTCUSDT"]
