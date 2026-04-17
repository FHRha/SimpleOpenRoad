from __future__ import annotations

import httpx
import pytest
import respx

from app.config.models import KeyConfig, ProviderConfig
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.providers.cerebras import CerebrasAdapter


def _adapter(endpoint: str = "https://api.cerebras.ai/v1") -> CerebrasAdapter:
    return CerebrasAdapter(config=ProviderConfig(endpoint=endpoint, keys=[]))


@pytest.mark.asyncio
@respx.mock
async def test_cerebras_uses_openai_chat_endpoint() -> None:
    route = respx.post("https://api.cerebras.ai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )
    )

    result = await _adapter().chat_completions(
        UnifiedLLMRequest(
            model="gpt-oss-120b",
            messages=[ChatMessage(role="user", content="hello")],
        ),
        KeyConfig(id="cerebras-main", key="cerebras-token"),
    )

    assert result["choices"][0]["message"]["content"] == "ok"
    assert route.calls.last.request.headers["authorization"] == "Bearer cerebras-token"


@pytest.mark.asyncio
@respx.mock
async def test_cerebras_lists_models_from_standard_endpoint() -> None:
    respx.get("https://api.cerebras.ai/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "gpt-oss-120b"}]})
    )

    models = await _adapter().list_models(KeyConfig(id="cerebras-main", key="cerebras-token"))

    assert models == ["gpt-oss-120b"]
