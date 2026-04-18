"""Z.AI OpenAI-compatible API adapter."""

from __future__ import annotations

from app.config.models import ProviderConfig
from app.providers.openai_compatible import OpenAICompatibleAdapter


class ZAIAdapter(OpenAICompatibleAdapter):
    chat_completions_path = "/chat/completions"
    responses_path = "/responses"
    models_path = "/models"

    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="zai", config=config)
