from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.config.models import EnvSettings, GatewayConfig, KeyConfig, ProviderConfig
from app.config.runtime import RuntimeConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import UnifiedLLMRequest
from app.inventory.cache import InventoryCache
from app.inventory.discovery import InventoryDiscoveryService
from app.inventory.models import InventorySnapshot
from app.providers.base import ProviderAdapter


class SuccessAdapter(ProviderAdapter):
    def __init__(self, provider_name: str, config: ProviderConfig, models: list[str]):
        super().__init__(provider_name=provider_name, config=config)
        self.models = models

    async def chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        return {}

    async def responses(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        return {}

    async def stream_chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> AsyncIterator[bytes]:
        if False:
            yield b""
        return

    async def validate_key(self, key: KeyConfig) -> dict:
        return {"status": "valid", "models": self.models}

    async def list_models(self, key: KeyConfig) -> list[str]:
        return self.models


class FailingAdapter(ProviderAdapter):
    def __init__(self, provider_name: str, config: ProviderConfig, error: GatewayError):
        super().__init__(provider_name=provider_name, config=config)
        self.error = error

    async def chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        return {}

    async def responses(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        return {}

    async def stream_chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> AsyncIterator[bytes]:
        if False:
            yield b""
        return

    async def validate_key(self, key: KeyConfig) -> dict:
        raise self.error

    async def list_models(self, key: KeyConfig) -> list[str]:
        raise self.error


def _runtime_config() -> RuntimeConfig:
    config = GatewayConfig(
        storage={"sqlite_path": "data/test_inventory.db"},
        providers={
            "gemini": ProviderConfig(
                endpoint="https://gemini.invalid",
                priority=10,
                keys=[
                    KeyConfig(id="gemini-main", key="secret-1"),
                    KeyConfig(id="gemini-backup", key="secret-2"),
                ],
            ),
            "openrouter": ProviderConfig(
                endpoint="https://openrouter.invalid",
                priority=20,
                keys=[KeyConfig(id="openrouter-main", key="secret-3")],
            ),
        }
    )
    return RuntimeConfig(config=config, env=EnvSettings())


@pytest.mark.asyncio
async def test_inventory_discovery_merges_models_across_keys() -> None:
    runtime_config = _runtime_config()
    gemini_cfg = runtime_config.get().providers["gemini"]
    openrouter_cfg = runtime_config.get().providers["openrouter"]
    service = InventoryDiscoveryService(
        runtime_config=runtime_config,
        providers={
            "gemini": SuccessAdapter(
                provider_name="gemini",
                config=gemini_cfg,
                models=["gemini-2.5-flash", "gemini-2.5-pro", "imagen-4.0-generate-001"],
            ),
            "openrouter": SuccessAdapter(
                provider_name="openrouter",
                config=openrouter_cfg,
                models=["openrouter/free", "openai/gpt-5.4-mini:free"],
            ),
        },
    )

    snapshot = await service.refresh()

    assert len(snapshot.key_results) == 3
    assert {(item.provider, item.key_id, item.status) for item in snapshot.key_results} == {
        ("gemini", "gemini-main", "valid"),
        ("gemini", "gemini-backup", "valid"),
        ("openrouter", "openrouter-main", "valid"),
    }

    models = {(item.provider, item.model_id): item for item in snapshot.models}
    assert ("gemini", "gemini-2.5-flash") in models
    assert ("gemini", "gemini-2.5-pro") in models
    assert ("gemini", "imagen-4.0-generate-001") in models
    assert ("openrouter", "openrouter/free") not in models
    assert [(item.provider, item.route_id) for item in snapshot.special_routes] == [("openrouter", "openrouter/free")]

    assert sorted(models[("gemini", "gemini-2.5-flash")].source_key_ids) == ["gemini-backup", "gemini-main"]
    assert models[("gemini", "gemini-2.5-flash")].modality == "text"
    assert models[("gemini", "gemini-2.5-flash")].is_text_candidate is True
    assert models[("gemini", "gemini-2.5-flash")].chat_state == "supported"
    assert models[("gemini", "gemini-2.5-flash")].responses_state == "supported"
    assert models[("gemini", "gemini-2.5-flash")].stream_state == "supported"
    assert models[("gemini", "imagen-4.0-generate-001")].modality == "image"
    assert models[("gemini", "imagen-4.0-generate-001")].is_text_candidate is False
    assert models[("gemini", "imagen-4.0-generate-001")].excluded_reason == "non_text_modality:image"
    assert models[("gemini", "imagen-4.0-generate-001")].chat_state == "unsupported"
    assert models[("openrouter", "openai/gpt-5.4-mini:free")].is_free is True
    classifications = {(item.provider, item.model_id): item for item in snapshot.classifications}
    assert "general" in classifications[("gemini", "gemini-2.5-flash")].classification_tags
    assert "excluded" in classifications[("gemini", "imagen-4.0-generate-001")].classification_tags
    alias_ids = {item.alias_id for item in snapshot.generated_aliases}
    assert "gemini/text/fast" in alias_ids
    assert "openrouter/text/free" in alias_ids
    assert "auto/text/free" in alias_ids


@pytest.mark.asyncio
async def test_inventory_discovery_records_auth_failure_per_key() -> None:
    runtime_config = _runtime_config()
    gemini_cfg = runtime_config.get().providers["gemini"]
    openrouter_cfg = runtime_config.get().providers["openrouter"]
    service = InventoryDiscoveryService(
        runtime_config=runtime_config,
        providers={
            "gemini": SuccessAdapter(
                provider_name="gemini",
                config=gemini_cfg,
                models=["gemini-2.5-flash"],
            ),
            "openrouter": FailingAdapter(
                provider_name="openrouter",
                config=openrouter_cfg,
                error=GatewayError(
                    message="Provider openrouter returned 401: invalid key",
                    error_class=ErrorClass.AUTH_INVALID,
                    status_code=401,
                    provider="openrouter",
                    key_id="openrouter-main",
                ),
            ),
        },
    )

    snapshot = await service.refresh()

    failed = next(item for item in snapshot.key_results if item.provider == "openrouter")
    assert failed.status == "invalid"
    assert failed.error_code == "auth_invalid"
    assert failed.discovered_models == 0
    assert [item.model_id for item in snapshot.models] == ["gemini-2.5-flash"]


@pytest.mark.asyncio
async def test_inventory_discovery_applies_provider_specific_text_filters() -> None:
    runtime_config = _runtime_config()
    openrouter_cfg = runtime_config.get().providers["openrouter"]
    service = InventoryDiscoveryService(
        runtime_config=runtime_config,
        providers={
            "openrouter": SuccessAdapter(
                provider_name="openrouter",
                config=openrouter_cfg,
                models=["openrouter/bodybuilder", "perplexity/sonar-pro-search", "openai/gpt-5-mini"],
            ),
        },
    )

    snapshot = await service.refresh()

    models = {(item.provider, item.model_id): item for item in snapshot.models}
    assert models[("openrouter", "openrouter/bodybuilder")].excluded_reason == "special_router_route"
    assert models[("openrouter", "perplexity/sonar-pro-search")].excluded_reason == "search_or_retrieval_route"
    assert models[("openrouter", "openai/gpt-5-mini")].is_text_candidate is True


@pytest.mark.asyncio
async def test_inventory_discovery_applies_manual_override_to_excluded_model() -> None:
    config = GatewayConfig.model_validate(
        {
            "providers": {
                "gemini": {
                    "enabled": True,
                    "priority": 10,
                    "endpoint": "https://example.invalid",
                    "keys": [{"id": "gemini-main", "key": "secret"}],
                }
            },
            "inventory": {
                "overrides": [
                    {
                        "provider": "gemini",
                        "model_pattern": "imagen-4.0-generate-001",
                        "force_modality": "text",
                        "force_include": True,
                        "force_categories": ["general"],
                    }
                ]
            },
        }
    )
    runtime_config = RuntimeConfig(config=config, env=EnvSettings())
    gemini_cfg = runtime_config.get().providers["gemini"]
    service = InventoryDiscoveryService(
        runtime_config=runtime_config,
        providers={
            "gemini": SuccessAdapter(
                provider_name="gemini",
                config=gemini_cfg,
                models=["imagen-4.0-generate-001"],
            ),
        },
    )

    snapshot = await service.refresh()

    model = snapshot.models[0]
    classification = snapshot.classifications[0]
    assert model.modality == "text"
    assert model.is_text_candidate is True
    assert model.excluded_reason is None
    assert model.chat_state == "supported"
    assert classification.general_score > 0


@pytest.mark.asyncio
async def test_inventory_discovery_reuses_file_cache(tmp_path) -> None:
    config = GatewayConfig.model_validate(
        {
            "providers": {
                "openrouter": {
                    "enabled": True,
                    "priority": 10,
                    "endpoint": "https://example.invalid",
                    "keys": [{"id": "openrouter-main", "key": "secret"}],
                }
            },
            "storage": {"sqlite_path": str(tmp_path / "gateway.db")},
            "health": {"startup_check": False},
        }
    )
    runtime_config = RuntimeConfig(config=config, env=EnvSettings())
    provider_cfg = runtime_config.get().providers["openrouter"]
    first = InventoryDiscoveryService(
        runtime_config=runtime_config,
        providers={
            "openrouter": SuccessAdapter(
                provider_name="openrouter",
                config=provider_cfg,
                models=["openai/gpt-4o-mini"],
            )
        },
    )

    refreshed = await first.refresh()
    second = InventoryDiscoveryService(runtime_config=runtime_config, providers={})
    cached = second.current_snapshot()

    assert cached is not None
    assert [item.alias_id for item in cached.generated_aliases] == [
        item.alias_id for item in refreshed.generated_aliases
    ]


def test_inventory_cache_respects_scheduled_stale_boundary(tmp_path) -> None:
    cache_path = tmp_path / "inventory_cache.json"
    snapshot = InventorySnapshot(refreshed_at="2026-04-14T00:00:00+00:00")
    cache = InventoryCache(file_path=cache_path)

    cache.set(snapshot, cached_at=100.0)
    assert cache.get(stale_after=99.0) is snapshot
    assert cache.get(stale_after=101.0) is None

    cache.save_file(snapshot, fingerprint="fp")
    assert InventoryCache(file_path=cache_path).load_file("fp", stale_after=0.0) is not None
    assert InventoryCache(file_path=cache_path).load_file("fp", stale_after=9999999999.0) is None
