from __future__ import annotations

import time
from typing import Any

from crypto_signal_bot.alerts.formatter import format_telegram_event
from crypto_signal_bot.alerts.schemas import AlertEvent
from crypto_signal_bot.notifications.base import NotificationResult

try:  # pragma: no cover
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


class TelegramNotifier:
    channel = "telegram"

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
        http_client: Any | None = None,
        max_retries: int = 2,
    ) -> None:
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot token and chat id are required.")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.parse_mode = parse_mode
        self.disable_notification = disable_notification
        self.max_retries = max_retries
        self.http_client = http_client or (httpx.Client(timeout=10) if httpx is not None else None)
        if self.http_client is None:
            raise RuntimeError("httpx is required for TelegramNotifier.")

    def destination_key(self) -> str:
        return f"{self.chat_id}:{self.bot_token}"

    def send(self, event: AlertEvent) -> NotificationResult:
        text = format_telegram_event(event)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": self.parse_mode,
            "disable_notification": self.disable_notification,
        }
        retries = 0
        for attempt in range(self.max_retries + 1):
            response = self.http_client.post(url, json=payload)
            if response.status_code in {401, 403}:
                return NotificationResult(
                    self.channel,
                    "failed",
                    self.chat_id,
                    error_code=str(response.status_code),
                    error_message="Telegram authorization failed.",
                    retry_count=retries,
                )
            if response.status_code == 429 and attempt < self.max_retries:
                retries += 1
                time.sleep(_telegram_retry_after(response) or 1.0)
                continue
            if 200 <= response.status_code < 300:
                return NotificationResult(
                    self.channel,
                    "delivered",
                    self.chat_id,
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
                self.chat_id,
                error_code=str(response.status_code),
                error_message="Telegram delivery failed.",
                provider_response=_safe_json(response),
                retry_count=retries,
            )
        return NotificationResult(self.channel, "failed", self.chat_id, retry_count=retries)


def _telegram_retry_after(response: Any) -> float | None:
    data = _safe_json(response)
    parameters = data.get("parameters", {}) if isinstance(data, dict) else {}
    retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
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
