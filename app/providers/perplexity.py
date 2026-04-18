"""Perplexity adapter."""

from __future__ import annotations

from app.config.models import ProviderConfig
from app.providers.openai_compatible import OpenAICompatibleAdapter


class PerplexityAdapter(OpenAICompatibleAdapter):
    chat_completions_path = "/v1/sonar"

    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="perplexity", config=config)
