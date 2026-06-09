from __future__ import annotations

import logging
import re
from typing import Any

SECRET_PATTERNS = [
    re.compile(r"(?i)(telegram_bot_token=)[^\s,]+"),
    re.compile(r"(?i)(bot_token=)[^\s,]+"),
    re.compile(r"https://discord(?:app)?\.com/api/webhooks/[^\s]+"),
    re.compile(r"https://api\.telegram\.org/bot[^\s/]+"),
]


def redact_secrets(value: Any) -> str:
    text = str(value)
    for pattern in SECRET_PATTERNS:
        if "webhooks" in pattern.pattern:
            text = pattern.sub("https://discord.com/api/webhooks/[REDACTED]", text)
        elif "telegram" in pattern.pattern and "api" in pattern.pattern:
            text = pattern.sub("https://api.telegram.org/bot[REDACTED]", text)
        else:
            text = pattern.sub(r"\1[REDACTED]", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.msg)
        if record.args:
            record.args = tuple(redact_secrets(arg) for arg in record.args)
        return True


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    root = logging.getLogger()
    root.addFilter(RedactingFilter())
    for handler in root.handlers:
        handler.addFilter(RedactingFilter())
