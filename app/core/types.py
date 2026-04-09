"""Strongly-typed core DTOs used by adapters, router and services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.errors import ErrorClass


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class UnifiedLLMRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(default_factory=list)
    input: Any | None = None
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class UnifiedLLMResponse(BaseModel):
    id: str
    object: str
    created: int
    model: str
    provider: str
    key_id: str
    output: dict[str, Any]
    usage: LLMUsage = Field(default_factory=LLMUsage)


class RouteCandidate(BaseModel):
    provider: str
    model: str


@dataclass(slots=True)
class RequestContext:
    request_id: str
    route_alias: str | None
    stream: bool
    timeout_seconds: float | None
    profile: str | None = None


@dataclass(slots=True)
class RouterAttempt:
    attempt_index: int
    provider: str
    key_id: str
    model: str
    success: bool
    latency_ms: float
    error_class: ErrorClass | None = None
    error_message: str | None = None


@dataclass(slots=True)
class RouterDecision:
    request_id: str
    requested_model: str
    resolved_alias: str | None
    selected_provider: str | None
    selected_key_id: str | None
    attempts: list[RouterAttempt] = field(default_factory=list)


@dataclass(slots=True)
class HealthCheckResult:
    provider: str
    key_id: str
    status: str
    latency_ms: float | None
    models: list[str]
    error_code: str | None
    error_message: str | None
    checked_at: datetime


@dataclass(slots=True)
class FailoverResult:
    success: bool
    final_error_class: ErrorClass | None
    final_error_message: str | None
    attempts: list[RouterAttempt]
