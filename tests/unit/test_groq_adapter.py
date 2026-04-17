from __future__ import annotations

import httpx
import pytest
import respx

from app.config.models import KeyConfig, ProviderConfig
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.providers.groq import GroqAdapter


def _adapter(endpoint: str = "https://api.groq.com/openai/v1") -> GroqAdapter:
    return GroqAdapter(config=ProviderConfig(endpoint=endpoint, keys=[]))


@pytest.mark.asyncio
@respx.mock
async def test_groq_uses_openai_chat_endpoint() -> None:
    route = respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
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
        KeyConfig(id="groq-main", key="groq-token"),
    )

    assert result["choices"][0]["message"]["content"] == "ok"
    assert route.calls.last.request.headers["authorization"] == "Bearer groq-token"


@pytest.mark.asyncio
@respx.mock
async def test_groq_does_not_duplicate_v1_path() -> None:
    respx.get("https://api.groq.com/openai/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "openai/gpt-oss-20b"}]})
    )

    models = await _adapter("https://api.groq.com/openai/v1").list_models(
        KeyConfig(id="groq-main", key="groq-token")
    )

    assert models == ["openai/gpt-oss-20b"]
