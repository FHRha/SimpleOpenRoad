"""Admin service used by CLI and admin API endpoints."""

from __future__ import annotations

from app.config.runtime import RuntimeConfig
from app.core.security import is_configured_secret
from app.health.checker import HealthChecker
from app.inventory.discovery import InventoryDiscoveryService
from app.observability.metrics import MetricsService
from app.registry.keys import KeyRegistry
from app.router.engine import RoutingEngine
from app.storage.repositories.health_repo import HealthRepository


class AdminService:
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        key_registry: KeyRegistry,
        health_checker: HealthChecker,
        health_repo: HealthRepository,
        metrics: MetricsService,
        routing_engine: RoutingEngine,
        inventory_discovery: InventoryDiscoveryService,
    ):
        self.runtime_config = runtime_config
        self.key_registry = key_registry
        self.health_checker = health_checker
        self.health_repo = health_repo
        self.metrics = metrics
        self.routing_engine = routing_engine
        self.inventory_discovery = inventory_discovery

    def list_providers(self) -> list[dict]:
        cfg = self.runtime_config.get()
        providers: list[dict] = []
        for name, provider_cfg in sorted(cfg.providers.items(), key=lambda item: item[1].priority):
            providers.append(
                {
                    "name": name,
                    "enabled": provider_cfg.enabled,
                    "priority": provider_cfg.priority,
                    "endpoint": provider_cfg.endpoint,
                    "timeout_seconds": provider_cfg.timeout_seconds,
                    "keys_count": sum(1 for key in provider_cfg.keys if is_configured_secret(key.key)),
                }
            )
        return providers

    def list_keys(self) -> list[dict]:
        cfg = self.runtime_config.get()
        return self.key_registry.list_configured_keys(cfg)

    async def validate_key(self, provider: str, key_id: str) -> dict:
        return await self.health_checker.validate_single_key(provider_name=provider, key_id=key_id)

    async def validate_all_keys(self) -> list[dict]:
        return await self.health_checker.validate_all()

    def latest_health(self) -> list[dict]:
        return self.health_repo.latest_by_key()

    def stats(self) -> dict:
        return self.metrics.get_summary()

    async def refresh_inventory(self) -> dict:
        snapshot = await self.inventory_discovery.refresh()
        return snapshot.to_dict()

    def current_inventory(self) -> dict | None:
        snapshot = self.inventory_discovery.current_snapshot()
        return snapshot.to_dict() if snapshot is not None else None

    def reload_config(self) -> dict:
        cfg = self.runtime_config.reload()
        self.key_registry.sync_defaults(cfg)
        self.routing_engine.refresh_providers()
        self.health_checker.providers = self.routing_engine.providers
        self.inventory_discovery.refresh_providers(self.routing_engine.providers)
        return {
            "status": "ok",
            "providers": len(cfg.providers),
            "aliases": len(cfg.routes.aliases),
        }
