from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from uuid import uuid4

from crypto_signal_bot.alerts.delivery_log import delivery_record
from crypto_signal_bot.alerts.dispatcher import NotificationDispatcher
from crypto_signal_bot.alerts.formatter import format_telegram_event
from crypto_signal_bot.alerts.policy import AlertPolicy, AlertPolicyConfig
from crypto_signal_bot.alerts.state import SQLiteAlertStateStore
from crypto_signal_bot.config import ConfigError, Settings, load_settings
from crypto_signal_bot.data.collector import make_mock_candles
from crypto_signal_bot.data.quality import assess_candles
from crypto_signal_bot.data.store import SQLiteStore
from crypto_signal_bot.exchanges.binance import BinancePublicClient
from crypto_signal_bot.exchanges.upbit import UpbitPublicClient
from crypto_signal_bot.features.feature_builder import build_feature_snapshot
from crypto_signal_bot.logging_config import configure_logging
from crypto_signal_bot.notifications.discord_webhook import DiscordWebhookNotifier
from crypto_signal_bot.notifications.noop import NoopNotifier
from crypto_signal_bot.notifications.telegram import TelegramNotifier
from crypto_signal_bot.signals.ranking import rank_candidates
from crypto_signal_bot.signals.schemas import SignalCandidate
from crypto_signal_bot.signals.scoring import ScoringEngine

try:  # pragma: no cover - rich availability depends on environment
    from rich.console import Console
    from rich.table import Table
except ImportError:  # pragma: no cover
    Console = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]


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
    collect.add_argument("--mock", action="store_true", help="Use deterministic local fixture data.")

    rank = sub.add_parser("rank", help="Rank stored public-market candidates.")
    rank.add_argument("--exchange", choices=["upbit", "binance"], required=True)
    rank.add_argument("--quote", default=None)
    rank.add_argument("--interval", default="5m")
    rank.add_argument("--top", type=int, default=20)
    rank.add_argument("--format", choices=["table", "json"], default="table")
    rank.add_argument("--notify", action="store_true")
    rank.add_argument("--mock", action="store_true", help="Seed deterministic fixture data before ranking.")

    backtest = sub.add_parser("backtest", help="Run a minimal leakage-safe event-study smoke test.")
    backtest.add_argument("--exchange", choices=["upbit", "binance"], required=True)
    backtest.add_argument("--quote", default=None)
    backtest.add_argument("--interval", default="15m")
    backtest.add_argument("--from", dest="from_date", default=None)
    backtest.add_argument("--to", dest="to_date", default=None)
    backtest.add_argument("--mock", action="store_true")

    alert_test = sub.add_parser("alert-test", help="Format or send a research alert test.")
    alert_test.add_argument("--channel", choices=["noop", "telegram", "discord"], default="noop")
    return parser


def _collect(args: argparse.Namespace, settings: Settings) -> int:
    quote = args.quote or ("KRW" if args.exchange == "upbit" else "USDT")
    store = SQLiteStore(settings.database_path)
    if args.mock:
        count = store.upsert_candles(
            make_mock_candles(args.exchange, quote, args.interval, limit=args.limit)
        )
        print(f"Stored {count} mocked public candles for {args.exchange} {quote}.")
        print("Research-only data collection completed. No order was placed.")
        return 0

    client = _exchange_client(args.exchange, settings)
    markets = client.get_markets(quote)
    max_symbols = args.max_symbols or settings.max_symbols_per_collect
    selected = markets[:max_symbols]
    stored = 0
    for market in selected:
        candles = client.get_candles(market.raw_symbol, args.interval, args.limit)
        stored += store.upsert_candles(candles)
    print(
        f"Stored {stored} public candles for {len(selected)} {args.exchange} {quote} symbols. "
        "No private API was used."
    )
    return 0


def _rank(args: argparse.Namespace, settings: Settings) -> int:
    quote = args.quote or ("KRW" if args.exchange == "upbit" else "USDT")
    store = SQLiteStore(settings.database_path)
    if args.mock:
        store.upsert_candles(make_mock_candles(args.exchange, quote, args.interval, limit=160))
    candidates = _score_from_store(store, args.exchange, quote, args.interval, args.top, settings)
    result = rank_candidates(candidates, top=args.top)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "source_run_id": result.source_run_id,
                    "generated_at_utc": result.generated_at_utc,
                    "research_warning": result.research_warning,
                    "candidates": [candidate.to_dict() for candidate in result.candidates],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        _print_table(result.candidates)

    if args.notify:
        _maybe_notify(result.candidates, settings)
    return 0


def _backtest(args: argparse.Namespace, settings: Settings) -> int:
    from crypto_signal_bot.backtest.engine import event_study_next_open

    quote = args.quote or ("KRW" if args.exchange == "upbit" else "USDT")
    store = SQLiteStore(settings.database_path)
    if args.mock:
        store.upsert_candles(make_mock_candles(args.exchange, quote, args.interval, limit=120))
    symbols = store.list_symbols(args.exchange, quote, args.interval)
    if not symbols:
        print("No stored candles found. Run collect first or use --mock.")
        return 1
    candles = store.fetch_candles(args.exchange, symbols[0], args.interval)
    signal_indices = list(range(50, max(50, len(candles) - 5), 20))
    metrics = event_study_next_open(candles, signal_indices)
    print(json.dumps(metrics, indent=2))
    print("Backtest smoke run used next-candle entries only. No order was placed.")
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


def _score_from_store(
    store: SQLiteStore,
    exchange: str,
    quote: str,
    interval: str,
    top: int,
    settings: Settings,
) -> list[SignalCandidate]:
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
    candidates: list[SignalCandidate] = []
    for symbol in symbols:
        candles = store.fetch_candles(exchange, symbol, interval, limit=240)
        if len(candles) < 25:
            continue
        quality = assess_candles(
            candles,
            interval,
            max_staleness_seconds=settings.max_staleness_seconds,
        )
        snapshot = build_feature_snapshot(
            candles,
            quality=quality,
            benchmark_candles=benchmark_candles if benchmark_candles else None,
        )
        candidates.append(engine.score(snapshot, source_run_id=run_id))
    return rank_candidates(candidates, top=top).candidates


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
        )
        ,
        state_store=SQLiteAlertStateStore(settings.database_path),
    )
    events = policy.evaluate(candidates)
    dispatcher = NotificationDispatcher(True, notifiers)
    delivery_results = dispatcher.dispatch_with_events(events)
    store = SQLiteStore(settings.database_path)
    for event in events:
        store.insert_alert_event(event)
    for event, result in delivery_results:
        store.insert_notification_delivery(delivery_record(result, event.alert_event_id))
    print(
        f"Ranking completed; {len(events)} alert events evaluated, "
        f"{len(delivery_results)} delivery attempts recorded."
    )


def _configured_notifiers(settings: Settings, channel: str | None = None) -> list[object]:
    notifiers: list[object] = []
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


def _exchange_client(exchange: str, settings: Settings) -> object:
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
