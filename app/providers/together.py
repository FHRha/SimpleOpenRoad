"""Together AI adapter."""

from __future__ import annotations

from app.config.models import ProviderConfig
from app.providers.openai_compatible import OpenAICompatibleAdapter


class TogetherAdapter(OpenAICompatibleAdapter):
    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="together", config=config)
