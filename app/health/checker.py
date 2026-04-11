"""Health check orchestrator for provider keys."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from app.config.runtime import RuntimeConfig
from app.core.security import is_configured_secret
from app.core.utils import utcnow_iso
from app.providers.base import ProviderAdapter
from app.registry.keys import KeyRegistry
from app.storage.repositories.health_repo import HealthRepository


class HealthChecker:
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        providers: dict[str, ProviderAdapter],
        key_registry: KeyRegistry,
        health_repo: HealthRepository,
    ):
        self.runtime_config = runtime_config
        self.providers = providers
        self.key_registry = key_registry
        self.health_repo = health_repo

    async def validate_single_key(self, provider_name: str, key_id: str) -> dict:
        config = self.runtime_config.get()
        provider_cfg = config.providers.get(provider_name)
        adapter = self.providers.get(provider_name)
        if provider_cfg is None or adapter is None:
            return {
                "provider": provider_name,
                "key_id": key_id,
                "status": "invalid",
                "models": [],
                "error_code": "provider_not_found",
                "error_message": "Provider not configured",
                "checked_at": utcnow_iso(),
            }

        key = next((item for item in provider_cfg.keys if item.id == key_id), None)
        if key is None:
            return {
                "provider": provider_name,
                "key_id": key_id,
                "status": "invalid",
                "models": [],
                "error_code": "key_not_found",
                "error_message": "Key not found",
                "checked_at": utcnow_iso(),
            }
        if not is_configured_secret(key.key):
            return {
                "provider": provider_name,
                "key_id": key_id,
                "status": "unconfigured",
                "models": [],
                "error_code": "key_not_configured",
                "error_message": "Provider key is empty or still uses an environment placeholder",
                "checked_at": utcnow_iso(),
            }

        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                adapter.validate_key(key),
                timeout=float(config.health.check_timeout_seconds),
            )
        except asyncio.TimeoutError:
            result = {
                "status": "degraded",
                "models": [],
                "error_code": "health_check_timeout",
                "error_message": "Health check timed out",
            }
        latency_ms = (time.perf_counter() - start) * 1000
        checked_at = datetime.now(UTC).isoformat()
        status = result.get("status", "degraded")
        error_code = result.get("error_code")
        error_message = result.get("error_message")
        models = result.get("models", [])

        self.health_repo.add_result(
            key_id=key.id,
            provider=provider_name,
            status=status,
            latency_ms=latency_ms,
            models=models,
            error_code=error_code,
            error_message=error_message,
            checked_at=checked_at,
        )
        self.key_registry.mark_health(
            key_id=key.id,
            status=status,
            checked_at=checked_at,
            error_code=error_code,
            error_message=error_message,
        )

        return {
            "provider": provider_name,
            "key_id": key.id,
            "status": status,
            "models": models,
            "latency_ms": latency_ms,
            "error_code": error_code,
            "error_message": error_message,
            "checked_at": checked_at,
        }

    async def validate_all(self) -> list[dict]:
        config = self.runtime_config.get()
        results: list[dict] = []
        for provider_name, provider_cfg in config.providers.items():
            if not provider_cfg.enabled or provider_name not in self.providers:
                continue
            for key in provider_cfg.keys:
                if not is_configured_secret(key.key):
                    continue
                results.append(await self.validate_single_key(provider_name, key.id))
        return results
