from __future__ import annotations

import time
from typing import Any

from crypto_signal_bot.alerts.formatter import format_discord_payload
from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.notifications.base import NotificationResult

try:  # pragma: no cover
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


class DiscordWebhookNotifier:
    channel = "discord"

    def __init__(
        self,
        *,
        webhook_url: str,
        username: str = "Crypto Signal Research Bot",
        thread_id: str = "",
        allow_mentions: bool = False,
        http_client: Any | None = None,
        max_retries: int = 2,
    ) -> None:
        if not webhook_url:
            raise ValueError("Discord webhook URL is required.")
        self.webhook_url = webhook_url
        self.username = username
        self.thread_id = thread_id
        self.allow_mentions = allow_mentions
        self.max_retries = max_retries
        self.http_client = http_client or (httpx.Client(timeout=10) if httpx is not None else None)
        if self.http_client is None:
            raise RuntimeError("httpx is required for DiscordWebhookNotifier.")

    def send(self, event: AlertEvent) -> NotificationResult:
        payload = format_discord_payload(
            event,
            username=self.username,
            allow_mentions=self.allow_mentions,
        )
        params = {"thread_id": self.thread_id} if self.thread_id else None
        retries = 0
        for attempt in range(self.max_retries + 1):
            response = self.http_client.post(self.webhook_url, json=payload, params=params)
            if response.status_code in {401, 403, 404}:
                return NotificationResult(
                    self.channel,
                    "failed",
                    "discord_webhook",
                    error_code=str(response.status_code),
                    error_message="Discord webhook authorization or destination failed.",
                    retry_count=retries,
                )
            if response.status_code == 429 and attempt < self.max_retries:
                retries += 1
                time.sleep(_discord_retry_after(response) or 1.0)
                continue
            if 200 <= response.status_code < 300:
                return NotificationResult(
                    self.channel,
                    "delivered",
                    "discord_webhook",
                    provider_response=_safe_json(response),
                    retry_count=retries,
                )
            if response.status_code >= 500 and attempt < self.max_retries:
                retries += 1
                time.sleep(0.5 * (attempt + 1))
                continue
            return NotificationResult(
                self.channel,
                "failed",
                "discord_webhook",
                error_code=str(response.status_code),
                error_message="Discord webhook delivery failed.",
                provider_response=_safe_json(response),
                retry_count=retries,
            )
        return NotificationResult(self.channel, "failed", "discord_webhook", retry_count=retries)


def _discord_retry_after(response: Any) -> float | None:
    header = response.headers.get("Retry-After") if hasattr(response, "headers") else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    data = _safe_json(response)
    retry_after = data.get("retry_after") if isinstance(data, dict) else None
    try:
        return float(retry_after) if retry_after is not None else None
    except (TypeError, ValueError):
        return None


def _safe_json(response: Any) -> dict:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}
    except Exception:
        return {}
