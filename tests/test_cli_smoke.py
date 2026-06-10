from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.cli import _filter_candles_by_date_range, main
from crypto_signal_bot.data.collector import make_mock_candles
from crypto_signal_bot.data.store import SQLiteStore


def test_cli_collect_and_rank_mock_json(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("DISPLAY_TIMEZONE", "Asia/Seoul")
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
    assert payload["display_timezone"] == "Asia/Seoul"
    assert payload["generated_at_display"].endswith("+09:00")
    assert len(payload["candidates"]) <= 2
    assert "score" in payload["candidates"][0]
    assert payload["candidates"][0]["raw_symbol"] == payload["candidates"][0]["symbol"]
    assert payload["candidates"][0]["base_asset"]
    assert payload["candidates"][0]["quote_asset"] == "USDT"
    assert "data_freshness_seconds" in payload["candidates"][0]
    assert payload["candidates"][0]["data_timestamp_display"].endswith("+09:00")
    assert payload["candidates"][0]["data_timestamp_display_timezone"] == "Asia/Seoul"
    assert "symbol_health_status" in payload["candidates"][0]
    assert "history_bars_available" in payload["candidates"][0]
    assert "benchmark_available" in payload["candidates"][0]


def test_cli_notify_skipped_when_disabled(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    main(["collect", "--exchange", "upbit", "--quote", "KRW", "--interval", "5m", "--limit", "80", "--mock"])
    assert main(["rank", "--exchange", "upbit", "--quote", "KRW", "--interval", "5m", "--top", "2", "--notify"]) == 0
    assert "notifications skipped because they are disabled" in capsys.readouterr().out


def test_cli_exit_guard_preflight_mock_outputs_research_event(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))

    assert main(
        [
            "exit-guard",
            "preflight",
            "--exchange",
            "binance_usdm_futures",
            "--symbol",
            "BTCUSDT",
            "--interval",
            "5m",
            "--action",
            "close_long",
            "--side",
            "SELL",
            "--quantity",
            "2",
            "--position-mode",
            "one_way",
            "--position-side",
            "BOTH",
            "--reduce-only",
            "--mock-orderbook",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["private_api_used"] is False
    assert payload["live_order_submitted"] is False
    assert payload["exchange_order_endpoint_used"] is False
    assert payload["orderbook_source"] == "mock"
    assert payload["max_orderbook_age_seconds"] == 30
    assert payload["max_slippage_pct"] == 1.0
    assert payload["slippage_assessment"]["status"] == "pass"
    assert payload["alert_event"]["event_type"] == "PROTECTIVE_EXIT_WATCH"
    assert "No order was placed" in payload["research_warning"]
    assert "buy now" not in json.dumps(payload).lower()


def test_cli_exit_guard_notify_skips_when_disabled(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))

    assert main(
        [
            "exit-guard",
            "preflight",
            "--exchange",
            "upbit_spot",
            "--symbol",
            "KRW-BTC",
            "--action",
            "sell_only",
            "--side",
            "ask",
            "--quantity",
            "1",
            "--mock-orderbook",
            "--notify",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["notification_note"].startswith("notifications skipped")
    assert payload["notification_results"][0]["status"] == "skipped"
    assert payload["intent"]["dry_run"] is True


def test_cli_exit_guard_uses_configured_preflight_thresholds(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("EXIT_GUARD_MAX_ORDERBOOK_AGE_SECONDS", "45")
    monkeypatch.setenv("EXIT_GUARD_MAX_SLIPPAGE_PCT", "0.05")

    assert main(
        [
            "exit-guard",
            "preflight",
            "--exchange",
            "binance_usdm_futures",
            "--symbol",
            "BTCUSDT",
            "--action",
            "close_long",
            "--side",
            "SELL",
            "--quantity",
            "2",
            "--position-mode",
            "one_way",
            "--position-side",
            "BOTH",
            "--reduce-only",
            "--mock-orderbook",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["max_orderbook_age_seconds"] == 45
    assert payload["max_slippage_pct"] == 0.05
    assert payload["slippage_assessment"]["status"] == "blocked"
    assert "excessive_slippage" in payload["slippage_assessment"]["risk_flags"]


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


def test_cli_strategy_event_study_mock_json(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))

    assert main(
        [
            "strategy",
            "event-study",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--horizons",
            "1,3",
            "--format",
            "json",
            "--mock",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["strategy_event_study_only"] is True
    assert payload["closed_candle_signals_only"] is True
    assert payload["next_open_entry_enforced"] is True
    assert payload["notification_logic_excluded"] is True
    assert payload["horizons"] == [1, 3]
    assert "variant_summaries" in payload
    assert "buy now" not in json.dumps(payload).lower()


def test_cli_strategy_event_study_rejects_invalid_horizons(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))

    assert main(
        [
            "strategy",
            "event-study",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--horizons",
            "1,zero",
            "--mock",
        ]
    ) == 2

    assert "horizons must contain only positive integers" in capsys.readouterr().err


def test_backtest_date_range_filters_candles_by_utc_open_time() -> None:
    candles = [
        candle
        for candle in make_mock_candles("binance", "USDT", "5m", limit=20)
        if candle.symbol == "BTCUSDT"
    ]
    start = candles[5].open_time_utc
    end = candles[10].open_time_utc

    filtered = _filter_candles_by_date_range(
        {"BTCUSDT": candles},
        start.isoformat(),
        end.isoformat(),
    )

    assert [candle.open_time_utc for candle in filtered["BTCUSDT"]] == [
        candle.open_time_utc
        for candle in candles[5:10]
    ]


def test_backtest_date_only_to_bound_is_inclusive_for_that_utc_day() -> None:
    candles = [
        candle
        for candle in make_mock_candles("binance", "USDT", "5m", limit=3)
        if candle.symbol == "BTCUSDT"
    ]
    target_day = datetime(2026, 1, 1, tzinfo=UTC)
    shifted = [
        candle.__class__(
            **{
                **candle.__dict__,
                "open_time_utc": target_day + timedelta(minutes=index * 5),
                "close_time_utc": target_day + timedelta(minutes=(index + 1) * 5) - timedelta(milliseconds=1),
            }
        )
        for index, candle in enumerate(candles)
    ]

    filtered = _filter_candles_by_date_range({"BTCUSDT": shifted}, "2026-01-01", "2026-01-01")

    assert len(filtered["BTCUSDT"]) == 3


def test_cli_backtest_rejects_inverted_date_range(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))

    assert main(
        [
            "backtest",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--from",
            "2026-01-02",
            "--to",
            "2026-01-01",
            "--mock",
        ]
    ) == 2

    assert "--from must be earlier than --to" in capsys.readouterr().err


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
