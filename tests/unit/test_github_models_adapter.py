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


def _adapter_with_headers(headers: dict[str, str]) -> GitHubModelsAdapter:
    return GitHubModelsAdapter(config=ProviderConfig(endpoint="https://models.github.ai", headers=headers, keys=[]))


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
    assert route.calls.last.request.headers["x-github-api-version"] == "2022-11-28"


@pytest.mark.asyncio
@respx.mock
async def test_github_models_config_headers_override_adapter_defaults() -> None:
    route = respx.get("https://models.github.ai/catalog/models").mock(
        return_value=httpx.Response(200, json=[{"id": "openai/gpt-4.1-mini"}])
    )

    await _adapter_with_headers({"X-GitHub-Api-Version": "2022-custom"}).list_models(
        KeyConfig(id="github-main", key="github-token")
    )

    assert route.calls.last.request.headers["x-github-api-version"] == "2022-custom"


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
async def test_github_models_catalog_uses_root_endpoint_when_configured_with_inference_path() -> None:
    respx.get("https://models.github.ai/catalog/models").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "openai/gpt-4.1-mini",
                    "limits": {"max_input_tokens": 1048576, "max_output_tokens": 32768},
                }
            ],
        )
    )

    records = await _adapter("https://models.github.ai/inference").list_model_records(
        KeyConfig(id="github-main", key="github-token")
    )

    assert records == [
        {
            "id": "openai/gpt-4.1-mini",
            "limits": {"max_input_tokens": 1048576, "max_output_tokens": 32768},
        }
    ]


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
@respx.mock
async def test_github_models_lists_catalog_models_when_api_returns_root_array() -> None:
    respx.get("https://models.github.ai/catalog/models").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "openai/gpt-4.1"},
                {"name": "azureml/Phi-4-reasoning"},
            ],
        )
    )

    models = await _adapter().list_models(KeyConfig(id="github-main", key="github-token"))

    assert models == ["openai/gpt-4.1", "azureml/Phi-4-reasoning"]


@pytest.mark.asyncio
@respx.mock
async def test_github_models_validate_reports_empty_catalog_shape() -> None:
    respx.get("https://models.github.ai/catalog/models").mock(
        return_value=httpx.Response(200, json={"unexpected": []})
    )

    result = await _adapter().validate_key(KeyConfig(id="github-main", key="github-token"))

    assert result["status"] == "degraded"
    assert result["models"] == []
    assert result["error_code"] == "no_models_discovered"
    assert "response_shape=dict(keys=[unexpected])" in result["error_message"]


@pytest.mark.asyncio
async def test_github_models_rejects_responses_endpoint() -> None:
    with pytest.raises(GatewayError) as exc_info:
        await _adapter().responses(
            UnifiedLLMRequest(model="openai/gpt-4.1", input="hello"),
            KeyConfig(id="github-main", key="github-token"),
        )

    assert exc_info.value.error_class == ErrorClass.UNSUPPORTED_MODEL
