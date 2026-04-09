"""Backoff helper for retry loops."""

from __future__ import annotations

import asyncio

from app.config.models import RetryConfig
from app.core.utils import bounded_backoff


async def sleep_with_backoff(retry_cfg: RetryConfig, attempt: int) -> None:
    delay = bounded_backoff(
        base_ms=retry_cfg.backoff_base_ms,
        max_ms=retry_cfg.backoff_max_ms,
        jitter_ms=retry_cfg.jitter_ms,
        attempt=attempt,
    )
    await asyncio.sleep(delay)
