"""Discovery of provider model catalogs into runtime inventory snapshots."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable
from typing import Any
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config.runtime import RuntimeConfig
from app.core.errors import GatewayError
from app.core.security import is_configured_secret
from app.core.utils import utcnow_iso
from app.inventory.aliases import build_generated_aliases
from app.inventory.cache import InventoryCache
from app.inventory.classifier import classify_model
from app.inventory.filtering import apply_text_filter
from app.inventory.models import DiscoveredModel, InventoryKeyResult, InventorySnapshot, ModelClassification, ProviderSpecialRoute
from app.inventory.normalizer import normalize_discovered_model
from app.inventory.overrides import apply_model_overrides
from app.inventory.special_routes import get_special_route
from app.inventory.validator import enrich_model_capabilities
from app.providers.base import ProviderAdapter


class InventoryDiscoveryService:
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        providers: dict[str, ProviderAdapter],
        cache: InventoryCache | None = None,
    ) -> None:
        self.runtime_config = runtime_config
        self.providers = providers
        self.cache = cache or InventoryCache(file_path=_cache_path(runtime_config.get().storage.sqlite_path))

    def refresh_providers(self, providers: dict[str, ProviderAdapter]) -> None:
        self.providers = providers

    def current_snapshot(self) -> InventorySnapshot | None:
        config = self.runtime_config.get()
        stale_after = _inventory_stale_after(config)
        snapshot = self.cache.get(stale_after=stale_after)
        if snapshot is not None:
            return snapshot
        return self.cache.load_file(_config_fingerprint(config), stale_after=stale_after)

    async def refresh(self) -> InventorySnapshot:
        cfg = self.runtime_config.get()
        refreshed_at = utcnow_iso()
        key_results: list[InventoryKeyResult] = []
        models_by_key: dict[tuple[str, str], DiscoveredModel] = {}
        special_routes: dict[tuple[str, str], ProviderSpecialRoute] = {}

        for provider_name, provider_cfg in sorted(cfg.providers.items(), key=lambda item: item[1].priority):
            if not provider_cfg.enabled:
                continue
            adapter = self.providers.get(provider_name)
            if adapter is None:
                continue

            for key in provider_cfg.keys:
                if not key.active or not is_configured_secret(key.key):
                    continue
                started = time.perf_counter()
                try:
                    discovered_records = await adapter.list_model_records(key)
                    discovered = [
                        str(item.get("id") or item.get("name") or item.get("model"))
                        for item in discovered_records
                        if isinstance(item, dict) and (item.get("id") or item.get("name") or item.get("model"))
                    ]
                    latency_ms = (time.perf_counter() - started) * 1000
                    key_results.append(
                        InventoryKeyResult(
                            provider=provider_name,
                            key_id=key.id,
                            status="valid" if discovered else "degraded",
                            discovered_models=len(discovered),
                            latency_ms=latency_ms,
                            error_code=None if discovered else "no_models_discovered",
                            error_message=None
                            if discovered
                            else f"Provider {provider_name} returned an empty model catalog during inventory refresh",
                            checked_at=utcnow_iso(),
                        )
                    )
                    self._merge_models(
                        config=cfg,
                        provider=provider_name,
                        model_records=discovered_records,
                        key_id=key.id,
                        models_by_key=models_by_key,
                        special_routes=special_routes,
                    )
                except GatewayError as exc:
                    latency_ms = (time.perf_counter() - started) * 1000
                    key_results.append(
                        InventoryKeyResult(
                            provider=provider_name,
                            key_id=key.id,
                            status="invalid" if exc.error_class.value.startswith("auth_") else "degraded",
                            discovered_models=0,
                            latency_ms=latency_ms,
                            error_code=exc.error_class.value,
                            error_message=exc.message,
                            checked_at=utcnow_iso(),
                        )
                    )

        snapshot = InventorySnapshot(
            refreshed_at=refreshed_at,
            key_results=key_results,
            models=sorted(models_by_key.values(), key=lambda item: (item.provider, item.model_id)),
            special_routes=sorted(special_routes.values(), key=lambda item: (item.provider, item.route_id)),
            classifications=_build_classifications(models_by_key.values(), cfg),
            generated_aliases=[],
        )
        snapshot.models = _enrich_models(snapshot.models, snapshot.classifications)
        snapshot.generated_aliases = build_generated_aliases(
            config=cfg,
            models=snapshot.models,
            classifications=snapshot.classifications,
            special_routes=snapshot.special_routes,
        )
        self.cache.set(snapshot)
        self.cache.save_file(snapshot, _config_fingerprint(cfg))
        return snapshot

    @staticmethod
    def _merge_models(
        *,
        config,
        provider: str,
        model_records: Iterable[dict[str, Any] | str],
        key_id: str,
        models_by_key: dict[tuple[str, str], DiscoveredModel],
        special_routes: dict[tuple[str, str], ProviderSpecialRoute],
    ) -> None:
        for item in model_records:
            if isinstance(item, dict):
                model_id_raw = item.get("id") or item.get("name") or item.get("model")
                metadata = item
            else:
                model_id_raw = item
                metadata = {}
            if not model_id_raw:
                continue
            model_id = str(model_id_raw)
            special_route = get_special_route(provider, model_id)
            if special_route is not None:
                special_routes[(provider, special_route.route_id)] = special_route
                continue
            record_key = (provider, model_id)
            existing = models_by_key.get(record_key)
            if existing is None:
                models_by_key[record_key] = apply_model_overrides(
                    apply_text_filter(
                        normalize_discovered_model(
                            provider=provider,
                            model_id=model_id,
                            key_id=key_id,
                            raw_metadata=metadata,
                        )
                    ),
                    config.inventory.overrides,
                )
                continue
            if key_id not in existing.source_key_ids:
                existing.source_key_ids.append(key_id)


def _build_classifications(models: Iterable[DiscoveredModel], config) -> list[ModelClassification]:
    return sorted(
        (
            classify_model(
                model,
                capabilities=config.model_capabilities,
                overrides=config.inventory.overrides,
            )
            for model in models
        ),
        key=lambda item: (item.provider, item.model_id),
    )


def _enrich_models(
    models: list[DiscoveredModel],
    classifications: list[ModelClassification],
) -> list[DiscoveredModel]:
    class_map = {(item.provider, item.model_id): item for item in classifications}
    enriched: list[DiscoveredModel] = []
    for model in models:
        classification = class_map[(model.provider, model.model_id)]
        enriched.append(enrich_model_capabilities(model, classification))
    return enriched


def _cache_path(sqlite_path: str) -> Path:
    return Path(sqlite_path).expanduser().parent / "inventory_cache.json"


def _inventory_stale_after(config) -> float:
    return _inventory_last_refresh_at(config).timestamp()


def _inventory_next_refresh_at(config) -> datetime:
    inventory = config.inventory
    interval = timedelta(hours=max(1, int(inventory.refresh_interval_hours)))
    return _inventory_last_refresh_at(config) + interval


def _inventory_last_refresh_at(config) -> datetime:
    inventory = config.inventory
    refresh_time = _parse_refresh_time(inventory.refresh_time)
    interval = timedelta(hours=max(1, int(inventory.refresh_interval_hours)))
    now = datetime.now(_resolve_timezone(inventory.refresh_timezone))
    anchor = datetime.combine(now.date(), refresh_time, tzinfo=now.tzinfo)
    if now < anchor:
        anchor -= timedelta(days=1)
    while anchor + interval <= now:
        anchor += interval
    return anchor


def _parse_refresh_time(value: str) -> datetime_time:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError:
        parsed = datetime.strptime("05:00", "%H:%M")
    return datetime_time(hour=parsed.hour, minute=parsed.minute)


def _resolve_timezone(value: str):
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        if value.lower() in {"msk", "europe/moscow"}:
            return timezone(timedelta(hours=3), name="MSK")
        return timezone.utc


def _config_fingerprint(config) -> str:
    parts: list[str] = []
    for provider_name, provider_cfg in sorted(config.providers.items()):
        parts.append(f"provider={provider_name}")
        parts.append(f"enabled={provider_cfg.enabled}")
        parts.append(f"endpoint={provider_cfg.endpoint}")
        parts.append(f"account_id={provider_cfg.account_id or ''}")
        for key in sorted(provider_cfg.keys, key=lambda item: item.id):
            key_hash = hashlib.sha256(str(key.key).encode("utf-8")).hexdigest()
            parts.append(f"key={key.id}:{key.active}:{key_hash}")
    for override in config.inventory.overrides:
        parts.append(f"override={override.model_dump_json()}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
