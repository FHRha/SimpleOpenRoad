"""Provider-agnostic OpenAI SSE stream validation and normalization."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.core.errors import ErrorClass, GatewayError


def _parse_sse_events(buffer: str) -> tuple[list[str], str]:
    normalized = buffer.replace("\r\n", "\n")
    parts = normalized.split("\n\n")
    return parts[:-1], parts[-1]


def _event_data(event: str) -> str | None:
    data_lines: list[str] = []
    for line in event.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    return "\n".join(data_lines)


def _choice_delta(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices", [])
    if not choices or not isinstance(choices[0], dict):
        return {}
    delta = choices[0].get("delta", {})
    return delta if isinstance(delta, dict) else {}


def _is_meaningful_delta(delta: dict[str, Any]) -> bool:
    content = delta.get("content")
    if isinstance(content, str) and content:
        return True
    if delta.get("tool_calls") or delta.get("function_call"):
        return True
    return False


def _role_chunk(model: str) -> bytes:
    chunk = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=True)}\n\n".encode("utf-8")


async def normalize_openai_stream(
    iterator: AsyncIterator[bytes],
    *,
    model: str,
    provider: str,
    key_id: str,
) -> AsyncIterator[bytes]:
    """Delay success until the stream contains assistant content or tool calls.

    Some providers can return a syntactically valid stream with only final/usage chunks.
    Agent clients such as Cline treat that as an invalid API response. Keeping this
    check provider-agnostic lets the router switch candidates before the HTTP stream
    is committed.
    """

    buffer = ""
    pending: list[bytes] = []
    role_seen = False
    meaningful_seen = False

    async for raw_chunk in iterator:
        text = raw_chunk.decode("utf-8", errors="replace")
        buffer += text
        events, buffer = _parse_sse_events(buffer)
        if not events:
            pending.append(raw_chunk)
            continue

        pending.clear()
        for event in events:
            event_bytes = f"{event}\n\n".encode("utf-8")
            data = _event_data(event)
            if data is None:
                pending.append(event_bytes)
                continue
            if data.strip() == "[DONE]":
                if not meaningful_seen:
                    raise GatewayError(
                        message="Provider stream ended without assistant content or tool calls",
                        error_class=ErrorClass.MALFORMED_RESPONSE,
                        status_code=502,
                        provider=provider,
                        key_id=key_id,
                    )
                yield event_bytes
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                pending.append(event_bytes)
                continue
            delta = _choice_delta(payload)
            if delta.get("role") == "assistant":
                role_seen = True
            if _is_meaningful_delta(delta):
                if not role_seen:
                    yield _role_chunk(model)
                    role_seen = True
                meaningful_seen = True
                for item in pending:
                    yield item
                pending.clear()
                yield event_bytes
            else:
                pending.append(event_bytes)

    if not meaningful_seen:
        raise GatewayError(
            message="Provider stream ended without assistant content or tool calls",
            error_class=ErrorClass.MALFORMED_RESPONSE,
            status_code=502,
            provider=provider,
            key_id=key_id,
        )
    for item in pending:
        yield item
