from __future__ import annotations

import json
from pathlib import Path

from crypto_signal_bot.cli import main
from crypto_signal_bot.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def test_binance_spot_research_profile_is_default_safe() -> None:
    settings = load_settings(ROOT / "configs" / "binance_spot_research.yaml")

    assert settings.primary_exchange == "binance"
    assert settings.default_quote == "USDT"
    assert settings.binance_enabled is True
    assert settings.upbit_enabled is False
    assert settings.public_data_only is True
    assert settings.live_trading_enabled is False
    assert settings.private_api_enabled is False
    assert settings.require_manual_approval is True
    assert settings.notifications_enabled is False
    assert settings.telegram_enabled is False
    assert settings.discord_webhook_enabled is False
    assert settings.exit_guard.enabled is False
    assert settings.exit_guard.private_read_enabled is False
    assert settings.exit_guard.live_exit_enabled is False


def test_gcp_free_tier_binance_profile_disables_upbit_and_notifications() -> None:
    settings = load_settings(ROOT / "configs" / "gcp_free_tier_binance.yaml")

    assert settings.primary_exchange == "binance"
    assert settings.upbit_enabled is False
    assert settings.binance_enabled is True
    assert settings.notifications_enabled is False
    assert settings.telegram_enabled is False
    assert settings.discord_webhook_enabled is False
    assert settings.exit_guard.enabled is False


def test_profile_rank_and_strategy_scan_mock_smoke(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "profile.sqlite"))
    profile = str(ROOT / "configs" / "binance_spot_research.yaml")

    assert main(["rank", "--profile", profile, "--interval", "5m", "--top", "3", "--format", "json", "--mock"]) == 0
    rank_output = capsys.readouterr().out
    rank_payload = json.loads(rank_output[rank_output.find("{") :])

    assert rank_payload["candidates"]
    assert {candidate["exchange"] for candidate in rank_payload["candidates"]} == {"binance"}
    assert {candidate["quote_asset"] for candidate in rank_payload["candidates"]} == {"USDT"}

    assert (
        main([
            "strategy",
            "scan",
            "--profile",
            profile,
            "--base-interval",
            "5m",
            "--timeframes",
            "5m,15m,30m",
            "--strategy",
            "binance_liquid_momentum_v2",
            "--top",
            "5",
            "--format",
            "json",
            "--mock",
        ])
        == 0
    )
    strategy_output = capsys.readouterr().out
    strategy_payload = json.loads(strategy_output[strategy_output.find("{") :])
    first = strategy_payload["candidates"][0]

    assert strategy_payload["strategy"] == "binance_liquid_momentum_v2"
    assert first["entry_strategy"] == "binance_liquid_momentum_v2"
    assert "directional_view" in first
    assert "confidence_calibration" in first
    assert "evidence_grade" in first
    assert first["why_not_trade_signal"] == "Research screen only; not a trade instruction."
    assert first["next_validation_needed"]


def test_readme_keeps_binance_public_data_default_boundary() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()

    assert "profit factor" not in readme
    assert "collect --exchange upbit" not in readme
    assert "python -m crypto_signal_bot.cli exit-guard" not in readme
    assert "binance spot public-data mvp" in readme
    assert "research watchlist only. not financial advice. no order was placed." in readme


def test_protective_exit_docs_state_dry_run_boundary() -> None:
    text = (ROOT / "docs" / "protective_exit_guard.md").read_text(encoding="utf-8").lower()

    assert "dry-run only. no order placed. no private api. not financial advice." in text


def test_public_docs_avoid_forbidden_recommendation_wording() -> None:
    files = [
        ROOT / "README.md",
        ROOT / "docs" / "safety.md",
        ROOT / "docs" / "notifications.md",
        ROOT / "docs" / "methodology.md",
        ROOT / "docs" / "acceptance_audit.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8").lower() for path in files)
    forbidden = [
        "buy now",
        "guaranteed",
        "sure profit",
        "pump now",
        "moon",
        "entry signal",
        "take profit",
        "urgent buy",
        "financial advice phrasing",
        "지금 매수",
        "확정 수익",
        "무조건 수익",
        "급등 보장",
    ]

    for phrase in forbidden:
        assert phrase not in text
