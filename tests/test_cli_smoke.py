from __future__ import annotations

import json

from crypto_signal_bot.cli import main


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


def test_cli_notify_skipped_when_disabled(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    main(["collect", "--exchange", "upbit", "--quote", "KRW", "--interval", "5m", "--limit", "80", "--mock"])
    assert main(["rank", "--exchange", "upbit", "--quote", "KRW", "--interval", "5m", "--top", "2", "--notify"]) == 0
    assert "notifications skipped because they are disabled" in capsys.readouterr().out
