from __future__ import annotations

import httpx
import pytest
import respx

from app.config.models import KeyConfig, ProviderConfig
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.providers.together import TogetherAdapter


def _adapter(endpoint: str = "https://api.together.xyz/v1") -> TogetherAdapter:
    return TogetherAdapter(config=ProviderConfig(endpoint=endpoint, keys=[]))


@pytest.mark.asyncio
@respx.mock
async def test_together_uses_openai_chat_endpoint() -> None:
    route = respx.post("https://api.together.xyz/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )
    )

    result = await _adapter().chat_completions(
        UnifiedLLMRequest(
            model="openai/gpt-oss-20b",
            messages=[ChatMessage(role="user", content="hello")],
        ),
        KeyConfig(id="together-main", key="together-token"),
    )

    assert result["choices"][0]["message"]["content"] == "ok"
    assert route.calls.last.request.headers["authorization"] == "Bearer together-token"


@pytest.mark.asyncio
@respx.mock
async def test_together_lists_models_from_top_level_array() -> None:
    respx.get("https://api.together.xyz/v1/models").mock(
        return_value=httpx.Response(200, json=[{"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"}])
    )

    models = await _adapter().list_models(KeyConfig(id="together-main", key="together-token"))

    assert models == ["meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"]
