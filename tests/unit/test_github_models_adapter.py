from __future__ import annotations

import httpx
import pytest
import respx

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.providers.github_models import GitHubModelsAdapter


def _adapter(endpoint: str = "https://models.github.ai") -> GitHubModelsAdapter:
    return GitHubModelsAdapter(config=ProviderConfig(endpoint=endpoint, keys=[]))


@pytest.mark.asyncio
@respx.mock
async def test_github_models_uses_inference_chat_endpoint() -> None:
    route = respx.post("https://models.github.ai/inference/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )
    )

    result = await _adapter().chat_completions(
        UnifiedLLMRequest(
            model="openai/gpt-4.1",
            messages=[ChatMessage(role="user", content="hello")],
        ),
        KeyConfig(id="github-main", key="github-token"),
    )

    assert result["choices"][0]["message"]["content"] == "ok"
    assert route.calls.last.request.headers["authorization"] == "Bearer github-token"
    assert route.calls.last.request.headers["accept"] == "application/vnd.github+json"
    assert route.calls.last.request.headers["x-github-api-version"] == "2026-03-10"


@pytest.mark.asyncio
@respx.mock
async def test_github_models_does_not_duplicate_inference_path() -> None:
    respx.post("https://models.github.ai/inference/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )
    )

    result = await _adapter("https://models.github.ai/inference").chat_completions(
        UnifiedLLMRequest(
            model="openai/gpt-4.1",
            messages=[ChatMessage(role="user", content="hello")],
        ),
        KeyConfig(id="github-main", key="github-token"),
    )

    assert result["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_github_models_lists_catalog_models() -> None:
    respx.get("https://models.github.ai/catalog/models").mock(
        return_value=httpx.Response(
            200,
            json={"models": [{"id": "openai/gpt-4.1"}, {"id": "microsoft/phi-4"}]},
        )
    )

    models = await _adapter().list_models(KeyConfig(id="github-main", key="github-token"))

    assert models == ["openai/gpt-4.1", "microsoft/phi-4"]


@pytest.mark.asyncio
async def test_github_models_rejects_responses_endpoint() -> None:
    with pytest.raises(GatewayError) as exc_info:
        await _adapter().responses(
            UnifiedLLMRequest(model="openai/gpt-4.1", input="hello"),
            KeyConfig(id="github-main", key="github-token"),
        )

    assert exc_info.value.error_class == ErrorClass.UNSUPPORTED_MODEL
