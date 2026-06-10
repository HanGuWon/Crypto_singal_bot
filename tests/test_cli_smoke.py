from __future__ import annotations

import json

from crypto_signal_bot.cli import main
from crypto_signal_bot.data.store import SQLiteStore


def test_cli_collect_and_rank_mock_json(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    assert main(
        ["collect", "--exchange", "binance", "--quote", "USDT", "--interval", "5m", "--limit", "80", "--mock"]
    ) == 0
    assert main(
        ["rank", "--exchange", "binance", "--quote", "USDT", "--interval", "5m", "--top", "2", "--format", "json"]
    ) == 0
    output = capsys.readouterr().out
    payload_text = output[output.find("{") :]
    payload = json.loads(payload_text)
    assert payload["research_warning"].startswith("Research watchlist only")
    assert len(payload["candidates"]) <= 2
    assert "score" in payload["candidates"][0]
    assert "symbol_health_status" in payload["candidates"][0]
    assert "history_bars_available" in payload["candidates"][0]
    assert "benchmark_available" in payload["candidates"][0]


def test_cli_notify_skipped_when_disabled(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    main(["collect", "--exchange", "upbit", "--quote", "KRW", "--interval", "5m", "--limit", "80", "--mock"])
    assert main(["rank", "--exchange", "upbit", "--quote", "KRW", "--interval", "5m", "--top", "2", "--notify"]) == 0
    assert "notifications skipped because they are disabled" in capsys.readouterr().out


def test_cli_rank_marks_insufficient_history(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("MIN_HISTORY_BARS", "120")
    assert main(
        ["collect", "--exchange", "binance", "--quote", "USDT", "--interval", "5m", "--limit", "80", "--mock"]
    ) == 0
    assert main(
        ["rank", "--exchange", "binance", "--quote", "USDT", "--interval", "5m", "--top", "1", "--format", "json"]
    ) == 0

    output = capsys.readouterr().out
    payload_text = output[output.find("{") :]
    candidate = json.loads(payload_text)["candidates"][0]
    assert candidate["symbol_health_status"] == "quarantined"
    assert candidate["quarantine_reason"] == "insufficient_history"
    assert "insufficient_history" in candidate["risk_flags"]


def test_cli_rank_can_include_entry_timing(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("MIN_QUOTE_VOLUME_BINANCE_USDT", "0")
    assert main(
        ["collect", "--exchange", "binance", "--quote", "USDT", "--interval", "5m", "--limit", "100", "--mock"]
    ) == 0

    assert main(
        [
            "rank",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--top",
            "2",
            "--format",
            "json",
            "--include-entry-timing",
        ]
    ) == 0

    output = capsys.readouterr().out
    payload_text = output[output.find("{") :]
    candidate = json.loads(payload_text)["candidates"][0]
    assert candidate["entry_timing_status"] != "not_evaluated"
    assert "entry_timing_score" in candidate
    assert "research_priority_score" in candidate


def test_cli_strategy_scan_mock_json(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("MIN_QUOTE_VOLUME_BINANCE_USDT", "0")

    assert main(
        [
            "strategy",
            "scan",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--base-interval",
            "5m",
            "--timeframes",
            "5m,15m",
            "--strategy",
            "three_tick",
            "--top",
            "3",
            "--format",
            "json",
            "--mock",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["strategy"] == "three_tick"
    assert payload["research_warning"].startswith("Research watchlist only")
    assert len(payload["candidates"]) <= 3
    assert payload["candidates"][0]["entry_strategy"] == "three_tick"
    assert payload["candidates"][0]["entry_timing_status"] != "not_evaluated"
    assert "buy now" not in json.dumps(payload).lower()


def test_saved_run_includes_entry_timing_snapshots(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MIN_QUOTE_VOLUME_BINANCE_USDT", "0")
    assert main(
        ["collect", "--exchange", "binance", "--quote", "USDT", "--interval", "5m", "--limit", "100", "--mock"]
    ) == 0

    assert main(
        [
            "rank",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--top",
            "2",
            "--format",
            "json",
            "--include-entry-timing",
            "--save-run",
        ]
    ) == 0

    output = capsys.readouterr().out
    payload_text = output[output.find("{") :]
    run_id = json.loads(payload_text)["saved_run_id"]
    store = SQLiteStore(db_path)
    assert len(store.get_entry_timing_snapshots(run_id)) == 2
