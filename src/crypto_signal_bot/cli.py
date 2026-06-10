from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from crypto_signal_bot.alerts.channel_state import SQLiteNotificationChannelStateStore
from crypto_signal_bot.alerts.delivery_log import delivery_record, suppressed_delivery_record
from crypto_signal_bot.alerts.dispatcher import NotificationDispatcher
from crypto_signal_bot.alerts.formatter import format_telegram_event
from crypto_signal_bot.alerts.policy import AlertPolicy, AlertPolicyConfig
from crypto_signal_bot.alerts.rate_limit import SQLiteNotificationRateLimiter
from crypto_signal_bot.alerts.state import SQLiteAlertStateStore
from crypto_signal_bot.config import ConfigError, Settings, load_settings
from crypto_signal_bot.data.collector import make_mock_candles
from crypto_signal_bot.data.models import (
    Candle,
    DataQualityReport,
    OrderBook,
    PriceLevel,
    SymbolHealth,
    Ticker,
    utc_now,
)
from crypto_signal_bot.data.quality import assess_candles
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.data.symbol_health import assess_symbol_health
from crypto_signal_bot.exchanges.base import PublicMarketDataClient
from crypto_signal_bot.exchanges.binance import BinancePublicClient
from crypto_signal_bot.exchanges.upbit import UpbitPublicClient
from crypto_signal_bot.features.feature_builder import FeatureSnapshot, build_feature_snapshot
from crypto_signal_bot.logging_config import configure_logging
from crypto_signal_bot.notifications.base import Notifier
from crypto_signal_bot.notifications.destinations import destination_hash, notifier_destination
from crypto_signal_bot.notifications.discord_webhook import DiscordWebhookNotifier
from crypto_signal_bot.notifications.noop import NoopNotifier
from crypto_signal_bot.notifications.telegram import TelegramNotifier
from crypto_signal_bot.research import config_hash
from crypto_signal_bot.signals.ranking import rank_candidates
from crypto_signal_bot.signals.schemas import SignalCandidate
from crypto_signal_bot.signals.scoring import ScoringEngine

Console: Any = None
Table: Any = None
try:  # pragma: no cover - rich availability depends on environment
    from rich.console import Console as RichConsole
    from rich.table import Table as RichTable

    Console = RichConsole
    Table = RichTable
except ImportError:  # pragma: no cover
    pass


@dataclass(frozen=True)
class ScoredResearchCandidate:
    candidate: SignalCandidate
    snapshot: FeatureSnapshot
    score_explanation: dict[str, object]
    data_window_start_utc: str
    data_window_end_utc: str


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    configure_logging(settings.log_level)
    try:
        if args.command == "collect":
            return _collect(args, settings)
        if args.command == "rank":
            return _rank(args, settings)
        if args.command == "backtest":
            return _backtest(args, settings)
        if args.command == "alert-test":
            return _alert_test(args, settings)
        if args.command == "db":
            return _db(args, settings)
        if args.command == "notifications":
            return _notifications(args, settings)
        if args.command == "runs":
            return _runs(args, settings)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crypto-signal-bot")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="Collect public market candles.")
    collect.add_argument("--exchange", choices=["upbit", "binance"], required=True)
    collect.add_argument("--quote", default=None)
    collect.add_argument("--interval", default="5m")
    collect.add_argument("--limit", type=int, default=200)
    collect.add_argument("--max-symbols", type=int, default=None)
    collect.add_argument("--skip-tickers", action="store_true", help="Skip public 24h ticker snapshots.")
    collect.add_argument("--with-orderbook", action="store_true", help="Fetch shallow public orderbook snapshots.")
    collect.add_argument("--max-orderbook-symbols", type=int, default=None)
    collect.add_argument("--mock", action="store_true", help="Use deterministic local fixture data.")

    rank = sub.add_parser("rank", help="Rank stored public-market candidates.")
    rank.add_argument("--exchange", choices=["upbit", "binance"], required=True)
    rank.add_argument("--quote", default=None)
    rank.add_argument("--interval", default="5m")
    rank.add_argument("--top", type=int, default=20)
    rank.add_argument("--format", choices=["table", "json"], default="table")
    rank.add_argument("--notify", action="store_true")
    rank.add_argument("--mock", action="store_true", help="Seed deterministic fixture data before ranking.")
    rank.add_argument("--save-run", action="store_true", help="Persist reproducible research-run artifacts.")

    backtest = sub.add_parser("backtest", help="Run a minimal leakage-safe event-study smoke test.")
    backtest.add_argument("--exchange", choices=["upbit", "binance"], required=True)
    backtest.add_argument("--quote", default=None)
    backtest.add_argument("--interval", default="15m")
    backtest.add_argument("--from", dest="from_date", default=None)
    backtest.add_argument("--to", dest="to_date", default=None)
    backtest.add_argument("--mock", action="store_true")

    alert_test = sub.add_parser("alert-test", help="Format or send a research alert test.")
    alert_test.add_argument("--channel", choices=["noop", "telegram", "discord"], default="noop")

    db = sub.add_parser("db", help="Inspect or migrate the local research database.")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("migrate", help="Apply versioned SQLite schema migrations.")
    db_sub.add_parser("doctor", help="Validate required SQLite tables, columns, and indexes.")

    notifications = sub.add_parser("notifications", help="Inspect notification state safely.")
    notification_sub = notifications.add_subparsers(dest="notifications_command", required=True)
    notification_sub.add_parser("status", help="Summarize notification outbox and channel state.")

    channel_state = notification_sub.add_parser("channel-state", help="Inspect or reset channel quarantine.")
    channel_state_sub = channel_state.add_subparsers(dest="channel_state_command", required=True)
    channel_state_sub.add_parser("list", help="List channel state using destination hashes only.")
    channel_reset = channel_state_sub.add_parser("reset", help="Reset a quarantined destination hash.")
    channel_reset.add_argument("--channel", choices=["telegram", "discord"], required=True)
    channel_reset.add_argument("--destination-hash", required=True)
    channel_reset.add_argument("--confirm", action="store_true")

    outbox = notification_sub.add_parser("outbox", help="Inspect or drain notification outbox rows.")
    outbox_sub = outbox.add_subparsers(dest="outbox_command", required=True)
    outbox_list = outbox_sub.add_parser("list", help="List outbox rows.")
    outbox_list.add_argument(
        "--status",
        choices=["pending", "claimed", "delivered", "failed_retryable", "failed_terminal", "suppressed"],
        default=None,
    )
    outbox_drain = outbox_sub.add_parser("drain", help="Drain pending/retryable outbox rows.")
    outbox_drain.add_argument("--max", dest="max_rows", type=int, default=10)
    outbox_drain.add_argument("--dry-run", action="store_true")

    runs = sub.add_parser("runs", help="Inspect saved research runs.")
    runs_sub = runs.add_subparsers(dest="runs_command", required=True)
    runs_list = runs_sub.add_parser("list", help="List saved research runs.")
    runs_list.add_argument("--limit", type=int, default=20)
    runs_show = runs_sub.add_parser("show", help="Show one saved research run.")
    runs_show.add_argument("run_id")
    runs_export = runs_sub.add_parser("export", help="Export one saved research run.")
    runs_export.add_argument("run_id")
    runs_export.add_argument("--format", choices=["json"], default="json")
    return parser


def _collect(args: argparse.Namespace, settings: Settings) -> int:
    quote = args.quote or ("KRW" if args.exchange == "upbit" else "USDT")
    store = SQLiteStore(settings.database_path)
    if args.mock:
        mocked = make_mock_candles(args.exchange, quote, args.interval, limit=args.limit)
        count = store.upsert_candles(mocked)
        symbols = sorted({candle.symbol for candle in mocked})
        ticker_count = 0 if args.skip_tickers else store.upsert_tickers(_mock_tickers(mocked))
        orderbook_count = 0
        if args.with_orderbook:
            max_orderbooks = args.max_orderbook_symbols or settings.max_orderbook_symbols_per_collect
            orderbook_count = store.upsert_orderbooks(_mock_orderbooks(mocked, symbols[:max_orderbooks]))
        for symbol in sorted({candle.symbol for candle in mocked}):
            candles = [candle for candle in mocked if candle.symbol == symbol]
            quality = assess_candles(
                candles,
                args.interval,
                max_staleness_seconds=settings.max_staleness_seconds,
            )
            _assess_and_store_symbol_health(
                store,
                args.exchange,
                symbol,
                args.interval,
                candles,
                quality,
                settings,
            )
        print(
            f"Stored {count} mocked public candles, {ticker_count} tickers, "
            f"and {orderbook_count} orderbooks for {args.exchange} {quote}."
        )
        print("Research-only data collection completed. No order was placed.")
        return 0

    client = _exchange_client(args.exchange, settings)
    markets = client.get_markets(quote)
    max_symbols = args.max_symbols or settings.max_symbols_per_collect
    selected = markets[:max_symbols]
    selected_trading = [market for market in selected if market.status == "TRADING"]
    stored = 0
    for market in selected:
        if market.status != "TRADING":
            _assess_and_store_symbol_health(
                store,
                args.exchange,
                market.raw_symbol,
                args.interval,
                [],
                assess_candles([], args.interval),
                settings,
                market_status=market.status,
            )
            continue
        candles = client.get_candles(market.raw_symbol, args.interval, args.limit)
        stored += store.upsert_candles(candles)
        quality = assess_candles(
            candles,
            args.interval,
            max_staleness_seconds=settings.max_staleness_seconds,
        )
        _assess_and_store_symbol_health(
            store,
            args.exchange,
            market.raw_symbol,
            args.interval,
            candles,
            quality,
            settings,
            market_status=market.status,
        )
    ticker_count = 0
    if not args.skip_tickers and selected_trading:
        ticker_count = store.upsert_tickers(_fetch_tickers(client, args.exchange, selected_trading))
    orderbook_count = 0
    if args.with_orderbook and selected_trading:
        max_orderbooks = args.max_orderbook_symbols or settings.max_orderbook_symbols_per_collect
        orderbook_count = store.upsert_orderbooks(
            _fetch_orderbooks(
                client,
                args.exchange,
                selected_trading[:max_orderbooks],
                depth_limit=settings.orderbook_depth_limit,
            )
        )
    print(
        f"Stored {stored} public candles, {ticker_count} tickers, and {orderbook_count} orderbooks "
        f"for {len(selected)} {args.exchange} {quote} symbols. "
        "No private API was used."
    )
    return 0


def _fetch_tickers(client: Any, exchange: str, markets: list[Any]) -> list[Ticker]:
    if exchange == "upbit":
        return list(client.get_ticker([market.raw_symbol for market in markets]))
    tickers: list[Ticker] = []
    for market in markets:
        tickers.extend(client.get_ticker(market.raw_symbol))
    return tickers


def _fetch_orderbooks(
    client: Any,
    exchange: str,
    markets: list[Any],
    *,
    depth_limit: int,
) -> list[OrderBook]:
    symbols = [market.raw_symbol for market in markets]
    if exchange == "upbit":
        return list(client.get_orderbook(symbols))
    return [client.get_orderbook(symbol, limit=depth_limit) for symbol in symbols]


def _mock_tickers(candles: list[Candle]) -> list[Ticker]:
    tickers: list[Ticker] = []
    for symbol in sorted({candle.symbol for candle in candles}):
        symbol_candles = [candle for candle in candles if candle.symbol == symbol]
        latest = symbol_candles[-1]
        quote_24h = sum(candle.quote_volume or 0.0 for candle in symbol_candles[-288:])
        base_24h = sum(candle.base_volume or 0.0 for candle in symbol_candles[-288:])
        first = symbol_candles[-288].close if len(symbol_candles) >= 288 else symbol_candles[0].close
        change_pct = 100 * (latest.close / first - 1) if first > 0 else 0.0
        tickers.append(
            Ticker(
                exchange=latest.exchange,
                symbol=symbol,
                price=latest.close,
                quote_volume_24h=quote_24h,
                base_volume_24h=base_24h,
                price_change_pct_24h=change_pct,
                event_time_utc=latest.close_time_utc,
            )
        )
    return tickers


def _mock_orderbooks(candles: list[Candle], symbols: list[str]) -> list[OrderBook]:
    orderbooks: list[OrderBook] = []
    for symbol in symbols:
        symbol_candles = [candle for candle in candles if candle.symbol == symbol]
        if not symbol_candles:
            continue
        latest = symbol_candles[-1]
        mid = latest.close
        spread = mid * 0.001
        orderbooks.append(
            OrderBook(
                exchange=latest.exchange,
                symbol=symbol,
                event_time_utc=utc_now(),
                bids=[PriceLevel(mid - spread / 2, 10.0)],
                asks=[PriceLevel(mid + spread / 2, 10.0)],
            )
        )
    return orderbooks


def _rank(args: argparse.Namespace, settings: Settings) -> int:
    quote = args.quote or ("KRW" if args.exchange == "upbit" else "USDT")
    store = SQLiteStore(settings.database_path)
    if args.mock:
        store.upsert_candles(make_mock_candles(args.exchange, quote, args.interval, limit=160))
    scored = _score_research_from_store(store, args.exchange, quote, args.interval, args.top, settings)
    result = rank_candidates([item.candidate for item in scored], top=args.top)
    if args.save_run:
        _save_research_run(
            store,
            result_candidates=result.candidates,
            scored_candidates=scored,
            settings=settings,
            exchange=args.exchange,
            quote=quote,
            interval=args.interval,
            mock_mode=bool(args.mock),
            generated_at_utc=result.generated_at_utc,
            research_warning=result.research_warning,
            run_id=result.source_run_id,
        )
    if args.format == "json":
        payload: dict[str, object] = {
            "source_run_id": result.source_run_id,
            "generated_at_utc": result.generated_at_utc,
            "research_warning": result.research_warning,
            "candidates": [candidate.to_dict() for candidate in result.candidates],
        }
        if args.save_run:
            payload["saved_run_id"] = result.source_run_id
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_table(result.candidates)
        if args.save_run:
            print(f"Saved research run {result.source_run_id}.")

    if args.notify:
        _maybe_notify(result.candidates, settings)
    return 0


def _backtest(args: argparse.Namespace, settings: Settings) -> int:
    from crypto_signal_bot.backtest.engine import diagnostic_event_study

    quote = args.quote or ("KRW" if args.exchange == "upbit" else "USDT")
    store = SQLiteStore(settings.database_path)
    mocked_candles = None
    if args.mock:
        mocked_candles = make_mock_candles(args.exchange, quote, args.interval, limit=120)
        store.upsert_candles(mocked_candles)
    symbols = (
        sorted({candle.symbol for candle in mocked_candles})
        if mocked_candles is not None
        else store.list_symbols(args.exchange, quote, args.interval)
    )
    if not symbols:
        print("No stored candles found. Run collect first or use --mock.")
        return 1
    candles_by_symbol = {
        symbol: (
            [candle for candle in mocked_candles if candle.symbol == symbol]
            if mocked_candles is not None
            else store.fetch_candles(args.exchange, symbol, args.interval)
        )
        for symbol in symbols
    }
    signal_indices_by_symbol = {
        symbol: list(range(50, max(50, len(candles) - 5), 20))
        for symbol, candles in candles_by_symbol.items()
    }
    benchmark_symbol = f"{quote}-BTC" if args.exchange == "upbit" else f"BTC{quote}"
    metrics = diagnostic_event_study(
        candles_by_symbol,
        signal_indices_by_symbol,
        benchmark_symbol=benchmark_symbol,
        symbol_conditions={
            symbol: _backtest_symbol_condition(
                store,
                args.exchange,
                symbol,
                args.interval,
                candles,
                settings,
            )
            for symbol, candles in candles_by_symbol.items()
        },
    )
    print(json.dumps(metrics, indent=2))
    print(
        "Backtest diagnostic event-study only; it is not a portfolio simulator or financial advice. "
        "No order was placed."
    )
    return 0


def _alert_test(args: argparse.Namespace, settings: Settings) -> int:
    candidate = _sample_candidate()
    policy = AlertPolicy(AlertPolicyConfig(score_threshold=80, top_n=10))
    events = policy.evaluate([candidate], previous_scores={candidate.symbol: 50})
    if not events:
        print("No alert event generated by sample policy.")
        return 1
    event = events[0]
    if args.channel == "noop":
        print(format_telegram_event(event))
        return 0
    if not settings.notifications_enabled:
        print("Alert formatted; notifications skipped because NOTIFICATIONS_ENABLED=false.")
        print(format_telegram_event(event))
        return 0
    dispatcher = NotificationDispatcher(True, _configured_notifiers(settings, channel=args.channel))
    results = dispatcher.dispatch(events)
    print(json.dumps([result.to_safe_dict() for result in results], indent=2))
    return 0


def _backtest_symbol_condition(
    store: SQLiteStore,
    exchange: str,
    symbol: str,
    interval: str,
    candles: list[Candle],
    settings: Settings,
) -> dict[str, object]:
    quality = assess_candles(
        candles,
        interval,
        max_staleness_seconds=settings.max_staleness_seconds,
    )
    health = assess_symbol_health(
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        candles=candles,
        quality=quality,
        previous=store.get_symbol_health(exchange, symbol, interval),
        min_history_bars=settings.min_history_bars,
        quarantine_minutes=settings.symbol_quarantine_minutes,
    )
    risk_flags: list[str] = []
    if quality.status == "fail":
        risk_flags.append("failed_data_quality")
    risk_flags.extend(warning for warning in quality.warnings if warning in {"stale_data", "incomplete_current_candle"})
    latest_quote_volume = candles[-1].quote_volume if candles else None
    min_quote_volume = (
        settings.min_quote_volume_upbit_krw
        if exchange == "upbit"
        else settings.min_quote_volume_binance_usdt
    )
    if latest_quote_volume is not None and latest_quote_volume < min_quote_volume:
        risk_flags.append("low_liquidity")
    return {
        "data_quality_status": quality.status,
        "risk_flags": _unique_strings(risk_flags),
        "symbol_health_status": health.status,
        "quarantine_reason": health.quarantine_reason,
        "confidence": "low" if health.status == "quarantined" or risk_flags else "medium",
    }


def _db(args: argparse.Namespace, settings: Settings) -> int:
    store = SQLiteStore(settings.database_path)
    if args.db_command == "migrate":
        applied = store.run_migrations()
        store.validate_schema()
        print(
            json.dumps(
                {
                    "database_path": str(settings.database_path),
                    "applied_migrations": applied,
                    "schema_valid": True,
                    "research_warning": "Database migration only. No order was placed.",
                },
                indent=2,
            )
        )
        return 0
    if args.db_command == "doctor":
        status = store.schema_status()
        print(json.dumps(status, indent=2))
        return 0 if bool(status["valid"]) else 1
    raise ConfigError(f"Unknown db command: {args.db_command}")


def _notifications(args: argparse.Namespace, settings: Settings) -> int:
    store = SQLiteStore(settings.database_path)
    if args.notifications_command == "status":
        _print_json(
            {
                "database_path": str(settings.database_path),
                "notifications_enabled": settings.notifications_enabled,
                "telegram_enabled": settings.telegram_enabled,
                "discord_webhook_enabled": settings.discord_webhook_enabled,
                **store.notification_status_summary(),
            }
        )
        return 0
    if args.notifications_command == "channel-state":
        return _notifications_channel_state(args, store)
    if args.notifications_command == "outbox":
        return _notifications_outbox(args, settings, store)
    raise ConfigError(f"Unknown notifications command: {args.notifications_command}")


def _notifications_channel_state(args: argparse.Namespace, store: SQLiteStore) -> int:
    if args.channel_state_command == "list":
        _print_json(
            {
                "channel_state": [
                    _channel_state_row_to_dict(row)
                    for row in store.list_notification_channel_states()
                ],
                "destination_policy": "Destinations are shown as hashes only.",
            }
        )
        return 0
    if args.channel_state_command == "reset":
        if not args.confirm:
            print("Channel-state reset requires --confirm.", file=sys.stderr)
            return 2
        deleted = store.reset_notification_channel_state(args.channel, args.destination_hash)
        _print_json(
            {
                "channel": args.channel,
                "destination_hash": args.destination_hash,
                "reset_rows": deleted,
                "destination_policy": "Destination hash only. No token or webhook URL was printed.",
            }
        )
        return 0
    raise ConfigError(f"Unknown channel-state command: {args.channel_state_command}")


def _notifications_outbox(args: argparse.Namespace, settings: Settings, store: SQLiteStore) -> int:
    if args.outbox_command == "list":
        _print_json(
            {
                "outbox": [
                    _outbox_row_to_dict(row)
                    for row in store.list_notification_outbox(status=args.status)
                ],
                "destination_policy": "Destinations are shown as hashes only.",
            }
        )
        return 0
    if args.outbox_command == "drain":
        return _notifications_outbox_drain(args, settings, store)
    raise ConfigError(f"Unknown outbox command: {args.outbox_command}")


def _notifications_outbox_drain(args: argparse.Namespace, settings: Settings, store: SQLiteStore) -> int:
    rows = _drainable_outbox_rows(store, limit=args.max_rows)
    if args.dry_run:
        _print_json(
            {
                "dry_run": True,
                "would_drain": [_outbox_row_to_dict(row) for row in rows],
                "terminal_rows_excluded": True,
                "research_warning": "Dry run only. No notification was sent.",
            }
        )
        return 0
    if not settings.notifications_enabled:
        _print_json(
            {
                "drained": [],
                "skipped": [_outbox_row_to_dict(row) for row in rows],
                "error": "Notifications are disabled.",
            }
        )
        return 1
    notifiers = _configured_notifiers(settings)
    delivered: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for row in rows:
        notifier = _matching_notifier(notifiers, str(row["channel"]), str(row["destination_hash"]))
        event = store.fetch_alert_event(str(row["alert_event_id"]))
        if notifier is None or event is None:
            skipped.append(_outbox_row_to_dict(row))
            continue
        dispatcher = NotificationDispatcher(
            True,
            [notifier],
            channel_state_store=SQLiteNotificationChannelStateStore(store),
            outbox_store=store,
        )
        for pair_event, result in dispatcher.dispatch_with_events([event]):
            store.insert_notification_delivery(delivery_record(result, pair_event.alert_event_id))
            delivered.append(
                {
                    "outbox_id": row["id"],
                    "alert_event_id": pair_event.alert_event_id,
                    "channel": result.channel,
                    "status": result.status,
                    "error_code": result.error_code,
                }
            )
    _print_json({"drained": delivered, "skipped": skipped})
    return 0


def _score_from_store(
    store: SQLiteStore,
    exchange: str,
    quote: str,
    interval: str,
    top: int,
    settings: Settings,
) -> list[SignalCandidate]:
    scored = _score_research_from_store(store, exchange, quote, interval, top, settings)
    return rank_candidates([item.candidate for item in scored], top=top).candidates


def _score_research_from_store(
    store: SQLiteStore,
    exchange: str,
    quote: str,
    interval: str,
    top: int,
    settings: Settings,
) -> list[ScoredResearchCandidate]:
    symbols = store.list_symbols(exchange, quote, interval)
    if not symbols:
        print("No stored candles found. Run collect first or use --mock.")
        return []
    engine = ScoringEngine(
        min_quote_volume=(
            settings.min_quote_volume_upbit_krw
            if exchange == "upbit"
            else settings.min_quote_volume_binance_usdt
        ),
        max_spread_bps=settings.max_spread_bps,
    )
    run_id = str(uuid4())
    benchmark_symbol = f"{quote}-BTC" if exchange == "upbit" else f"BTC{quote}"
    benchmark_candles = store.fetch_candles(exchange, benchmark_symbol, interval, limit=240)
    benchmark_available = _benchmark_available(
        benchmark_candles,
        interval,
        settings=settings,
    )
    scored_candidates: list[ScoredResearchCandidate] = []
    for symbol in symbols:
        candles = store.fetch_candles(exchange, symbol, interval, limit=240)
        quality = assess_candles(
            candles,
            interval,
            max_staleness_seconds=settings.max_staleness_seconds,
        )
        health = _assess_and_store_symbol_health(
            store,
            exchange,
            symbol,
            interval,
            candles,
            quality,
            settings,
            benchmark_available=benchmark_available,
        )
        if len(candles) < 25:
            continue
        orderbook = store.fetch_latest_orderbook(exchange, symbol)
        snapshot = build_feature_snapshot(
            candles,
            quality=quality,
            benchmark_candles=benchmark_candles if benchmark_candles else None,
            orderbook=orderbook,
        )
        candidate = engine.score(snapshot, source_run_id=run_id)
        candidate = _candidate_with_symbol_health(
            candidate,
            health,
            orderbook_available=orderbook is not None,
        )
        scored_candidates.append(
            ScoredResearchCandidate(
                candidate=candidate,
                snapshot=snapshot,
                score_explanation=engine.explain(snapshot, candidate),
                data_window_start_utc=candles[0].open_time_utc.isoformat(),
                data_window_end_utc=candles[-1].close_time_utc.isoformat(),
            )
        )
    return scored_candidates


def _assess_and_store_symbol_health(
    store: SQLiteStore,
    exchange: str,
    symbol: str,
    interval: str,
    candles: list[Candle],
    quality: DataQualityReport,
    settings: Settings,
    *,
    market_status: str = "TRADING",
    benchmark_available: bool = True,
) -> SymbolHealth:
    health = assess_symbol_health(
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        candles=candles,
        quality=quality,
        market_status=market_status,
        benchmark_available=benchmark_available,
        previous=store.get_symbol_health(exchange, symbol, interval),
        min_history_bars=settings.min_history_bars,
        quarantine_minutes=settings.symbol_quarantine_minutes,
    )
    store.upsert_symbol_health(health)
    return health


def _benchmark_available(
    benchmark_candles: list[Candle],
    interval: str,
    *,
    settings: Settings,
) -> bool:
    if len([candle for candle in benchmark_candles if candle.is_closed]) < settings.min_history_bars:
        return False
    quality = assess_candles(
        benchmark_candles,
        interval,
        max_staleness_seconds=settings.max_staleness_seconds,
    )
    return quality.status == "pass"


def _candidate_with_symbol_health(
    candidate: SignalCandidate,
    health: SymbolHealth,
    *,
    orderbook_available: bool,
) -> SignalCandidate:
    data = candidate.to_dict()
    risk_flags = _unique_strings(candidate.risk_flags)
    confidence = candidate.confidence
    if not orderbook_available and "wide_spread" not in risk_flags:
        # Spread is unavailable when no orderbook snapshot was collected; keep this visible.
        if "orderbook_unavailable" not in risk_flags:
            risk_flags.append("orderbook_unavailable")
            if confidence == "high":
                confidence = "medium"
    if health.status == "quarantined":
        risk_flags = _unique_strings([
            *risk_flags,
            "symbol_quarantined",
            _risk_flag_for_quarantine_reason(health.quarantine_reason),
        ])
        confidence = "low"
    if not health.benchmark_available:
        risk_flags = _unique_strings([*risk_flags, "benchmark_unavailable"])
        confidence = "low"
    data.update(
        {
            "confidence": confidence,
            "risk_flags": risk_flags,
            "symbol_health_status": health.status,
            "quarantine_reason": health.quarantine_reason,
            "history_bars_available": health.history_bars_available,
            "benchmark_available": health.benchmark_available,
        }
    )
    return SignalCandidate(**data)


def _risk_flag_for_quarantine_reason(reason: str | None) -> str:
    if reason is None:
        return "symbol_quarantined"
    if reason == "insufficient_history":
        return "insufficient_history"
    if reason.startswith("market_status_"):
        return "inactive_market"
    return f"quarantine_{reason}"


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _save_research_run(
    store: SQLiteStore,
    *,
    result_candidates: list[SignalCandidate],
    scored_candidates: list[ScoredResearchCandidate],
    settings: Settings,
    exchange: str,
    quote: str,
    interval: str,
    mock_mode: bool,
    generated_at_utc: str,
    research_warning: str,
    run_id: str,
) -> None:
    by_key = {
        (item.candidate.exchange, item.candidate.symbol, item.candidate.interval): item
        for item in scored_candidates
    }
    selected = [
        by_key[(candidate.exchange, candidate.symbol, candidate.interval)]
        for candidate in result_candidates
        if (candidate.exchange, candidate.symbol, candidate.interval) in by_key
    ]
    store.insert_research_run(
        {
            "run_id": run_id,
            "created_at_utc": generated_at_utc,
            "commit_sha": _current_commit_sha(),
            "config_hash": config_hash(settings),
            "exchange": exchange,
            "quote": quote,
            "interval": interval,
            "data_window_start_utc": (
                min(item.data_window_start_utc for item in selected) if selected else None
            ),
            "data_window_end_utc": (
                max(item.data_window_end_utc for item in selected) if selected else None
            ),
            "mock_mode": mock_mode,
            "candidate_count": len(result_candidates),
            "research_warning": research_warning,
        }
    )
    for candidate in result_candidates:
        item = by_key.get((candidate.exchange, candidate.symbol, candidate.interval))
        if item is None:
            continue
        explanation = {
            **item.score_explanation,
            "rank": candidate.rank,
            "score": candidate.score,
            "research_warning": research_warning,
        }
        store.insert_feature_snapshot(
            {
                "run_id": run_id,
                "exchange": candidate.exchange,
                "symbol": candidate.symbol,
                "interval": candidate.interval,
                "data_timestamp_utc": candidate.data_timestamp_utc,
                "feature": item.snapshot.values,
                "component_scores": candidate.component_scores,
                "penalties": explanation["penalties"],
                "risk_flags": candidate.risk_flags,
                "score_explanation": explanation,
            }
        )


def _runs(args: argparse.Namespace, settings: Settings) -> int:
    store = SQLiteStore(settings.database_path)
    if args.runs_command == "list":
        _print_json({"runs": [_research_run_row_to_dict(row) for row in store.list_research_runs(args.limit)]})
        return 0
    if args.runs_command == "show":
        run = store.get_research_run(args.run_id)
        if run is None:
            print(f"Research run not found: {args.run_id}", file=sys.stderr)
            return 1
        _print_json(
            {
                "run": _research_run_row_to_dict(run),
                "snapshot_count": len(store.get_feature_snapshots(args.run_id)),
            }
        )
        return 0
    if args.runs_command == "export":
        run = store.get_research_run(args.run_id)
        if run is None:
            print(f"Research run not found: {args.run_id}", file=sys.stderr)
            return 1
        _print_json(
            {
                "research_warning": run["research_warning"],
                "run": _research_run_row_to_dict(run),
                "feature_snapshots": [
                    _feature_snapshot_row_to_dict(row)
                    for row in store.get_feature_snapshots(args.run_id)
                ],
            }
        )
        return 0
    raise ConfigError(f"Unknown runs command: {args.runs_command}")


def _current_commit_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _maybe_notify(candidates: list[SignalCandidate], settings: Settings) -> None:
    if not settings.notifications_enabled:
        print("Ranking completed; notifications skipped because they are disabled.")
        return
    notifiers = _configured_notifiers(settings)
    if not notifiers:
        print("Ranking completed; notifications skipped because no channel is enabled.")
        return
    policy = AlertPolicy(
        AlertPolicyConfig(
            score_threshold=settings.alert_score_threshold,
            exit_threshold=settings.alert_exit_threshold,
            score_delta_threshold=settings.alert_score_delta_threshold,
            top_n=settings.alert_top_n,
            cooldown_minutes=settings.alert_cooldown_minutes,
        ),
        state_store=SQLiteAlertStateStore(settings.database_path),
    )
    events = policy.evaluate(candidates)
    store = SQLiteStore(settings.database_path)
    limiter = SQLiteNotificationRateLimiter(
        store,
        global_max_per_minute=settings.alert_global_max_per_minute,
        per_symbol_max_per_hour=settings.alert_per_symbol_max_per_hour,
        safety_global_max_per_minute=settings.alert_safety_global_max_per_minute,
        safety_per_symbol_max_per_hour=settings.alert_safety_per_symbol_max_per_hour,
    )
    allowed_events, suppressed_events = limiter.filter_events(events)
    for event in events:
        store.insert_alert_event(event)
    for decision in suppressed_events:
        store.insert_notification_delivery(suppressed_delivery_record(decision))
    for event in allowed_events:
        for notifier in notifiers:
            channel = getattr(notifier, "channel", "unknown")
            destination = notifier_destination(notifier)
            store.insert_notification_outbox(
                alert_event_id=event.alert_event_id,
                channel=channel,
                destination_hash=destination_hash(channel, destination),
                created_at_utc=datetime.now(tz=UTC).isoformat(),
            )

    dispatcher = NotificationDispatcher(
        True,
        notifiers,
        channel_state_store=SQLiteNotificationChannelStateStore(store),
        outbox_store=store,
    )
    delivery_results = dispatcher.dispatch_with_events(allowed_events)
    for event, result in delivery_results:
        store.insert_notification_delivery(delivery_record(result, event.alert_event_id))
    print(
        f"Ranking completed; {len(events)} alert events evaluated, "
        f"{len(allowed_events)} allowed, {len(suppressed_events)} rate-limited, "
        f"{len(delivery_results)} delivery attempts recorded."
    )


def _configured_notifiers(settings: Settings, channel: str | None = None) -> list[Notifier]:
    notifiers: list[Notifier] = []
    if (channel in {None, "telegram"}) and settings.telegram_enabled:
        settings.validate_notification_channel("telegram")
        notifiers.append(
            TelegramNotifier(
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
                parse_mode=settings.telegram_parse_mode,
                disable_notification=settings.telegram_disable_notification,
            )
        )
    if (channel in {None, "discord"}) and settings.discord_webhook_enabled:
        settings.validate_notification_channel("discord")
        notifiers.append(
            DiscordWebhookNotifier(
                webhook_url=settings.discord_webhook_url,
                username=settings.discord_username,
                thread_id=settings.discord_thread_id,
                allow_mentions=settings.discord_allow_mentions,
            )
        )
    if not notifiers and channel == "noop":
        notifiers.append(NoopNotifier())
    return notifiers


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _research_run_row_to_dict(row: Any) -> dict[str, object]:
    return {
        "run_id": row["run_id"],
        "created_at_utc": row["created_at_utc"],
        "commit_sha": row["commit_sha"],
        "config_hash": row["config_hash"],
        "exchange": row["exchange"],
        "quote": row["quote"],
        "interval": row["interval"],
        "data_window_start_utc": row["data_window_start_utc"],
        "data_window_end_utc": row["data_window_end_utc"],
        "mock_mode": bool(row["mock_mode"]),
        "candidate_count": row["candidate_count"],
        "research_warning": row["research_warning"],
    }


def _feature_snapshot_row_to_dict(row: Any) -> dict[str, object]:
    return {
        "run_id": row["run_id"],
        "exchange": row["exchange"],
        "symbol": row["symbol"],
        "interval": row["interval"],
        "data_timestamp_utc": row["data_timestamp_utc"],
        "feature": json.loads(str(row["feature_json"])),
        "component_scores": json.loads(str(row["component_scores_json"])),
        "penalties": json.loads(str(row["penalties_json"])),
        "risk_flags": json.loads(str(row["risk_flags_json"])),
        "score_explanation": json.loads(str(row["score_explanation_json"])),
    }


def _channel_state_row_to_dict(row: Any) -> dict[str, object]:
    return {
        "channel": row["channel"],
        "destination_hash": row["destination_hash"],
        "status": row["status"],
        "last_error_code": row["last_error_code"],
        "last_error_at_utc": row["last_error_at_utc"],
        "retry_after_until_utc": row["retry_after_until_utc"],
        "manual_reset_required": bool(row["manual_reset_required"]),
    }


def _outbox_row_to_dict(row: Any) -> dict[str, object]:
    return {
        "id": row["id"],
        "alert_event_id": row["alert_event_id"],
        "channel": row["channel"],
        "destination_hash": row["destination_hash"],
        "status": row["status"],
        "created_at_utc": row["created_at_utc"],
        "claimed_at_utc": row["claimed_at_utc"],
        "completed_at_utc": row["completed_at_utc"],
        "retry_count": row["retry_count"],
        "last_error_code": row["last_error_code"],
    }


def _drainable_outbox_rows(store: SQLiteStore, *, limit: int) -> list[Any]:
    rows = [
        *store.list_notification_outbox(status="pending"),
        *store.list_notification_outbox(status="failed_retryable"),
    ]
    rows.sort(key=lambda row: str(row["created_at_utc"]))
    return rows[: max(0, limit)]


def _matching_notifier(notifiers: list[Notifier], channel: str, expected_destination_hash: str) -> Notifier | None:
    for notifier in notifiers:
        notifier_channel = getattr(notifier, "channel", "unknown")
        destination = notifier_destination(notifier)
        if (
            notifier_channel == channel
            and destination_hash(notifier_channel, destination) == expected_destination_hash
        ):
            return notifier
    return None


def _exchange_client(exchange: str, settings: Settings) -> PublicMarketDataClient:
    if exchange == "upbit":
        return UpbitPublicClient(settings.upbit_base_url, timeout=settings.default_request_timeout_seconds)
    return BinancePublicClient(settings.binance_base_url, timeout=settings.default_request_timeout_seconds)


def _print_table(candidates: list[SignalCandidate]) -> None:
    print("Research watchlist only. Not financial advice. No order was placed.")
    if Console is not None and Table is not None:
        table = Table(title="Crypto Signal Research Watchlist")
        for column in ["Rank", "Exchange", "Symbol", "Score", "Confidence", "Price", "Drivers", "Risks"]:
            table.add_column(column)
        for candidate in candidates:
            table.add_row(
                str(candidate.rank or ""),
                candidate.exchange,
                candidate.symbol,
                f"{candidate.score:.1f}",
                candidate.confidence,
                f"{candidate.current_price:.8g}",
                ", ".join(candidate.drivers[:3]),
                ", ".join(candidate.risk_flags[:3]) or "none",
            )
        Console().print(table)
        return
    for candidate in candidates:
        print(
            f"{candidate.rank:>2} {candidate.exchange:<7} {candidate.symbol:<14} "
            f"score={candidate.score:5.1f} confidence={candidate.confidence:<6} "
            f"price={candidate.current_price:.8g} drivers={','.join(candidate.drivers[:3])} "
            f"risks={','.join(candidate.risk_flags[:3]) or 'none'}"
        )


def _sample_candidate() -> SignalCandidate:
    now = datetime.now(tz=UTC).isoformat()
    return SignalCandidate(
        exchange="binance",
        symbol="BTCUSDT",
        interval="15m",
        current_price=100_000.0,
        score=85.0,
        component_scores={
            "trend": 80,
            "momentum": 75,
            "volume": 70,
            "liquidity": 90,
            "breakout": 60,
            "relative_strength": 65,
            "market_regime": 55,
        },
        confidence="medium",
        rank=1,
        drivers=["trend_constructive", "volume_expansion", "positive_relative_strength"],
        risk_flags=[],
        invalidation_condition=(
            "Research view invalidates if score falls below 60, closes below EMA20, "
            "or data becomes stale."
        ),
        data_timestamp_utc=now,
        source_run_id=str(uuid4()),
        is_closed_candle_signal=True,
        data_quality_status="pass",
    )


if __name__ == "__main__":
    raise SystemExit(main())
