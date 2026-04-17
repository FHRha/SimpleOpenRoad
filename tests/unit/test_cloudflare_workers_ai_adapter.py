from __future__ import annotations

import httpx
import pytest
import respx

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.providers.cloudflare_workers_ai import CloudflareWorkersAIAdapter


def _adapter(
    endpoint: str = "https://api.cloudflare.com/client/v4",
    account_id: str = "acc-123",
) -> CloudflareWorkersAIAdapter:
    return CloudflareWorkersAIAdapter(config=ProviderConfig(endpoint=endpoint, account_id=account_id, keys=[]))


@pytest.mark.asyncio
@respx.mock
async def test_cloudflare_uses_account_scoped_openai_chat_endpoint() -> None:
    route = respx.post(
        "https://api.cloudflare.com/client/v4/accounts/acc-123/ai/v1/chat/completions"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )
    )

    result = await _adapter().chat_completions(
        UnifiedLLMRequest(
            model="@cf/meta/llama-3.1-8b-instruct",
            messages=[ChatMessage(role="user", content="hello")],
        ),
        KeyConfig(id="cloudflare-main", key="cf-token"),
    )

    assert result["choices"][0]["message"]["content"] == "ok"
    assert route.calls.last.request.headers["authorization"] == "Bearer cf-token"


@pytest.mark.asyncio
@respx.mock
async def test_cloudflare_lists_models_from_model_search_endpoint() -> None:
    respx.get(
        "https://api.cloudflare.com/client/v4/accounts/acc-123/ai/models/search?per_page=100"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"result": [{"id": "@cf/meta/llama-3.1-8b-instruct"}, {"name": "@cf/openai/gpt-oss-20b"}]},
        )
    )

    models = await _adapter().list_models(KeyConfig(id="cloudflare-main", key="cf-token"))

    assert models == ["@cf/meta/llama-3.1-8b-instruct", "@cf/openai/gpt-oss-20b"]


@pytest.mark.asyncio
async def test_cloudflare_requires_account_id() -> None:
    adapter = _adapter(account_id="")

    with pytest.raises(GatewayError) as exc_info:
        await adapter.list_models(KeyConfig(id="cloudflare-main", key="cf-token"))

    assert exc_info.value.error_class == ErrorClass.AUTH_FORBIDDEN


@pytest.mark.asyncio
async def test_cloudflare_rejects_responses_endpoint() -> None:
    with pytest.raises(GatewayError) as exc_info:
        await _adapter().responses(
            UnifiedLLMRequest(model="@cf/meta/llama-3.1-8b-instruct", input="hello"),
            KeyConfig(id="cloudflare-main", key="cf-token"),
        )

    assert exc_info.value.error_class == ErrorClass.UNSUPPORTED_MODEL
