"""Background scheduler for periodic key health checks."""

from __future__ import annotations

import asyncio

from app.health.checker import HealthChecker
from app.observability.logging import get_logger


class HealthScheduler:
    def __init__(self, checker: HealthChecker, interval_seconds: int):
        self.checker = checker
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self.logger = get_logger("gateway.health.scheduler")

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.checker.validate_all()
            except Exception:  # noqa: BLE001
                self.logger.exception("health check loop failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
