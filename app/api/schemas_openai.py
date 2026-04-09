"""Request/response schemas for OpenAI-compatible gateway endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatMessageSchema(BaseModel):
    role: str
    content: str


class ChatCompletionsRequestSchema(BaseModel):
    model: str
    messages: list[ChatMessageSchema] = Field(default_factory=list)
    input: Any | None = None
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResponsesRequestSchema(BaseModel):
    model: str
    input: Any
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
