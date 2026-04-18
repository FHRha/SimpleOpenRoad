"""Novita AI adapter."""

from __future__ import annotations

from app.config.models import ProviderConfig
from app.providers.openai_compatible import OpenAICompatibleAdapter


class NovitaAdapter(OpenAICompatibleAdapter):
    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="novita", config=config)
