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
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def _url(self, path: str, key: KeyConfig | None = None) -> str:
        endpoint = self.config.endpoint.rstrip("/")
        normalized_path = path if path.startswith("/") else f"/{path}"
        if endpoint.endswith("/inference"):
            if normalized_path.startswith("/inference/"):
                normalized_path = normalized_path.removeprefix("/inference")
            else:
                endpoint = endpoint.removesuffix("/inference")
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

    async def validate_key(self, key: KeyConfig) -> dict:
        try:
            data = await self._get(self.models_path, key)
            models = self._model_records_from_catalog(data)
            if not models:
                return {
                    "status": "degraded",
                    "models": [],
                    "error_code": "no_models_discovered",
                    "error_message": (
                        "GitHub catalog returned no model records; "
                        f"url={self._url(self.models_path)}; response_shape={self._response_shape(data)}"
                    ),
                }
            return {
                "status": "valid",
                "models": [str(item["id"]) for item in models if item.get("id")],
                "error_code": None,
                "error_message": None,
            }
        except GatewayError as exc:
            status = "invalid" if exc.error_class in (ErrorClass.AUTH_INVALID, ErrorClass.AUTH_FORBIDDEN) else "degraded"
            return {
                "status": status,
                "models": [],
                "error_code": exc.error_class.value,
                "error_message": exc.message,
            }
        except Exception as exc:  # noqa: BLE001 - validation must return diagnostics instead of crashing CLI.
            return {
                "status": "degraded",
                "models": [],
                "error_code": "validation_exception",
                "error_message": f"GitHub validation failed: {type(exc).__name__}: {exc}",
            }

    async def list_model_records(self, key: KeyConfig) -> list[dict[str, Any]]:
        data = await self._get(self.models_path, key)
        return self._model_records_from_catalog(data)

    def _model_records_from_catalog(self, data: object) -> list[dict[str, Any]]:
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

    @staticmethod
    def _response_shape(data: object) -> str:
        if isinstance(data, list):
            sample_type = type(data[0]).__name__ if data else "empty"
            return f"list(len={len(data)}, first={sample_type})"
        if isinstance(data, dict):
            keys = ", ".join(sorted(str(key) for key in data.keys())[:8])
            return f"dict(keys=[{keys}])"
        return type(data).__name__
