"""Provider-agnostic validation for successful OpenAI-compatible payloads."""

from __future__ import annotations

from typing import Any

from app.core.errors import ErrorClass, GatewayError


def _has_text(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, list):
        return any(_has_text(item) for item in value)
    if isinstance(value, dict):
        return any(_has_text(value.get(key)) for key in ("text", "content", "input_text", "output_text"))
    return False


def _has_tool_call(value: Any) -> bool:
    if isinstance(value, list):
        return bool(value)
    return bool(value)


def validate_chat_completion_payload(payload: dict[str, Any], *, provider: str, key_id: str) -> None:
    choices = payload.get("choices", [])
    if not choices or not isinstance(choices[0], dict):
        raise GatewayError(
            message="Provider returned chat completion without choices",
            error_class=ErrorClass.MALFORMED_RESPONSE,
            status_code=502,
            provider=provider,
            key_id=key_id,
        )

    choice = choices[0]
    message = choice.get("message", {})
    if isinstance(message, dict):
        if _has_text(message.get("content")):
            return
        if _has_tool_call(message.get("tool_calls")) or _has_tool_call(message.get("function_call")):
            return

    finish_reason = choice.get("finish_reason")
    suffix = f" finish_reason={finish_reason}" if finish_reason else ""
    raise GatewayError(
        message=f"Provider returned chat completion without assistant content or tool calls.{suffix}",
        error_class=ErrorClass.MALFORMED_RESPONSE,
        status_code=502,
        provider=provider,
        key_id=key_id,
    )


def validate_responses_payload(payload: dict[str, Any], *, provider: str, key_id: str) -> None:
    if _has_text(payload.get("output_text")):
        return

    output = payload.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"function_call", "tool_call"}:
                return
            if _has_text(item.get("content")):
                return

    raise GatewayError(
        message="Provider returned response without output text or tool calls",
        error_class=ErrorClass.MALFORMED_RESPONSE,
        status_code=502,
        provider=provider,
        key_id=key_id,
    )
