from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from app.core.errors import GatewayError
from app.router.stream_normalizer import normalize_openai_stream


async def _iter_chunks(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_stream_normalizer_injects_role_before_content() -> None:
    content_chunk = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m1",
        "choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}],
    }
    iterator = normalize_openai_stream(
        _iter_chunks(
            [
                f"data: {json.dumps(content_chunk)}\n\n".encode("utf-8"),
                b"data: [DONE]\n\n",
            ]
        ),
        model="m1",
        provider="p1",
        key_id="p1-k",
    )

    chunks = [chunk.decode("utf-8") async for chunk in iterator]

    assert '"role": "assistant"' in chunks[0]
    assert '"content": "hello"' in chunks[1]
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_stream_normalizer_rejects_done_only_stream() -> None:
    iterator = normalize_openai_stream(
        _iter_chunks([b"data: [DONE]\n\n"]),
        model="m1",
        provider="p1",
        key_id="p1-k",
    )

    with pytest.raises(GatewayError, match="without assistant content"):
        async for _ in iterator:
            pass
