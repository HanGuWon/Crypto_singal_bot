from __future__ import annotations

import pytest

from conftest import make_alert
from crypto_signal_bot.alerts.formatter import format_discord_payload
from crypto_signal_bot.notifications.discord_webhook import DiscordWebhookNotifier


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.posts = []

    def post(self, url: str, json: dict, params: dict | None = None) -> FakeResponse:  # noqa: A002
        self.posts.append((url, json, params))
        return self.responses.pop(0)


def test_discord_payload_has_safe_allowed_mentions() -> None:
    payload = format_discord_payload(make_alert())
    assert payload["allowed_mentions"] == {"parse": []}


def test_discord_retries_429(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("crypto_signal_bot.notifications.discord_webhook.time.sleep", lambda _seconds: None)
    client = FakeClient([FakeResponse(429, {"retry_after": 1}), FakeResponse(204)])
    notifier = DiscordWebhookNotifier(webhook_url="https://discord.com/api/webhooks/1/x", http_client=client)
    result = notifier.send(make_alert())
    assert result.status == "delivered"
    assert result.retry_count == 1
    assert len(client.posts) == 2


def test_discord_retries_429_retry_after_header(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("crypto_signal_bot.notifications.discord_webhook.time.sleep", lambda _seconds: None)
    client = FakeClient([FakeResponse(429, headers={"Retry-After": "1"}), FakeResponse(204)])
    notifier = DiscordWebhookNotifier(webhook_url="https://discord.com/api/webhooks/1/x", http_client=client)
    result = notifier.send(make_alert())
    assert result.status == "delivered"
    assert result.retry_count == 1
    assert len(client.posts) == 2


def test_discord_preserves_retry_after_header_when_429_retries_exhausted() -> None:
    client = FakeClient([FakeResponse(429, headers={"Retry-After": "3"})])
    notifier = DiscordWebhookNotifier(
        webhook_url="https://discord.com/api/webhooks/1/x",
        http_client=client,
        max_retries=0,
    )

    result = notifier.send(make_alert())

    assert result.status == "failed"
    assert result.error_code == "429"
    assert result.provider_response is not None
    assert result.provider_response["retry_after"] == 3.0
    assert result.retry_count == 0
    assert len(client.posts) == 1


@pytest.mark.parametrize("status_code", [401, 403, 404])
def test_discord_does_not_retry_authorization_or_destination_failures(status_code: int) -> None:
    client = FakeClient([FakeResponse(status_code)])
    notifier = DiscordWebhookNotifier(webhook_url="https://discord.com/api/webhooks/1/x", http_client=client)
    result = notifier.send(make_alert())
    assert result.status == "failed"
    assert result.error_code == str(status_code)
    assert result.retry_count == 0
    assert len(client.posts) == 1
