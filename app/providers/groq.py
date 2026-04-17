"""Groq adapter."""

from __future__ import annotations

from app.config.models import ProviderConfig
from app.providers.openai_compatible import OpenAICompatibleAdapter


class GroqAdapter(OpenAICompatibleAdapter):
    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="groq", config=config)
