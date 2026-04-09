"""Utility helpers shared across modules."""

from __future__ import annotations

import hashlib
import os
import random
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def mask_secret(secret: str, keep: int = 4) -> str:
    if not secret:
        return ""
    if len(secret) <= keep:
        return "*" * len(secret)
    return f"{'*' * (len(secret) - keep)}{secret[-keep:]}"


def env_expand(value: str) -> str:
    """Expand ${VAR} placeholders from environment variables."""

    return os.path.expandvars(value)


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bounded_backoff(base_ms: int, max_ms: int, jitter_ms: int, attempt: int) -> float:
    growth = min(max_ms, base_ms * (2 ** max(0, attempt - 1)))
    if jitter_ms <= 0:
        return growth / 1000.0
    return max(0.0, (growth + random.randint(0, jitter_ms)) / 1000.0)
