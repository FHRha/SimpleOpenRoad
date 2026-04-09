from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.config.models import ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import UnifiedLLMRequest
from app.main import create_app
from app.providers.base import ProviderAdapter


class SuccessAdapter(ProviderAdapter):
    async def chat_completions(self, request: UnifiedLLMRequest, key) -> dict:  # type: ignore[override]
        text = "ok"
        if request.messages:
            text = request.messages[-1].content
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": request.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    async def responses(self, request: UnifiedLLMRequest, key) -> dict:  # type: ignore[override]
        text = str(request.input)
        return {
            "id": "resp-test",
            "object": "response",
            "created": 1,
            "model": request.model,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    async def stream_chat_completions(self, request: UnifiedLLMRequest, key) -> AsyncIterator[bytes]:  # type: ignore[override]
        async def iterator() -> AsyncIterator[bytes]:
            chunk = {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": request.model,
                "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=True)}\\n\\n".encode("utf-8")
            yield b"data: [DONE]\\n\\n"

        return iterator()

    async def validate_key(self, key) -> dict:  # type: ignore[override]
        return {"status": "valid", "models": ["m1"], "error_code": None, "error_message": None}

    async def list_models(self, key) -> list[str]:  # type: ignore[override]
        return ["m1"]


class UnsupportedModelAdapter(SuccessAdapter):
    async def chat_completions(self, request: UnifiedLLMRequest, key) -> dict:  # type: ignore[override]
        raise GatewayError(
            message="unsupported",
            error_class=ErrorClass.UNSUPPORTED_MODEL,
            status_code=400,
            provider=self.provider_name,
            key_id=key.id,
        )


def _write_config(tmp_path: Path, require_auth: bool = True) -> Path:
    config = {
        "server": {
            "host": "127.0.0.1",
            "port": 12345,
            "request_timeout_seconds": 30,
            "stream_timeout_seconds": 120,
        },
        "security": {
            "require_master_key": require_auth,
            "require_admin_key": require_auth,
            "mask_secrets_in_logs": True,
        },
        "routing": {
            "default_strategy": "strict_priority",
            "retry": {
                "max_attempts_per_candidate": 2,
                "backoff_base_ms": 1,
                "backoff_max_ms": 5,
                "jitter_ms": 0,
            },
            "error_policy": {
                "auth_invalid": "switch_key",
                "auth_forbidden": "switch_key",
                "rate_limit": "retry_then_switch_key",
                "provider_unavailable": "retry_then_switch_provider",
                "network_timeout": "retry_then_switch_key",
                "malformed_response": "switch_provider",
                "unsupported_model": "switch_provider",
            },
        },
        "providers": {
            "github": {
                "enabled": True,
                "priority": 20,
                "endpoint": "https://example.invalid",
                "timeout_seconds": 5,
                "keys": [{"id": "github-main", "key": "gh-key", "priority": 100}],
            },
            "openrouter": {
                "enabled": True,
                "priority": 30,
                "endpoint": "https://example.invalid",
                "timeout_seconds": 5,
                "keys": [{"id": "openrouter-main", "key": "or-key", "priority": 90}],
            },
        },
        "routes": {
            "aliases": {
                "auto/fast": {
                    "strategy": "strict_priority",
                    "candidates": [{"provider": "github", "model": "gpt-4.1-mini"}],
                },
                "auto/fallback": {
                    "strategy": "strict_priority",
                    "candidates": [
                        {"provider": "github", "model": "gpt-4.1-mini"},
                        {"provider": "openrouter", "model": "gpt-4o-mini"},
                    ],
                },
            }
        },
        "storage": {"sqlite_path": str(tmp_path / "gateway.db")},
        "health": {
            "check_interval_seconds": 3600,
            "startup_check": False,
            "check_timeout_seconds": 2,
        },
        "observability": {
            "json_logs": True,
            "request_log": True,
            "router_decision_log": True,
            "save_attempt_events": True,
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _patch_adapters(app, github_adapter: ProviderAdapter, openrouter_adapter: ProviderAdapter) -> None:
    container = app.state.container
    container.routing_engine.providers = {
        "github": github_adapter,
        "openrouter": openrouter_adapter,
    }
    container.health_checker.providers = container.routing_engine.providers


def _provider_cfg(app, name: str) -> ProviderConfig:
    return app.state.container.runtime_config.get().providers[name]


def test_auth_for_user_and_admin_endpoints(monkeypatch, tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, require_auth=True)
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("MASTER_API_KEY", "master-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-key")

    app = create_app()
    _patch_adapters(
        app,
        SuccessAdapter(provider_name="github", config=_provider_cfg(app, "github")),
        SuccessAdapter(provider_name="openrouter", config=_provider_cfg(app, "openrouter")),
    )

    with TestClient(app) as client:
        assert client.get("/providers").status_code == 401
        assert client.get("/keys").status_code == 401
        assert client.get("/providers", headers={"x-api-key": "master-key"}).status_code == 200
        assert client.get("/keys", headers={"x-admin-key": "admin-key"}).status_code == 200


def test_chat_responses_and_stream_with_mocked_provider(monkeypatch, tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, require_auth=True)
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("MASTER_API_KEY", "master-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-key")

    app = create_app()
    _patch_adapters(
        app,
        SuccessAdapter(provider_name="github", config=_provider_cfg(app, "github")),
        SuccessAdapter(provider_name="openrouter", config=_provider_cfg(app, "openrouter")),
    )

    with TestClient(app) as client:
        chat = client.post(
            "/v1/chat/completions",
            headers={"x-api-key": "master-key"},
            json={
                "model": "auto/fast",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert chat.status_code == 200
        assert chat.headers.get("x-request-id")
        assert chat.json()["choices"][0]["message"]["content"] == "hello"

        responses = client.post(
            "/v1/responses",
            headers={"x-api-key": "master-key"},
            json={
                "model": "auto/fast",
                "input": "ping",
            },
        )
        assert responses.status_code == 200
        assert responses.json()["output"][0]["content"][0]["text"] == "ping"

        with client.stream(
            "POST",
            "/v1/chat/completions",
            headers={"x-api-key": "master-key"},
            json={
                "model": "auto/fast",
                "stream": True,
                "messages": [{"role": "user", "content": "stream"}],
            },
        ) as stream_resp:
            body = b"".join(stream_resp.iter_bytes()).decode("utf-8", errors="replace")
            assert stream_resp.status_code == 200
            assert "data: [DONE]" in body


def test_failover_switches_to_next_provider(monkeypatch, tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, require_auth=True)
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("MASTER_API_KEY", "master-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-key")

    app = create_app()
    _patch_adapters(
        app,
        UnsupportedModelAdapter(provider_name="github", config=_provider_cfg(app, "github")),
        SuccessAdapter(provider_name="openrouter", config=_provider_cfg(app, "openrouter")),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"x-api-key": "master-key"},
            json={
                "model": "auto/fallback",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["model"] == "openrouter/gpt-4o-mini"

        with app.state.container.attempts_repo.db.connection() as conn:
            rows = conn.execute(
                "SELECT provider, outcome FROM request_attempts ORDER BY id DESC LIMIT 2"
            ).fetchall()
        attempts = list(reversed([dict(row) for row in rows]))
        assert len(attempts) == 2
        assert attempts[0]["provider"] == "github"
        assert attempts[0]["outcome"] == "failure"
        assert attempts[1]["provider"] == "openrouter"
        assert attempts[1]["outcome"] == "success"
