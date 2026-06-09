from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.cli import _score_from_store, main
from crypto_signal_bot.config import Settings
from crypto_signal_bot.data.collector import make_mock_candles
from crypto_signal_bot.data.quality import assess_candles
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.features.feature_builder import build_feature_snapshot
from crypto_signal_bot.research import config_hash, safe_config
from crypto_signal_bot.signals.scoring import ScoringEngine


def test_rank_save_run_and_export_is_research_safe(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "runs.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-secret-token")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/secret")

    assert (
        main([
            "rank",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--mock",
            "--save-run",
            "--format",
            "json",
        ])
        == 0
    )
    rank_payload = _json_output(capsys.readouterr().out)
    run_id = rank_payload["saved_run_id"]

    assert main(["runs", "show", run_id]) == 0
    show_payload = _json_output(capsys.readouterr().out)
    assert show_payload["run"]["run_id"] == run_id
    assert show_payload["snapshot_count"] > 0

    assert main(["runs", "export", run_id, "--format", "json"]) == 0
    export_text = capsys.readouterr().out
    export_payload = _json_output(export_text)
    assert export_payload["run"]["config_hash"]
    assert export_payload["feature_snapshots"]
    assert "telegram-secret-token" not in export_text
    assert "discord.com/api/webhooks" not in export_text
    lowered = export_text.lower()
    for forbidden in ["buy", "sell", "profit", "guaranteed"]:
        assert forbidden not in lowered


def test_same_mock_input_and_config_produces_same_scores_and_config_hash(tmp_path) -> None:
    candles = make_mock_candles("binance", "USDT", "5m", limit=160)
    settings = Settings(database_path=tmp_path / "unused.sqlite")
    first_store = SQLiteStore(tmp_path / "first.sqlite")
    second_store = SQLiteStore(tmp_path / "second.sqlite")
    first_store.upsert_candles(candles)
    second_store.upsert_candles(candles)

    first = _score_from_store(first_store, "binance", "USDT", "5m", 3, settings)
    second = _score_from_store(second_store, "binance", "USDT", "5m", 3, settings)

    assert [(candidate.symbol, candidate.score) for candidate in first] == [
        (candidate.symbol, candidate.score) for candidate in second
    ]
    assert config_hash(settings) == config_hash(settings)


def test_config_hash_changes_when_research_config_changes() -> None:
    assert config_hash(Settings()) != config_hash(Settings(min_history_bars=120))
    safe = json.dumps(safe_config(Settings(telegram_bot_token="secret", discord_webhook_url="secret")))
    assert "secret" not in safe


def test_score_explanation_reconciles_to_final_score() -> None:
    candles = [
        candle
        for candle in make_mock_candles("binance", "USDT", "5m", limit=160)
        if candle.symbol == "BTCUSDT"
    ]
    quality = assess_candles(candles, "5m", now=datetime.now(tz=UTC) + timedelta(minutes=1))
    snapshot = build_feature_snapshot(candles, quality=quality)
    engine = ScoringEngine()
    candidate = engine.score(snapshot, source_run_id="run")
    explanation = engine.explain(snapshot, candidate)

    assert abs(float(explanation["reconstructed_score"]) - candidate.score) <= 0.1
    assert explanation["component_contributions"]
    assert isinstance(explanation["penalties"], dict)


def test_quarantine_and_missing_benchmark_are_exported(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "runs.sqlite"))
    monkeypatch.setenv("MIN_HISTORY_BARS", "200")

    assert (
        main([
            "rank",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--mock",
            "--save-run",
            "--format",
            "json",
        ])
        == 0
    )
    run_id = _json_output(capsys.readouterr().out)["saved_run_id"]
    assert main(["runs", "export", run_id]) == 0
    payload = _json_output(capsys.readouterr().out)
    explanations = [snapshot["score_explanation"] for snapshot in payload["feature_snapshots"]]

    assert any(explanation["benchmark_available"] is False for explanation in explanations)
    assert any(explanation["quarantine_reason"] == "insufficient_history" for explanation in explanations)


def _json_output(text: str) -> dict[str, object]:
    return json.loads(text[text.find("{") :])
