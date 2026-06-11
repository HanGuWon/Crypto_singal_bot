from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.cli import _filter_candles_by_date_range, main
from crypto_signal_bot.data.collector import make_mock_candles
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.exchanges.base import ExchangeClientError
from crypto_signal_bot.exit_guard.alerts import make_protective_exit_dedupe_key
from crypto_signal_bot.notifications.base import NotificationResult


def _allow_exit_guard_symbols(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("EXIT_GUARD_SYMBOL_ALLOWLIST", "BTCUSDT,KRW-BTC")


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
    assert payload["candidates"][0]["canonical_asset_id"]
    assert payload["candidates"][0]["canonical_pair_id"].endswith("/USDT")
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


def test_cli_exchange_error_records_system_error_event(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    class FailingClient:
        def get_markets(self, _quote: str) -> list[object]:
            raise ExchangeClientError(
                "failed https://discord.com/api/webhooks/123/secret "
                "and https://api.telegram.org/bot123:ABC/sendMessage"
            )

    monkeypatch.setattr("crypto_signal_bot.cli._exchange_client", lambda _exchange, _settings: FailingClient())

    assert (
        main([
            "collect",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--limit",
            "10",
        ])
        == 1
    )

    stderr = capsys.readouterr().err
    assert "Exchange/API error" in stderr
    assert "SYSTEM_ERROR alert_event_id=" in stderr
    assert "123:ABC" not in stderr
    assert "secret" not in stderr

    events = SQLiteStore(db_path).list_alert_events(limit=5)
    assert len(events) == 1
    assert events[0].event_type == "SYSTEM_ERROR"
    assert events[0].severity == "CRITICAL"
    assert events[0].exchange == "binance"
    assert events[0].symbol == "USDT"
    assert "not_trading_signal" in events[0].risk_flags


def test_cli_unexpected_system_error_records_system_error_event(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    class FailingClient:
        def get_markets(self, _quote: str) -> list[object]:
            raise RuntimeError(
                "boom https://discord.com/api/webhooks/123/secret "
                "and https://api.telegram.org/bot123:ABC/sendMessage"
            )

    monkeypatch.setattr("crypto_signal_bot.cli._exchange_client", lambda _exchange, _settings: FailingClient())

    assert (
        main([
            "collect",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--limit",
            "10",
        ])
        == 1
    )

    stderr = capsys.readouterr().err
    assert "System error" in stderr
    assert "SYSTEM_ERROR alert_event_id=" in stderr
    assert "123:ABC" not in stderr
    assert "secret" not in stderr

    events = SQLiteStore(db_path).list_alert_events(limit=5)
    assert len(events) == 1
    assert events[0].event_type == "SYSTEM_ERROR"
    assert events[0].severity == "CRITICAL"
    assert events[0].exchange == "binance"
    assert events[0].symbol == "USDT"
    assert "not_trading_signal" in events[0].risk_flags


def test_cli_alert_test_records_audited_delivery_when_enabled(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-1")

    class FakeTelegramNotifier:
        channel = "telegram"

        def __init__(self, **_kwargs: object) -> None:
            pass

        def destination_key(self) -> str:
            return "chat-1:test-token"

        def send(self, _event: object) -> NotificationResult:
            return NotificationResult("telegram", "delivered", "chat-1", provider_response={"ok": True})

    monkeypatch.setattr("crypto_signal_bot.cli.TelegramNotifier", FakeTelegramNotifier)

    assert main(["alert-test", "--channel", "telegram"]) == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["notification_note"].startswith("alert-test dispatch attempted")
    assert payload["delivery_audit_count"] == len(payload["alert_event_ids"])
    assert payload["outbox_count"] == len(payload["alert_event_ids"])
    assert all(result["status"] == "delivered" for result in payload["delivery_results"])
    assert "test-token" not in output

    store = SQLiteStore(db_path)
    event = store.fetch_alert_event(payload["alert_event_id"])
    assert event is not None
    with store.connect() as conn:
        outbox_rows = conn.execute("SELECT status FROM notification_outbox").fetchall()
        delivery_rows = conn.execute("SELECT status, channel FROM notification_deliveries").fetchall()
    assert len(outbox_rows) == len(payload["alert_event_ids"])
    assert len(delivery_rows) == len(payload["alert_event_ids"])
    assert {row["status"] for row in outbox_rows} == {"delivered"}
    assert {row["status"] for row in delivery_rows} == {"delivered"}
    assert {row["channel"] for row in delivery_rows} == {"telegram"}


def test_cli_exit_guard_preflight_mock_outputs_research_event(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    _allow_exit_guard_symbols(monkeypatch)

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


def test_cli_exit_guard_signal_mock_outputs_and_saves_public_candle_event(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    assert main(
        [
            "exit-guard",
            "signal",
            "--exchange",
            "binance_usdm_futures",
            "--symbol",
            "BTCUSDT",
            "--interval",
            "5m",
            "--exposure-side",
            "long",
            "--confirmation-intervals",
            "15m",
            "--mock-candles",
            "--save-event",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["private_api_used"] is False
    assert payload["live_order_submitted"] is False
    assert payload["exchange_order_endpoint_used"] is False
    assert payload["candle_source"] == "mock"
    assert payload["candle_count"] >= 60
    assert payload["data_quality"]["status"] == "pass"
    assert payload["data_quality"]["gap_classification"] == "complete"
    assert payload["data_quality"]["gap_policy_reason"] is None
    assert payload["signal"]["is_closed_candle_signal"] is True
    assert payload["signal"]["state"] in {
        "WATCHING",
        "WARNING",
        "EXIT_CANDIDATE",
        "EXIT_CONFIRMED",
        "SEVERE_EXIT_CANDIDATE",
        "SAFETY_BLOCKED",
    }
    assert payload["confirmation_intervals"] == ["15m"]
    assert payload["confirmation_signals"][0]["interval"] == "15m"
    assert payload["alert_event"]["event_type"].startswith("PROTECTIVE_EXIT_")
    assert payload["saved_event"] is True
    assert payload["saved_signal"] is True
    assert payload["saved_signal_id"] == payload["signal"]["signal_id"]
    assert "No order was placed" in payload["research_warning"]
    assert "buy now" not in json.dumps(payload).lower()

    saved = SQLiteStore(db_path).fetch_alert_event(payload["saved_alert_event_id"])
    assert saved is not None
    assert saved.source_run_id == payload["signal"]["signal_id"]
    signal_row = SQLiteStore(db_path).fetch_protective_exit_signal(payload["saved_signal_id"])
    assert signal_row is not None
    assert signal_row["source_alert_event_id"] == payload["saved_alert_event_id"]

    assert main(["exit-guard", "signals", "list", "--limit", "5"]) == 0
    list_payload = json.loads(capsys.readouterr().out)
    assert list_payload["count"] == 1
    assert list_payload["signals"][0]["id"] == payload["saved_signal_id"]

    assert main(["exit-guard", "signals", "show", payload["saved_signal_id"]]) == 0
    show_payload = json.loads(capsys.readouterr().out)
    assert show_payload["signal"]["id"] == payload["saved_signal_id"]
    assert show_payload["signal"]["payload"]["combined_signal"]["signal_id"] == payload["saved_signal_id"]


def test_cli_exit_guard_signal_without_candles_safety_blocks(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))

    assert main(
        [
            "exit-guard",
            "signal",
            "--exchange",
            "binance_usdm_futures",
            "--symbol",
            "BTCUSDT",
            "--interval",
            "5m",
            "--exposure-side",
            "short",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["candle_source"] == "database"
    assert payload["candle_count"] == 0
    assert payload["data_quality"]["status"] == "fail"
    assert payload["data_quality"]["gap_classification"] == "unavailable"
    assert payload["data_quality"]["gap_policy_reason"] == "no candles supplied"
    assert payload["signal"]["state"] == "SAFETY_BLOCKED"
    assert payload["signal"]["data_quality_status"] == "fail"
    assert payload["alert_event"]["event_type"] == "PROTECTIVE_EXIT_BLOCKED"
    assert payload["saved_event"] is False
    assert payload["saved_signal"] is False


def test_cli_exit_guard_blocks_unallowlisted_symbol_before_manual_approval(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

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
            "--request-approval",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["symbol_allowlist"]["required"] is True
    assert payload["symbol_allowlist"]["status"] == "blocked"
    assert payload["slippage_assessment"]["status"] == "pass"
    assert payload["alert_event"]["event_type"] == "PROTECTIVE_EXIT_BLOCKED"
    assert "exit_guard_symbol_not_allowlisted" in payload["alert_event"]["risk_flags"]
    assert payload["manual_approval_request"] is None
    assert payload["manual_approval_note"] == "skipped because exit guard preflight is blocked"

    store = SQLiteStore(db_path)
    assert store.list_manual_approval_requests(status="pending") == []


def test_cli_exit_guard_notify_skips_when_disabled(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    _allow_exit_guard_symbols(monkeypatch)

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
    assert payload["saved_event"] is True
    assert payload["delivery_audit_recorded"] is True
    assert payload["delivery_audit_count"] == 1
    assert payload["intent"]["dry_run"] is True

    store = SQLiteStore(db_path)
    with store.connect() as conn:
        alert_rows = conn.execute("SELECT * FROM alert_events").fetchall()
        delivery_rows = conn.execute("SELECT * FROM notification_deliveries").fetchall()
    assert len(alert_rows) == 1
    assert len(delivery_rows) == 1
    assert delivery_rows[0]["alert_event_id"] == payload["saved_alert_event_id"]
    assert delivery_rows[0]["channel"] == "noop"
    assert delivery_rows[0]["destination"] == "disabled"
    assert delivery_rows[0]["status"] == "skipped"

    assert main(["exit-guard", "events", "show", payload["saved_alert_event_id"]]) == 0
    show_payload = json.loads(capsys.readouterr().out)
    assert show_payload["event"]["alert_event_id"] == payload["saved_alert_event_id"]
    assert len(show_payload["notification_deliveries"]) == 1
    assert show_payload["notification_deliveries"][0]["channel"] == "noop"
    assert show_payload["notification_deliveries"][0]["destination"] == "disabled"
    assert show_payload["notification_deliveries"][0]["status"] == "skipped"


def test_cli_exit_guard_notify_uses_discord_only_when_enabled(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    class FakeDiscordNotifier:
        channel = "discord"

        def __init__(
            self,
            *,
            webhook_url: str,
            username: str = "",
            thread_id: str = "",
            allow_mentions: bool = False,
        ) -> None:
            self.webhook_url = webhook_url
            self.username = username
            self.thread_id = thread_id
            self.allow_mentions = allow_mentions

        def destination_key(self) -> str:
            return self.webhook_url

        def send(self, event) -> NotificationResult:  # type: ignore[no-untyped-def]
            return NotificationResult(
                "discord",
                "delivered",
                "discord_webhook",
                provider_response={"ok": True, "event_type": event.event_type, "drivers": event.drivers},
            )

    class FailingTelegramNotifier:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            raise AssertionError("Exit guard must not instantiate TelegramNotifier.")

    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    _allow_exit_guard_symbols(monkeypatch)
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("DISCORD_WEBHOOK_ENABLED", "true")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/secret-token")
    monkeypatch.setenv("EXIT_GUARD_DISCORD_ALERTS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-1")
    monkeypatch.setattr("crypto_signal_bot.cli.DiscordWebhookNotifier", FakeDiscordNotifier)
    monkeypatch.setattr("crypto_signal_bot.cli.TelegramNotifier", FailingTelegramNotifier)

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
            "--notify",
            "--request-approval",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    approval_id = payload["manual_approval_request"]["id"]
    alert_event = payload["alert_event"]
    expected_dedupe_key = make_protective_exit_dedupe_key(
        exchange=alert_event["exchange"],
        symbol=alert_event["symbol"],
        interval=alert_event["interval"],
        event_type=alert_event["event_type"],
        score=alert_event["score"],
        drivers=alert_event["drivers"],
        risk_flags=alert_event["risk_flags"],
    )
    assert payload["notification_note"] == "dispatch_attempted_discord_only"
    assert payload["delivery_audit_count"] == 1
    assert payload["notification_results"][0]["channel"] == "discord"
    assert payload["notification_results"][0]["status"] == "delivered"
    assert alert_event["dedupe_key"] == expected_dedupe_key
    assert f"manual_approval_request:{approval_id}" in alert_event["drivers"]
    assert (
        f"manual_approval_request:{approval_id}"
        in payload["notification_results"][0]["provider_response"]["drivers"]
    )
    assert "telegram" not in json.dumps(payload["notification_results"]).lower()

    store = SQLiteStore(db_path)
    with store.connect() as conn:
        outbox_rows = conn.execute("SELECT * FROM notification_outbox").fetchall()
        delivery_rows = conn.execute("SELECT * FROM notification_deliveries").fetchall()
    assert len(outbox_rows) == 1
    assert outbox_rows[0]["channel"] == "discord"
    assert outbox_rows[0]["status"] == "delivered"
    assert "secret-token" not in outbox_rows[0]["destination_hash"]
    assert len(delivery_rows) == 1
    assert delivery_rows[0]["channel"] == "discord"
    assert delivery_rows[0]["status"] == "delivered"
    assert "secret-token" not in delivery_rows[0]["destination"]

    assert main(["exit-guard", "events", "show", payload["saved_alert_event_id"]]) == 0
    show_payload = json.loads(capsys.readouterr().out)
    assert f"manual_approval_request:{approval_id}" in show_payload["event"]["drivers"]
    assert show_payload["event"]["dedupe_key"] == expected_dedupe_key
    assert show_payload["notification_deliveries"][0]["channel"] == "discord"
    assert show_payload["notification_deliveries"][0]["status"] == "delivered"


def test_cli_exit_guard_uses_configured_preflight_thresholds(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    _allow_exit_guard_symbols(monkeypatch)
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


def test_cli_exit_guard_can_save_preflight_event_to_audit_table(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    _allow_exit_guard_symbols(monkeypatch)

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
            "--save-event",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    saved = SQLiteStore(db_path).fetch_alert_event(payload["saved_alert_event_id"])
    assert payload["saved_event"] is True
    assert saved is not None
    assert saved.event_type == "PROTECTIVE_EXIT_WATCH"
    assert saved.source_run_id == payload["alert_event"]["source_run_id"]

    assert main(["exit-guard", "events", "list", "--limit", "5"]) == 0
    list_payload = json.loads(capsys.readouterr().out)
    assert list_payload["count"] == 1
    assert list_payload["events"][0]["alert_event_id"] == payload["saved_alert_event_id"]
    assert list_payload["events"][0]["event_type"] == "PROTECTIVE_EXIT_WATCH"

    assert main(["exit-guard", "events", "show", payload["saved_alert_event_id"]]) == 0
    show_payload = json.loads(capsys.readouterr().out)
    assert show_payload["event"]["alert_event_id"] == payload["saved_alert_event_id"]
    assert show_payload["event"]["event_type"].startswith("PROTECTIVE_EXIT_")
    assert show_payload["notification_deliveries"] == []
    assert "No order was placed" in show_payload["research_warning"]


def test_cli_exit_guard_manual_approval_request_is_audit_only(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    _allow_exit_guard_symbols(monkeypatch)

    assert main(
        [
            "exit-guard",
            "preflight",
            "--exchange",
            "binance_usdm_futures",
            "--symbol",
            "BTCUSDT",
            "--action",
            "close_short",
            "--side",
            "BUY",
            "--quantity",
            "2",
            "--position-mode",
            "one_way",
            "--position-side",
            "BOTH",
            "--reduce-only",
            "--mock-orderbook",
            "--request-approval",
            "--approval-ttl-minutes",
            "15",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    request_id = payload["manual_approval_request"]["id"]
    binding_hash = payload["manual_approval_request"]["binding_hash"]
    assert payload["saved_event"] is True
    assert payload["manual_approval_request"]["status"] == "pending"
    assert payload["manual_approval_request"]["source_alert_event_id"] == payload["saved_alert_event_id"]
    assert isinstance(binding_hash, str)
    assert len(binding_hash) == 64
    assert payload["live_order_submitted"] is False

    assert main(["exit-guard", "approvals", "list", "--status", "pending"]) == 0
    list_payload = json.loads(capsys.readouterr().out)
    assert list_payload["count"] == 1
    assert list_payload["approval_requests"][0]["id"] == request_id
    assert list_payload["approval_requests"][0]["binding_hash"] == binding_hash

    assert main(["exit-guard", "approvals", "show", request_id]) == 0
    show_payload = json.loads(capsys.readouterr().out)
    request = show_payload["approval_request"]
    assert request["status"] == "pending"
    assert request["source_alert_event_id"] == payload["saved_alert_event_id"]
    assert request["binding_hash"] == binding_hash
    assert request["request_payload"]["binding_hash"] == binding_hash
    assert request["request_payload"]["intent"]["action"] == "close_short"
    assert "No order was placed" in show_payload["research_warning"]

    assert main(["exit-guard", "approvals", "approve", request_id]) == 1
    assert "require --confirm" in capsys.readouterr().err

    assert main(["exit-guard", "approvals", "approve", request_id, "--confirm", "--note", "reviewed"]) == 0
    approved_payload = json.loads(capsys.readouterr().out)
    assert approved_payload["approval_request"]["status"] == "approved"
    assert approved_payload["approval_request"]["decision_note"] == "reviewed"
    assert approved_payload["approval_request"]["binding_hash"] == binding_hash
    assert approved_payload["live_execution_allowed"] is False
    assert "No order was placed" in approved_payload["research_warning"]

    assert main(["exit-guard", "approvals", "reject", request_id, "--confirm"]) == 1
    assert "no longer pending" in capsys.readouterr().err


def test_cli_exit_guard_manual_approval_rejects_tampered_binding(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    _allow_exit_guard_symbols(monkeypatch)

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
            "--request-approval",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    request_id = payload["manual_approval_request"]["id"]
    store = SQLiteStore(db_path)
    with store.connect() as conn:
        conn.execute(
            """
            UPDATE manual_approval_requests
            SET quantity=3.0
            WHERE id=?
            """,
            (request_id,),
        )

    assert main(["exit-guard", "approvals", "approve", request_id, "--confirm"]) == 1
    assert "binding integrity check failed" in capsys.readouterr().err
    row = store.fetch_manual_approval_request(request_id)
    assert row is not None
    assert row["status"] == "pending"
    assert row["decided_at_utc"] is None


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
    assert payload["timeframe_alignment"]["status"] == "pass"
    assert payload["timeframe_alignment"]["base_interval"] == "5m"
    assert payload["timeframe_alignment"]["timeframes"] == ["5m", "15m"]
    assert payload["research_warning"].startswith("Research watchlist only")
    assert len(payload["candidates"]) <= 3
    assert payload["candidates"][0]["entry_strategy"] == "three_tick"
    assert payload["candidates"][0]["entry_timing_status"] != "not_evaluated"
    assert "buy now" not in json.dumps(payload).lower()


def test_cli_strategy_scan_rejects_unsupported_timeframe(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))

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
            "5m,7m",
            "--format",
            "json",
            "--mock",
        ]
    ) == 2

    assert "unsupported: 7m" in capsys.readouterr().err


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
            "--fee-bps",
            "12",
            "--spread-bps",
            "6",
            "--slippage-bps",
            "4",
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
    assert payload["cost_model"]["fee_bps"] == 12.0
    assert payload["cost_model"]["spread_bps"] == 6.0
    assert payload["cost_model"]["slippage_bps"] == 4.0
    assert "cost_sensitivity" in payload
    assert payload["benchmark_set_diagnostics"]["available_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert payload["baseline_diagnostics"]["windows_aligned_point_in_time"] is True
    assert payload["stress_diagnostics"]["strategy_event_stress_only"] is True
    assert "variant_summaries" in payload
    assert "buy now" not in json.dumps(payload).lower()


def test_cli_strategy_event_study_rejects_negative_costs(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
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
            "--fee-bps",
            "-1",
            "--mock",
        ]
    ) == 2

    assert "--fee-bps must be non-negative" in capsys.readouterr().err


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


def test_cli_backtest_mock_includes_btc_eth_benchmark_set(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
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
            "--mock",
        ]
    ) == 0

    output = capsys.readouterr().out
    payload = json.loads(output[: output.rfind("}") + 1])
    benchmark_set = payload["benchmark_set_diagnostics"]
    assert benchmark_set["requested_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert benchmark_set["available_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert benchmark_set["benchmark_return_by_symbol"]["BTCUSDT"]["trades"] > 0
    assert benchmark_set["benchmark_return_by_symbol"]["ETHUSDT"]["trades"] > 0


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
