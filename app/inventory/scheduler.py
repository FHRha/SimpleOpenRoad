"""Background scheduler for provider inventory refresh."""

from __future__ import annotations

import asyncio
import time

from app.config.runtime import RuntimeConfig
from app.inventory.discovery import InventoryDiscoveryService, _inventory_next_refresh_at
from app.observability.logging import get_logger


class InventoryRefreshScheduler:
    def __init__(
        self,
        *,
        runtime_config: RuntimeConfig,
        discovery: InventoryDiscoveryService,
        min_sleep_seconds: int = 60,
    ) -> None:
        self.runtime_config = runtime_config
        self.discovery = discovery
        self.min_sleep_seconds = min_sleep_seconds
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self.logger = get_logger("gateway.inventory.scheduler")

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            cfg = self.runtime_config.get()
            next_refresh = _inventory_next_refresh_at(cfg)
            sleep_seconds = max(self.min_sleep_seconds, next_refresh.timestamp() - time.time())
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_seconds)
            except asyncio.TimeoutError:
                pass
            if self._stop_event.is_set():
                return
            try:
                await self.discovery.refresh()
                self.logger.info("inventory refresh completed: next_refresh_at=%s", next_refresh.isoformat())
            except Exception:  # noqa: BLE001
                self.logger.exception("inventory refresh loop failed")

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
