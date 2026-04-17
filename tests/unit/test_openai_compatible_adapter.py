from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.providers.openai_compatible import OpenAICompatibleAdapter


def _adapter() -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        provider_name="openrouter",
        config=ProviderConfig(endpoint="https://openrouter.example", keys=[]),
    )


def _adapter_with_v1_endpoint() -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        provider_name="openrouter",
        config=ProviderConfig(endpoint="https://openrouter.example/api/v1", keys=[]),
    )


def _adapter_with_headers(headers: dict[str, str]) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        provider_name="openrouter",
        config=ProviderConfig(endpoint="https://openrouter.example/api/v1", headers=headers, keys=[]),
        extra_headers={"X-Default": "adapter", "X-Override": "adapter"},
    )


@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_stream_preserves_sse_event_boundaries() -> None:
    chunk = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m1",
        "choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}],
    }
    body = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"
    respx.post("https://openrouter.example/v1/chat/completions").mock(return_value=httpx.Response(200, text=body))

    iterator = await _adapter().stream_chat_completions(
        UnifiedLLMRequest(model="m1", messages=[ChatMessage(role="user", content="hello")], stream=True),
        KeyConfig(id="openrouter-main", key="secret"),
    )

    chunks = [chunk.decode("utf-8") async for chunk in iterator]

    assert chunks == [f"data: {json.dumps(chunk)}\n\n", "data: [DONE]\n\n"]


@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_does_not_duplicate_v1_for_v1_endpoint() -> None:
    respx.post("https://openrouter.example/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )
    )

    result = await _adapter_with_v1_endpoint().chat_completions(
        UnifiedLLMRequest(model="m1", messages=[ChatMessage(role="user", content="hello")]),
        KeyConfig(id="openrouter-main", key="secret"),
    )

    assert result["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_lists_models_with_get() -> None:
    respx.get("https://openrouter.example/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "openai/gpt-4o-mini"}]})
    )

    models = await _adapter_with_v1_endpoint().list_models(KeyConfig(id="openrouter-main", key="secret"))

    assert models == ["openai/gpt-4o-mini"]


@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_config_headers_override_adapter_defaults() -> None:
    route = respx.get("https://openrouter.example/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "openai/gpt-4o-mini"}]})
    )

    await _adapter_with_headers({"X-Override": "config"}).list_models(KeyConfig(id="openrouter-main", key="secret"))

    assert route.calls.last.request.headers["x-default"] == "adapter"
    assert route.calls.last.request.headers["x-override"] == "config"


@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_validate_reports_empty_catalog_reason() -> None:
    respx.get("https://openrouter.example/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    result = await _adapter_with_v1_endpoint().validate_key(KeyConfig(id="openrouter-main", key="secret"))

    assert result["status"] == "degraded"
    assert result["models"] == []
    assert result["error_code"] == "no_models_discovered"
    assert "empty model catalog" in result["error_message"]


@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_classifies_quota_403_as_rate_limit() -> None:
    respx.post("https://openrouter.example/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "message": "Key limit exceeded (total limit). Manage it using settings.",
                    "code": 403,
                }
            },
        )
    )

    with pytest.raises(GatewayError) as exc_info:
        await _adapter_with_v1_endpoint().chat_completions(
            UnifiedLLMRequest(model="m1", messages=[ChatMessage(role="user", content="hello")]),
            KeyConfig(id="openrouter-main", key="secret"),
        )

    assert exc_info.value.error_class == ErrorClass.RATE_LIMIT


@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_keeps_permission_403_as_auth_forbidden() -> None:
    respx.post("https://openrouter.example/api/v1/chat/completions").mock(
        return_value=httpx.Response(403, json={"error": {"message": "Forbidden", "code": 403}})
    )

    with pytest.raises(GatewayError) as exc_info:
        await _adapter_with_v1_endpoint().chat_completions(
            UnifiedLLMRequest(model="m1", messages=[ChatMessage(role="user", content="hello")]),
            KeyConfig(id="openrouter-main", key="secret"),
        )

    assert exc_info.value.error_class == ErrorClass.AUTH_FORBIDDEN


@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_marks_openrouter_free_429_scope() -> None:
    respx.post("https://openrouter.example/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            429,
            json={"error": {"message": "Free model requests per day exceeded", "code": 429}},
            headers={"Retry-After": "60"},
        )
    )

    with pytest.raises(GatewayError) as exc_info:
        await _adapter_with_v1_endpoint().chat_completions(
            UnifiedLLMRequest(model="openrouter/free", messages=[ChatMessage(role="user", content="hello")]),
            KeyConfig(id="openrouter-main", key="secret"),
        )

    assert exc_info.value.error_class == ErrorClass.RATE_LIMIT
    assert exc_info.value.details["rate_limit_scope"] == "provider_free_tier"
    assert exc_info.value.details["upstream_headers"]["retry-after"] == "60"
