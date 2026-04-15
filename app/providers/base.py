"""Provider adapter contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.config.models import KeyConfig, ProviderConfig
from app.core.types import UnifiedLLMRequest


class ProviderAdapter(ABC):
    provider_name: str

    def __init__(self, provider_name: str, config: ProviderConfig):
        self.provider_name = provider_name
        self.config = config

    @abstractmethod
    async def chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        """Execute non-stream chat completion and return OpenAI-like payload."""

    @abstractmethod
    async def responses(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        """Execute OpenAI responses-style request and return OpenAI-like payload."""

    @abstractmethod
    async def stream_chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> AsyncIterator[bytes]:
        """Yield SSE lines for streaming chat completion."""

    @abstractmethod
    async def validate_key(self, key: KeyConfig) -> dict:
        """Return health result map with status/models/error details."""

    @abstractmethod
    async def list_models(self, key: KeyConfig) -> list[str]:
        """Return list of models available for this provider key."""

    async def list_model_records(self, key: KeyConfig) -> list[dict[str, Any]]:
        """Return provider model records with optional metadata."""
        return [{"id": model_id} for model_id in await self.list_models(key)]
