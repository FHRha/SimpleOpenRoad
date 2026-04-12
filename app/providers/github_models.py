"""GitHub Models adapter."""

from __future__ import annotations

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import UnifiedLLMRequest
from app.providers.openai_compatible import OpenAICompatibleAdapter


class GitHubModelsAdapter(OpenAICompatibleAdapter):
    chat_completions_path = "/inference/chat/completions"
    models_path = "/catalog/models"

    def __init__(self, config: ProviderConfig):
        super().__init__(
            provider_name="github",
            config=config,
            extra_headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )

    def _url(self, path: str) -> str:
        endpoint = self.config.endpoint.rstrip("/")
        normalized_path = path if path.startswith("/") else f"/{path}"
        if endpoint.endswith("/inference") and normalized_path.startswith("/inference/"):
            normalized_path = normalized_path.removeprefix("/inference")
        return f"{endpoint}{normalized_path}"

    async def responses(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        raise GatewayError(
            message="GitHub Models does not expose an OpenAI Responses endpoint",
            error_class=ErrorClass.UNSUPPORTED_MODEL,
            status_code=400,
            provider=self.provider_name,
            key_id=key.id,
        )

    async def list_models(self, key: KeyConfig) -> list[str]:
        data = await self._get(self.models_path, key)
        if not isinstance(data, dict):
            return []

        items = data.get("models") or data.get("data") or data.get("items") or []
        models: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id") or item.get("name") or item.get("model")
            if model_id:
                models.append(str(model_id))
        return models
