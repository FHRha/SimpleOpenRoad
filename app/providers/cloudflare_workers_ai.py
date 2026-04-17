"""Cloudflare Workers AI adapter."""

from __future__ import annotations

from typing import Any

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import UnifiedLLMRequest
from app.providers.openai_compatible import OpenAICompatibleAdapter


class CloudflareWorkersAIAdapter(OpenAICompatibleAdapter):
    chat_completions_path = "/v1/chat/completions"
    models_path = "/models/search?per_page=100"

    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="cloudflare", config=config)

    def _require_account_id(self, key: KeyConfig | None = None) -> str:
        account_id = ((key.account_id if key is not None else None) or self.config.account_id or "").strip()
        if not account_id:
            raise GatewayError(
                message="Cloudflare Workers AI requires account_id on the key or provider config",
                error_class=ErrorClass.AUTH_FORBIDDEN,
                status_code=403,
                provider=self.provider_name,
            )
        return account_id

    def _url(self, path: str, key: KeyConfig | None = None) -> str:
        endpoint = self.config.endpoint.rstrip("/")
        account_id = self._require_account_id(key)
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{endpoint}/accounts/{account_id}/ai{normalized_path}"

    async def responses(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        raise GatewayError(
            message="Cloudflare Workers AI does not expose an OpenAI Responses endpoint in this integration",
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
        items = data.get("result", []) if isinstance(data, dict) else []
        models: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            preferred_name = item.get("name")
            model_id = preferred_name or item.get("model") or item.get("id")
            if not model_id:
                continue
            record = dict(item)
            record["id"] = str(model_id)
            models.append(record)
        return models
