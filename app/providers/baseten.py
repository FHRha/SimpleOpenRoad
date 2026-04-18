"""Baseten adapter."""

from __future__ import annotations

from app.config.models import KeyConfig, ProviderConfig
from app.providers.openai_compatible import OpenAICompatibleAdapter


class BasetenAdapter(OpenAICompatibleAdapter):
    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="baseten", config=config)

    def _build_headers(self, key: KeyConfig) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.auth_required:
            headers["Authorization"] = f"Api-Key {key.key}"
        headers.update(self.extra_headers)
        headers.update(self.config.headers)
        return headers
