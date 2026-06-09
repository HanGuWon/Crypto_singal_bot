from __future__ import annotations

from conftest import make_alert
from crypto_signal_bot.notifications.telegram import TelegramNotifier


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"ok": True}
        self.headers = {}

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.posts = []

    def post(self, url: str, json: dict) -> FakeResponse:  # noqa: A002
        self.posts.append((url, json))
        return self.responses.pop(0)


def test_telegram_retries_429_retry_after(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("crypto_signal_bot.notifications.telegram.time.sleep", lambda _seconds: None)
    client = FakeClient([
        FakeResponse(429, {"parameters": {"retry_after": 1}}),
        FakeResponse(200, {"ok": True}),
    ])
    notifier = TelegramNotifier(bot_token="token", chat_id="chat", http_client=client)
    result = notifier.send(make_alert())
    assert result.status == "delivered"
    assert result.retry_count == 1
    assert len(client.posts) == 2


def test_telegram_does_not_retry_unauthorized() -> None:
    client = FakeClient([FakeResponse(401, {"ok": False})])
    notifier = TelegramNotifier(bot_token="token", chat_id="chat", http_client=client)
    result = notifier.send(make_alert())
    assert result.status == "failed"
    assert result.retry_count == 0
    assert len(client.posts) == 1
