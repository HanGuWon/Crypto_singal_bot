from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_gcp_free_tier_profile_is_conservative() -> None:
    profile = (ROOT / "configs" / "gcp_free_tier.yaml").read_text(encoding="utf-8")

    assert "enabled: false" in profile
    assert "disable_websocket: true" in profile
    assert "disable_dashboard: true" in profile
    assert "disable_large_backtests: true" in profile
    assert "max_symbols_per_exchange: 60" in profile
    assert "max_orderbook_symbols: 10" in profile
    assert "notifications_enabled: false" in profile
    assert "live_trading_enabled: false" in profile
    assert "private_api_enabled: false" in profile
    assert "outbox_drain_timer_enabled: false" in profile
    assert "outbox_drain_max_rows: 10" in profile
    assert "exit_guard_live_exit_enabled: false" in profile
    assert "exit_guard_require_symbol_whitelist: true" in profile
    assert "exit_guard_symbol_allowlist: []" in profile
    assert "exit_guard_max_orderbook_age_seconds: 30" in profile
    assert "exit_guard_max_slippage_pct: 1.0" in profile
    assert "us-west1" in profile
    assert "us-central1" in profile
    assert "us-east1" in profile
    assert "asia-northeast3" in profile


def test_gcp_free_tier_deployment_artifacts_exist() -> None:
    required = [
        "Dockerfile",
        ".dockerignore",
        "docs/deploy_gcp_free_tier.md",
        "scripts/sqlite_backup.sh",
        "scripts/logrotate/crypto_signal_bot",
        "scripts/systemd/crypto-signal-bot-collect.service",
        "scripts/systemd/crypto-signal-bot-collect.timer",
        "scripts/systemd/crypto-signal-bot-rank.service",
        "scripts/systemd/crypto-signal-bot-rank.timer",
        "scripts/systemd/crypto-signal-bot-outbox-drain.service",
        "scripts/systemd/crypto-signal-bot-outbox-drain.timer",
        "scripts/systemd/crypto-signal-bot-db-backup.service",
        "scripts/systemd/crypto-signal-bot-db-backup.timer",
        "scripts/systemd/crypto-signal-bot-db-maintenance.service",
        "scripts/systemd/crypto-signal-bot-db-maintenance.timer",
    ]

    for relative_path in required:
        assert (ROOT / relative_path).exists()


def test_gcp_free_tier_docs_keep_safety_defaults_visible() -> None:
    docs = (ROOT / "docs" / "deploy_gcp_free_tier.md").read_text(encoding="utf-8")

    assert "LIVE_TRADING_ENABLED=false" in docs
    assert "PRIVATE_API_ENABLED=false" in docs
    assert "NOTIFICATIONS_ENABLED=false" in docs
    assert "EXIT_GUARD_LIVE_EXIT_ENABLED=false" in docs
    assert "EXIT_GUARD_REQUIRE_SYMBOL_WHITELIST=true" in docs
    assert "EXIT_GUARD_SYMBOL_ALLOWLIST=" in docs
    assert "EXIT_GUARD_MAX_ORDERBOOK_AGE_SECONDS=30" in docs
    assert "EXIT_GUARD_MAX_SLIPPAGE_PCT=1.0" in docs
    assert "notifications outbox drain --max 10" in docs
    assert "db prune-retention --profile configs/gcp_free_tier.yaml" in docs
    assert "--execute --vacuum" in docs
    assert "dry run" in docs
    assert "asia-northeast3" in docs
    assert "Always Free" in docs
    assert "As of June 11, 2026" in docs
    assert "3 free jobs per month" in docs
    assert "10,000 access operations" in docs
    assert "SQLite persistence issue" in docs
    assert "Always check current billing pages" in docs


def test_gcp_free_tier_constraints_anchor_matches_profile_and_docs() -> None:
    profile = (ROOT / "configs" / "gcp_free_tier.yaml").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "deploy_gcp_free_tier.md").read_text(encoding="utf-8")
    constraints = json.loads((ROOT / "docs" / "gcp_free_tier_constraints.json").read_text(encoding="utf-8"))

    assert constraints["checked_at_utc"] == "2026-06-11T00:00:00+00:00"
    assert constraints["official_doc_currentness_is_time_bounded"] is True
    assert constraints["recheck_before_deploy"] is True
    assert constraints["source_urls"] == {
        "google_cloud_free_tier": "https://docs.cloud.google.com/free/docs/free-cloud-features",
        "cloud_scheduler_pricing": "https://cloud.google.com/scheduler/pricing",
        "cloud_run_pricing": "https://cloud.google.com/run/pricing",
        "secret_manager_pricing": "https://cloud.google.com/secret-manager/pricing",
    }

    compute = constraints["compute_engine_always_free"]
    assert compute["machine_type"] == "e2-micro"
    assert compute["standard_persistent_disk_gb_month"] == 30
    assert compute["north_america_outbound_transfer_gb_month"] == 1
    for region in compute["regions"]:
        assert region in profile
        assert region in docs
    for region in compute["excluded_region_examples"]:
        assert region in profile
        assert region in docs
    assert constraints["cloud_scheduler"]["free_jobs_per_month_per_billing_account"] == 3
    assert constraints["cloud_scheduler"]["free_tier_scope"] == "billing_account"
    assert constraints["cloud_run_jobs"]["sqlite_persistence_requires_storage_refactor"] is True
    assert constraints["secret_manager"]["active_secret_versions_free_per_month"] == 6
    assert constraints["secret_manager"]["access_operations_free_per_month"] == 10000
    assert "gcp_free_tier_constraints.json" in docs


def test_gcp_outbox_drain_timer_is_bounded_and_disabled_safe() -> None:
    service = (ROOT / "scripts" / "systemd" / "crypto-signal-bot-outbox-drain.service").read_text(
        encoding="utf-8"
    )
    timer = (ROOT / "scripts" / "systemd" / "crypto-signal-bot-outbox-drain.timer").read_text(
        encoding="utf-8"
    )

    assert 'if [ "$NOTIFICATIONS_ENABLED" != "true" ]' in service
    assert "skipping outbox drain" in service
    assert "notifications outbox drain --max 10" in service
    assert "OnUnitActiveSec=1min" in timer


def test_gcp_db_maintenance_timer_prunes_profile_retention() -> None:
    service = (ROOT / "scripts" / "systemd" / "crypto-signal-bot-db-maintenance.service").read_text(
        encoding="utf-8"
    )
    timer = (ROOT / "scripts" / "systemd" / "crypto-signal-bot-db-maintenance.timer").read_text(
        encoding="utf-8"
    )

    assert "db prune-retention --profile configs/gcp_free_tier.yaml --execute --vacuum" in service
    assert "OnCalendar=weekly" in timer
    assert "Persistent=true" in timer
