from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.config.models import ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import UnifiedLLMRequest, stringify_content
from app.main import create_app
from app.providers.base import ProviderAdapter


class SuccessAdapter(ProviderAdapter):
    async def chat_completions(self, request: UnifiedLLMRequest, key) -> dict:  # type: ignore[override]
        text = "ok"
        if request.messages:
            text = stringify_content(request.messages[-1].content)
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
            yield f"data: {json.dumps(chunk, ensure_ascii=True)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"

        return iterator()

    async def validate_key(self, key) -> dict:  # type: ignore[override]
        return {"status": "valid", "models": await self.list_models(key), "error_code": None, "error_message": None}

    async def list_models(self, key) -> list[str]:  # type: ignore[override]
        if self.provider_name == "openrouter":
            return ["openai/gpt-4o-mini"]
        return ["gpt-4.1-mini"]


class UnsupportedModelAdapter(SuccessAdapter):
    async def chat_completions(self, request: UnifiedLLMRequest, key) -> dict:  # type: ignore[override]
        raise GatewayError(
            message="unsupported",
            error_class=ErrorClass.UNSUPPORTED_MODEL,
            status_code=400,
            provider=self.provider_name,
            key_id=key.id,
        )


class RecordingAdapter(SuccessAdapter):
    def __init__(self, provider_name: str, config: ProviderConfig):
        super().__init__(provider_name=provider_name, config=config)
        self.last_chat_request: UnifiedLLMRequest | None = None
        self.last_responses_request: UnifiedLLMRequest | None = None

    async def chat_completions(self, request: UnifiedLLMRequest, key) -> dict:  # type: ignore[override]
        self.last_chat_request = request
        return await super().chat_completions(request, key)

    async def responses(self, request: UnifiedLLMRequest, key) -> dict:  # type: ignore[override]
        self.last_responses_request = request
        return await super().responses(request, key)


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
    container.inventory_discovery.refresh_providers(container.routing_engine.providers)


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


def test_openai_models_lists_aliases_and_direct_provider_models(monkeypatch, tmp_path: Path) -> None:
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
        response = client.get("/v1/models", headers={"Authorization": "Bearer master-key"})

    assert response.status_code == 200
    model_ids = [item["id"] for item in response.json()["data"]]
    assert "auto/general" in model_ids
    assert "auto/fast" in model_ids
    assert "github/gpt-4.1-mini" in model_ids
    assert "openrouter/openai/gpt-4o-mini" in model_ids


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
        assert chat.headers.get("x-sor-selected-model") == "github/gpt-4.1-mini"
        assert chat.headers.get("x-sor-failed-candidates") is None
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


def test_chat_headers_show_selected_and_failed_candidates(monkeypatch, tmp_path: Path) -> None:
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
                "model": "auto/fast",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200
    assert response.headers.get("x-sor-selected-model") == "openrouter/openai/gpt-4o-mini"
    assert response.headers.get("x-sor-failed-candidates") == "github/gpt-4.1-mini"


def test_chat_accepts_cline_style_openai_payload(monkeypatch, tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, require_auth=True)
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("MASTER_API_KEY", "master-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-key")

    app = create_app()
    github_adapter = RecordingAdapter(provider_name="github", config=_provider_cfg(app, "github"))
    openrouter_adapter = RecordingAdapter(provider_name="openrouter", config=_provider_cfg(app, "openrouter"))
    _patch_adapters(app, github_adapter, openrouter_adapter)

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"x-api-key": "master-key"},
            json={
                "model": "gpt-4.1-mini",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "hello from cline"}],
                    }
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "description": "Read file contents",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "tool_choice": "auto",
                "stream_options": {"include_usage": True},
                "reasoning_effort": "medium",
            },
        )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hello from cline"
    assert github_adapter.last_chat_request is not None
    assert stringify_content(github_adapter.last_chat_request.messages[0].content) == "hello from cline"
    assert github_adapter.last_chat_request.extra_body["tool_choice"] == "auto"
    assert github_adapter.last_chat_request.extra_body["reasoning_effort"] == "medium"
    assert github_adapter.last_chat_request.extra_body["stream_options"] == {"include_usage": True}
    assert github_adapter.last_chat_request.extra_body["tools"][0]["function"]["name"] == "read_file"


def test_responses_accepts_structured_openai_payload(monkeypatch, tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, require_auth=True)
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("MASTER_API_KEY", "master-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-key")

    app = create_app()
    github_adapter = RecordingAdapter(provider_name="github", config=_provider_cfg(app, "github"))
    openrouter_adapter = RecordingAdapter(provider_name="openrouter", config=_provider_cfg(app, "openrouter"))
    _patch_adapters(app, github_adapter, openrouter_adapter)

    with TestClient(app) as client:
        response = client.post(
            "/v1/responses",
            headers={"x-api-key": "master-key"},
            json={
                "model": "auto/general",
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Summarize this file"}],
                    }
                ],
                "instructions": "Answer briefly",
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "tool_choice": "auto",
                "max_output_tokens": 256,
                "text": {"format": {"type": "text"}},
            },
        )

    assert response.status_code == 200
    assert response.json()["output"][0]["content"][0]["text"] == str(
        [{"role": "user", "content": [{"type": "input_text", "text": "Summarize this file"}]}]
    )
    assert github_adapter.last_responses_request is not None
    assert github_adapter.last_responses_request.max_tokens == 256
    assert github_adapter.last_responses_request.extra_body["instructions"] == "Answer briefly"
    assert github_adapter.last_responses_request.extra_body["tool_choice"] == "auto"
    assert github_adapter.last_responses_request.extra_body["text"] == {"format": {"type": "text"}}


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
                "model": "auto/fast",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["model"] == "openrouter/openai/gpt-4o-mini"

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


def test_503_includes_route_candidate_diagnostics(monkeypatch, tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, require_auth=True)
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    data["providers"]["github"]["keys"] = []
    data["providers"]["openrouter"]["keys"] = []
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("APP_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("MASTER_API_KEY", "master-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-key")

    app = create_app()

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"x-api-key": "master-key"},
            json={
                "model": "gpt-4.1-mini",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["type"] == "provider_unavailable"
    assert detail["details"]["candidates"]
    assert detail["details"]["candidates"][0]["reason"] == "no_available_keys"
