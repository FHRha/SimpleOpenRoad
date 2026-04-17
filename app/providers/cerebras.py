"""Cerebras Inference adapter."""

from __future__ import annotations

from app.config.models import ProviderConfig
from app.providers.openai_compatible import OpenAICompatibleAdapter


class CerebrasAdapter(OpenAICompatibleAdapter):
    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="cerebras", config=config)
