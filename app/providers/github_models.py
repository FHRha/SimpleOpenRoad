"""GitHub Models adapter."""

from __future__ import annotations

from typing import Any

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
        records = await self.list_model_records(key)
        return [str(item["id"]) for item in records if item.get("id")]

    async def list_model_records(self, key: KeyConfig) -> list[dict[str, Any]]:
        data = await self._get(self.models_path, key)
        items = self._extract_model_items(data)
        models: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id") or item.get("name") or item.get("model")
            if model_id:
                record = dict(item)
                record["id"] = str(model_id)
                models.append(record)
        return models

    @staticmethod
    def _extract_model_items(data: object) -> list[object]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            items = data.get("models") or data.get("data") or data.get("items") or []
            if isinstance(items, list):
                return items
            if isinstance(items, dict):
                nested = items.get("models") or items.get("data") or items.get("items") or []
                if isinstance(nested, list):
                    return nested
        return []
