"""Together AI adapter."""

from __future__ import annotations

from typing import Any

from app.config.models import KeyConfig, ProviderConfig
from app.providers.openai_compatible import OpenAICompatibleAdapter


class TogetherAdapter(OpenAICompatibleAdapter):
    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="together", config=config)

    async def list_model_records(self, key: KeyConfig) -> list[dict[str, Any]]:
        data = await self._get(self.models_path, key)
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("data", [])
        else:
            items = []

        models: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict) and "id" in item:
                models.append(dict(item))
        return models
