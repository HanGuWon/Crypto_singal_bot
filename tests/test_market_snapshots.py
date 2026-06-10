from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from crypto_signal_bot.cli import main
from crypto_signal_bot.data.models import OrderBook, PriceLevel, Ticker
from crypto_signal_bot.data.store import SQLiteStore


def test_ticker_and_orderbook_round_trip(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "snapshots.sqlite")
    ticker = Ticker(
        exchange="binance",
        symbol="BTCUSDT",
        price=100.0,
        quote_volume_24h=2_000_000.0,
        base_volume_24h=20_000.0,
        price_change_pct_24h=1.2,
        event_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )
    orderbook = OrderBook(
        exchange="binance",
        symbol="BTCUSDT",
        event_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
        bids=[PriceLevel(99.9, 2.0)],
        asks=[PriceLevel(100.1, 3.0)],
    )

    assert store.upsert_tickers([ticker]) == 1
    assert store.upsert_orderbooks([orderbook]) == 1

    loaded_ticker = store.fetch_latest_ticker("binance", "BTCUSDT")
    loaded_orderbook = store.fetch_latest_orderbook("binance", "BTCUSDT")
    assert loaded_ticker is not None
    assert loaded_ticker.quote_volume_24h == 2_000_000.0
    assert loaded_orderbook is not None
    assert loaded_orderbook.best_bid == 99.9
    assert loaded_orderbook.best_ask == 100.1
    assert loaded_orderbook.spread_bps is not None


def test_collect_mock_stores_tickers_and_optional_orderbooks(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "snapshots.sqlite"))

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
            "80",
            "--mock",
            "--with-orderbook",
            "--max-orderbook-symbols",
            "2",
        ])
        == 0
    )

    output = capsys.readouterr().out
    assert "tickers" in output
    assert "orderbooks" in output
    store = SQLiteStore(tmp_path / "snapshots.sqlite")
    assert store.fetch_latest_ticker("binance", "BTCUSDT") is not None
    assert store.fetch_latest_orderbook("binance", "BTCUSDT") is not None


def test_rank_uses_collected_orderbook_spread(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "snapshots.sqlite"))
    main([
        "collect",
        "--exchange",
        "binance",
        "--quote",
        "USDT",
        "--interval",
        "5m",
        "--limit",
        "120",
        "--mock",
        "--with-orderbook",
    ])
    assert (
        main([
            "rank",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--top",
            "1",
            "--format",
            "json",
        ])
        == 0
    )

    payload_text = capsys.readouterr().out
    payload = json.loads(payload_text[payload_text.find("{") :])
    assert "orderbook_unavailable" not in payload["candidates"][0]["risk_flags"]


def test_rank_flags_stale_orderbook_snapshot(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "snapshots.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MAX_ORDERBOOK_AGE_SECONDS", "30")
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
            "120",
            "--mock",
        ])
        == 0
    )
    store = SQLiteStore(db_path)
    stale_time = datetime.now(tz=UTC) - timedelta(minutes=10)
    orderbooks: list[OrderBook] = []
    for symbol in store.list_symbols("binance", "USDT", "5m"):
        candles = store.fetch_candles("binance", symbol, "5m", limit=1)
        latest = candles[-1].close
        orderbooks.append(
            OrderBook(
                exchange="binance",
                symbol=symbol,
                event_time_utc=stale_time,
                bids=[PriceLevel(latest * 0.9995, 10.0)],
                asks=[PriceLevel(latest * 1.0005, 10.0)],
            )
        )
    assert store.upsert_orderbooks(orderbooks) == len(orderbooks)

    assert (
        main([
            "rank",
            "--exchange",
            "binance",
            "--quote",
            "USDT",
            "--interval",
            "5m",
            "--top",
            "3",
            "--format",
            "json",
        ])
        == 0
    )

    payload_text = capsys.readouterr().out
    payload = json.loads(payload_text[payload_text.find("{") :])
    assert payload["candidates"]
    assert all("stale_orderbook" in candidate["risk_flags"] for candidate in payload["candidates"])
    assert all("orderbook_unavailable" not in candidate["risk_flags"] for candidate in payload["candidates"])
