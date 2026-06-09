from __future__ import annotations

import random
import time
from dataclasses import dataclass, field


def parse_upbit_remaining_req(header: str | None) -> tuple[str | None, int | None]:
    if not header:
        return None, None
    parts: dict[str, str] = {}
    for item in header.split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts[key.strip()] = value.strip()
    group = parts.get("group")
    sec_raw = parts.get("sec")
    try:
        sec = int(sec_raw) if sec_raw is not None else None
    except ValueError:
        sec = None
    return group, sec


@dataclass
class UpbitRemainingReqLimiter:
    low_remaining_threshold: int = 2
    sleep_seconds: float = 0.25
    remaining_by_group: dict[str, int] = field(default_factory=dict)

    def update_from_header(self, header: str | None) -> None:
        group, sec = parse_upbit_remaining_req(header)
        if group and sec is not None:
            self.remaining_by_group[group] = sec

    def throttle_if_needed(self, group: str | None) -> float:
        if not group:
            return 0.0
        remaining = self.remaining_by_group.get(group)
        if remaining is not None and remaining <= self.low_remaining_threshold:
            time.sleep(self.sleep_seconds)
            return self.sleep_seconds
        return 0.0


@dataclass
class BinanceWeightLimiter:
    max_weight_per_minute: int = 1200
    safety_margin: float = 0.8
    used_weight_1m: int = 0

    @property
    def soft_limit(self) -> int:
        return int(self.max_weight_per_minute * self.safety_margin)

    def update_from_headers(self, headers: dict[str, str]) -> None:
        for key, value in headers.items():
            if key.upper() == "X-MBX-USED-WEIGHT-1M":
                try:
                    self.used_weight_1m = int(value)
                except ValueError:
                    return

    def should_backoff(self, request_weight: int = 1) -> bool:
        return self.used_weight_1m + request_weight >= self.soft_limit


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_sleep_seconds: float = 0.2
    max_sleep_seconds: float = 3.0
    jitter_seconds: float = 0.05

    def sleep_for_attempt(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_sleep_seconds)
        base = min(self.base_sleep_seconds * (2 ** max(attempt - 1, 0)), self.max_sleep_seconds)
        return base + random.uniform(0, self.jitter_seconds)
