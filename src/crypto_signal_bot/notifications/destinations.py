from __future__ import annotations

from hashlib import sha256
from typing import Any


def notifier_destination(notifier: Any) -> str:
    destination = getattr(notifier, "destination_key", None)
    if callable(destination):
        return str(destination())
    if destination:
        return str(destination)
    return str(getattr(notifier, "channel", "unknown"))


def destination_hash(channel: str, destination: str) -> str:
    return sha256(f"{channel}:{destination}".encode()).hexdigest()
