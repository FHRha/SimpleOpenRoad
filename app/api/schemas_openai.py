"""Request/response schemas for OpenAI-compatible gateway endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatMessageSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: Any = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ChatCompletionsRequestSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessageSchema] = Field(default_factory=list)
    input: Any | None = None
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stop: str | list[str] | None = None
    n: int | None = None
    user: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None
    parallel_tool_calls: bool | None = None
    response_format: dict[str, Any] | None = None
    stream_options: dict[str, Any] | None = None
    reasoning_effort: str | None = None
    modalities: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResponsesRequestSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    input: Any
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    max_output_tokens: int | None = None
    instructions: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None
    parallel_tool_calls: bool | None = None
    response_format: dict[str, Any] | None = None
    stream_options: dict[str, Any] | None = None
    reasoning_effort: str | None = None
    text: dict[str, Any] | None = None
    user: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
