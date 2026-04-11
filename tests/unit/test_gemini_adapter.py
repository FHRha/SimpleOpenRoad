from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import GatewayError
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.providers.gemini import GeminiAdapter


def _adapter() -> GeminiAdapter:
    return GeminiAdapter(
        ProviderConfig(
            endpoint="https://generativelanguage.googleapis.com",
            keys=[],
        )
    )


def _request(stream: bool = True) -> UnifiedLLMRequest:
    return UnifiedLLMRequest(
        model="gemini-2.5-flash",
        messages=[ChatMessage(role="user", content="hello")],
        stream=stream,
    )


@pytest.mark.asyncio
@respx.mock
async def test_gemini_stream_emits_openai_role_and_content_chunks() -> None:
    body = "\n".join(
        [
            'data: {"candidates":[{"content":{"parts":[{"text":"hi"}]}}]}',
            "",
        ]
    )
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent"
    ).mock(return_value=httpx.Response(200, text=body))

    chunks = []
    iterator = await _adapter().stream_chat_completions(_request(stream=True), KeyConfig(id="gemini-main", key="secret"))
    async for chunk in iterator:
        chunks.append(chunk.decode("utf-8"))

    assert any('"delta": {"role": "assistant"}' in chunk for chunk in chunks)
    assert any('"delta": {"content": "hi"}' in chunk for chunk in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
@respx.mock
async def test_gemini_stream_empty_text_raises_before_successful_done() -> None:
    body = "\n".join(
        [
            'data: {"candidates":[{"finishReason":"SAFETY","content":{"parts":[]}}]}',
            "",
        ]
    )
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent"
    ).mock(return_value=httpx.Response(200, text=body))

    iterator = await _adapter().stream_chat_completions(_request(stream=True), KeyConfig(id="gemini-main", key="secret"))

    with pytest.raises(GatewayError, match="no assistant text"):
        async for _ in iterator:
            pass


def test_gemini_non_stream_empty_text_raises_gateway_error() -> None:
    with pytest.raises(GatewayError, match="no assistant text"):
        _adapter()._map_non_stream_to_openai(  # noqa: SLF001
            {
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {"parts": []},
                    }
                ],
                "usageMetadata": {},
            },
            _request(stream=False),
        )


def test_gemini_non_stream_text_maps_to_openai_payload() -> None:
    payload = _adapter()._map_non_stream_to_openai(  # noqa: SLF001
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "ok"}]},
                }
            ],
            "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1},
        },
        _request(stream=False),
    )

    assert json.dumps(payload)
    assert payload["choices"][0]["message"]["content"] == "ok"
    assert payload["usage"]["total_tokens"] == 3
