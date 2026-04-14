from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.config.models import EnvSettings, GatewayConfig
from app.config.runtime import RuntimeConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.health.checker import HealthChecker
from app.inventory.discovery import InventoryDiscoveryService
from app.providers.base import ProviderAdapter
from app.registry.keys import KeyRegistry
from app.router.engine import RoutingEngine
from app.storage.db import SQLiteDB
from app.storage.repositories.attempts_repo import AttemptsRepository
from app.storage.repositories.health_repo import HealthRepository
from app.storage.repositories.keys_repo import KeysRuntimeRepository
from app.storage.repositories.route_memory_repo import RouteModelMemoryRepository
from app.storage.repositories.stats_repo import StatsRepository


class DummyProviderAdapter(ProviderAdapter):
    def __init__(self):
        super().__init__(
            provider_name="p1",
            config=GatewayConfig.model_validate(
                {
                    "providers": {
                        "p1": {
                            "endpoint": "https://example.invalid",
                            "keys": [{"id": "p1-k", "key": "x"}],
                        }
                    }
                }
            ).providers["p1"],
        )

    async def chat_completions(self, request: UnifiedLLMRequest, key):  # type: ignore[override]
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    async def responses(self, request: UnifiedLLMRequest, key):  # type: ignore[override]
        return {
            "id": "resp-test",
            "object": "response",
            "created": 1,
            "output": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    async def stream_chat_completions(self, request: UnifiedLLMRequest, key) -> AsyncIterator[bytes]:  # type: ignore[override]
        async def _iter() -> AsyncIterator[bytes]:
            yield b"data: [DONE]\n\n"

        return _iter()

    async def validate_key(self, key):  # type: ignore[override]
        return {"status": "valid", "models": ["gpt-4.1-mini"], "error_code": None, "error_message": None}

    async def list_models(self, key):  # type: ignore[override]
        return ["gpt-4.1-mini"]


class SlowValidateProviderAdapter(DummyProviderAdapter):
    async def validate_key(self, key):  # type: ignore[override]
        await asyncio.sleep(0.01)
        return {"status": "valid", "models": ["m1"], "error_code": None, "error_message": None}


class RateLimitFirstModelAdapter(DummyProviderAdapter):
    async def chat_completions(self, request: UnifiedLLMRequest, key):  # type: ignore[override]
        if request.model in {"gpt-4.1-mini", "m1"}:
            raise GatewayError(
                message="rate limited",
                error_class=ErrorClass.RATE_LIMIT,
                status_code=429,
                provider=self.provider_name,
                key_id=key.id,
            )
        return await super().chat_completions(request, key)


class EmptyChatFirstModelAdapter(DummyProviderAdapter):
    async def chat_completions(self, request: UnifiedLLMRequest, key):  # type: ignore[override]
        if request.model in {"gpt-4.1-mini", "m1"}:
            return {
                "id": "chatcmpl-empty",
                "object": "chat.completion",
                "created": 1,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "stop",
                    }
                ],
            }
        return await super().chat_completions(request, key)


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "app" / "storage" / "schema.sql"


def _build_runtime_config(sqlite_path: str, save_attempt_events: bool = True) -> RuntimeConfig:
    config = GatewayConfig.model_validate(
        {
            "routing": {
                "default_strategy": "strict_priority",
            },
            "providers": {
                "p1": {
                    "enabled": True,
                    "priority": 10,
                    "endpoint": "https://example.invalid",
                    "keys": [
                        {"id": "p1-high", "key": "secret-high", "priority": 100, "max_consecutive_errors": 2},
                        {"id": "p1-low", "key": "secret-low", "priority": 10, "max_consecutive_errors": 2},
                    ],
                }
            },
            "routes": {
                "aliases": {
                    "auto/fast": {
                        "strategy": "least_errors",
                        "candidates": [
                            {"provider": "p1", "model": "m1"},
                            {"provider": "p1", "model": "m2"},
                        ],
                    },
                    "custom/fast": {
                        "strategy": "least_errors",
                        "candidates": [
                            {"provider": "p1", "model": "m1"},
                            {"provider": "p1", "model": "m2"},
                        ],
                    },
                }
            },
            "storage": {"sqlite_path": sqlite_path},
            "health": {"check_timeout_seconds": 0},
            "observability": {"save_attempt_events": save_attempt_events},
        }
    )
    return RuntimeConfig(config=config, env=EnvSettings())


def _build_engine(tmp_path: Path, save_attempt_events: bool = True) -> tuple[RoutingEngine, KeyRegistry, AttemptsRepository]:
    runtime_config = _build_runtime_config(str(tmp_path / "gateway.db"), save_attempt_events=save_attempt_events)
    db = SQLiteDB(runtime_config.get().storage.sqlite_path)
    db.initialize(str(_schema_path()))
    keys_repo = KeysRuntimeRepository(db)
    attempts_repo = AttemptsRepository(db)
    route_memory_repo = RouteModelMemoryRepository(db)
    stats_repo = StatsRepository(db)
    key_registry = KeyRegistry(keys_repo)
    key_registry.sync_defaults(runtime_config.get())
    inventory_discovery = InventoryDiscoveryService(runtime_config=runtime_config, providers={})

    engine = RoutingEngine(
        runtime_config=runtime_config,
        key_registry=key_registry,
        attempts_repo=attempts_repo,
        route_memory_repo=route_memory_repo,
        stats_repo=stats_repo,
        inventory_discovery=inventory_discovery,
    )
    engine.providers = {"p1": DummyProviderAdapter()}
    inventory_discovery.refresh_providers(engine.providers)
    return engine, key_registry, attempts_repo


@pytest.mark.asyncio
async def test_alias_strategy_overrides_default_selection(tmp_path: Path) -> None:
    engine, key_registry, _ = _build_engine(tmp_path)
    with key_registry.runtime_repo.db.connection() as conn:
        conn.execute("UPDATE key_runtime_state SET consecutive_errors = ? WHERE key_id = ?", (3, "p1-high"))
        conn.execute("UPDATE key_runtime_state SET consecutive_errors = ? WHERE key_id = ?", (0, "p1-low"))

    request = UnifiedLLMRequest(model="auto/fast", messages=[ChatMessage(role="user", content="hi")])
    context = engine.build_context(route_alias="auto/fast", stream=False)
    _, decision = await engine.route_chat_completion(request, context)

    assert decision.selected_key_id == "p1-low"


@pytest.mark.asyncio
async def test_save_attempt_events_flag_disables_attempt_persistence(tmp_path: Path) -> None:
    engine, _, attempts_repo = _build_engine(tmp_path, save_attempt_events=False)
    request = UnifiedLLMRequest(model="auto/fast", messages=[ChatMessage(role="user", content="hello")])
    context = engine.build_context(route_alias="auto/fast", stream=False)
    await engine.route_chat_completion(request, context)

    attempts = attempts_repo.list_for_request(context.request_id)
    assert attempts == []


@pytest.mark.asyncio
async def test_router_prefers_remembered_successful_model_for_same_profile_bucket(tmp_path: Path) -> None:
    engine, _, _ = _build_engine(tmp_path)
    assert engine.route_memory_repo is not None
    engine.route_memory_repo.record_success(
        route_alias="custom/fast",
        profile="fast",
        context_bucket="small",
        provider="p1",
        model="m2",
        latency_ms=12.0,
        updated_at="2026-04-14T00:00:00+00:00",
    )

    request = UnifiedLLMRequest(model="custom/fast", messages=[ChatMessage(role="user", content="hello")])
    context = engine.build_context(route_alias="custom/fast", stream=False)
    payload, decision = await engine.route_chat_completion(request, context)

    assert payload["model"] == "p1/m2"
    assert decision.attempts[0].model == "m2"


def test_key_is_blocked_after_max_consecutive_errors(tmp_path: Path) -> None:
    runtime_config = _build_runtime_config(str(tmp_path / "gateway.db"))
    db = SQLiteDB(runtime_config.get().storage.sqlite_path)
    db.initialize(str(_schema_path()))
    keys_repo = KeysRuntimeRepository(db)
    key_registry = KeyRegistry(keys_repo)
    key_registry.sync_defaults(runtime_config.get())

    key = runtime_config.get().providers["p1"].keys[1]
    key_registry.record_failure(key=key, error_class=ErrorClass.PROVIDER_UNAVAILABLE, error_message="boom")
    key_registry.record_failure(key=key, error_class=ErrorClass.PROVIDER_UNAVAILABLE, error_message="boom")

    state = keys_repo.get_state(key.id)
    assert state is not None
    assert state["status"] == "blocked"


def test_unconfigured_placeholder_keys_are_not_available(tmp_path: Path) -> None:
    config = GatewayConfig.model_validate(
        {
            "providers": {
                "p1": {
                    "enabled": True,
                    "endpoint": "https://example.invalid",
                    "keys": [
                        {"id": "p1-placeholder", "key": "${P1_API_KEY}", "priority": 100},
                        {"id": "p1-real", "key": "real-secret", "priority": 10},
                    ],
                }
            },
            "storage": {"sqlite_path": str(tmp_path / "gateway.db")},
        }
    )
    db = SQLiteDB(config.storage.sqlite_path)
    db.initialize(str(_schema_path()))
    keys_repo = KeysRuntimeRepository(db)
    key_registry = KeyRegistry(keys_repo)
    key_registry.sync_defaults(config)

    available = key_registry.get_available_keys(config, "p1")
    listed = key_registry.list_configured_keys(config)
    listed_all = key_registry.list_configured_keys(config, include_unconfigured=True)

    assert [key.id for key in available] == ["p1-real"]
    assert [row["id"] for row in listed] == ["p1-real"]
    assert [row["id"] for row in listed_all] == ["p1-placeholder", "p1-real"]


@pytest.mark.asyncio
async def test_health_checker_respects_check_timeout(tmp_path: Path) -> None:
    runtime_config = _build_runtime_config(str(tmp_path / "gateway.db"))
    db = SQLiteDB(runtime_config.get().storage.sqlite_path)
    db.initialize(str(_schema_path()))
    keys_repo = KeysRuntimeRepository(db)
    health_repo = HealthRepository(db)
    key_registry = KeyRegistry(keys_repo)
    key_registry.sync_defaults(runtime_config.get())

    checker = HealthChecker(
        runtime_config=runtime_config,
        providers={"p1": SlowValidateProviderAdapter()},
        key_registry=key_registry,
        health_repo=health_repo,
    )
    result = await checker.validate_single_key(provider_name="p1", key_id="p1-high")

    assert result["status"] == "degraded"
    assert result["error_code"] == "health_check_timeout"


@pytest.mark.asyncio
async def test_rate_limited_cooldown_returns_429_instead_of_generic_503(tmp_path: Path) -> None:
    engine, key_registry, _ = _build_engine(tmp_path)
    for key in engine.runtime_config.get().providers["p1"].keys:
        key_registry.record_failure(key=key, error_class=ErrorClass.RATE_LIMIT, error_message="rate limited")

    request = UnifiedLLMRequest(model="auto/fast", messages=[ChatMessage(role="user", content="hello")])
    context = engine.build_context(route_alias="auto/fast", stream=False)

    with pytest.raises(GatewayError) as exc_info:
        await engine.route_chat_completion(request, context)

    assert exc_info.value.status_code == 429
    assert exc_info.value.error_class == ErrorClass.RATE_LIMIT
    assert "cooling down" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_router_switches_to_next_model_when_first_model_rate_limited(tmp_path: Path) -> None:
    config = GatewayConfig.model_validate(
        {
            "routing": {
                "default_strategy": "strict_priority",
                "retry": {"max_attempts_per_candidate": 2},
            },
            "providers": {
                "p1": {
                    "enabled": True,
                    "priority": 10,
                    "endpoint": "https://example.invalid",
                    "keys": [{"id": "p1-main", "key": "secret-main", "priority": 100}],
                }
            },
            "routes": {
                "aliases": {
                    "custom/fast": {
                        "strategy": "strict_priority",
                        "candidates": [
                            {"provider": "p1", "model": "m1"},
                            {"provider": "p1", "model": "m2"},
                        ],
                    }
                }
            },
            "storage": {"sqlite_path": str(tmp_path / "gateway.db")},
            "health": {"check_timeout_seconds": 0},
        }
    )
    runtime_config = RuntimeConfig(config=config, env=EnvSettings())
    db = SQLiteDB(runtime_config.get().storage.sqlite_path)
    db.initialize(str(_schema_path()))
    keys_repo = KeysRuntimeRepository(db)
    attempts_repo = AttemptsRepository(db)
    route_memory_repo = RouteModelMemoryRepository(db)
    stats_repo = StatsRepository(db)
    key_registry = KeyRegistry(keys_repo)
    key_registry.sync_defaults(runtime_config.get())
    inventory_discovery = InventoryDiscoveryService(runtime_config=runtime_config, providers={})

    engine = RoutingEngine(
        runtime_config=runtime_config,
        key_registry=key_registry,
        attempts_repo=attempts_repo,
        route_memory_repo=route_memory_repo,
        stats_repo=stats_repo,
        inventory_discovery=inventory_discovery,
    )
    engine.providers = {"p1": RateLimitFirstModelAdapter()}
    inventory_discovery.refresh_providers(engine.providers)

    request = UnifiedLLMRequest(model="custom/fast", messages=[ChatMessage(role="user", content="hello")])
    context = engine.build_context(route_alias="custom/fast", stream=False)
    payload, decision = await engine.route_chat_completion(request, context)

    assert payload["choices"][0]["message"]["content"] == "ok"
    assert payload["model"] == "p1/m2"
    assert [attempt.model for attempt in decision.attempts] == ["m1", "m2"]


@pytest.mark.asyncio
async def test_router_switches_to_next_model_when_first_model_returns_empty_chat(tmp_path: Path) -> None:
    config = GatewayConfig.model_validate(
        {
            "routing": {
                "default_strategy": "strict_priority",
                "retry": {"max_attempts_per_candidate": 1},
            },
            "providers": {
                "p1": {
                    "enabled": True,
                    "priority": 10,
                    "endpoint": "https://example.invalid",
                    "keys": [{"id": "p1-main", "key": "secret-main", "priority": 100}],
                }
            },
            "routes": {
                "aliases": {
                    "custom/fast": {
                        "strategy": "strict_priority",
                        "candidates": [
                            {"provider": "p1", "model": "m1"},
                            {"provider": "p1", "model": "m2"},
                        ],
                    }
                }
            },
            "storage": {"sqlite_path": str(tmp_path / "gateway.db")},
            "health": {"check_timeout_seconds": 0},
        }
    )
    runtime_config = RuntimeConfig(config=config, env=EnvSettings())
    db = SQLiteDB(runtime_config.get().storage.sqlite_path)
    db.initialize(str(_schema_path()))
    keys_repo = KeysRuntimeRepository(db)
    attempts_repo = AttemptsRepository(db)
    route_memory_repo = RouteModelMemoryRepository(db)
    stats_repo = StatsRepository(db)
    key_registry = KeyRegistry(keys_repo)
    key_registry.sync_defaults(runtime_config.get())
    inventory_discovery = InventoryDiscoveryService(runtime_config=runtime_config, providers={})

    engine = RoutingEngine(
        runtime_config=runtime_config,
        key_registry=key_registry,
        attempts_repo=attempts_repo,
        route_memory_repo=route_memory_repo,
        stats_repo=stats_repo,
        inventory_discovery=inventory_discovery,
    )
    engine.providers = {"p1": EmptyChatFirstModelAdapter()}
    inventory_discovery.refresh_providers(engine.providers)

    request = UnifiedLLMRequest(model="custom/fast", messages=[ChatMessage(role="user", content="hello")])
    context = engine.build_context(route_alias="custom/fast", stream=False)
    payload, decision = await engine.route_chat_completion(request, context)

    assert payload["choices"][0]["message"]["content"] == "ok"
    assert payload["model"] == "p1/m2"
    assert [attempt.model for attempt in decision.attempts] == ["m1", "m2"]
    assert decision.attempts[0].error_class == ErrorClass.MALFORMED_RESPONSE
