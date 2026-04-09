"""Reusable transport for OpenAI-compatible provider endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import UnifiedLLMRequest
from app.providers.base import ProviderAdapter


class OpenAICompatibleAdapter(ProviderAdapter):
    def __init__(self, provider_name: str, config: ProviderConfig, extra_headers: dict[str, str] | None = None):
        super().__init__(provider_name=provider_name, config=config)
        self.extra_headers = extra_headers or {}

    def _build_headers(self, key: KeyConfig) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {key.key}",
            "Content-Type": "application/json",
        }
        headers.update(self.config.headers)
        headers.update(self.extra_headers)
        return headers

    def _request_payload(self, request: UnifiedLLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "stream": request.stream,
        }
        if request.messages:
            payload["messages"] = [m.model_dump() for m in request.messages]
        if request.input is not None:
            payload["input"] = request.input
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        return payload

    async def _post(self, path: str, payload: dict[str, Any], key: KeyConfig) -> dict:
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.config.endpoint.rstrip('/')}{path}",
                    headers=self._build_headers(key),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise GatewayError(
                message=f"Timeout contacting {self.provider_name}",
                error_class=ErrorClass.NETWORK_TIMEOUT,
                status_code=504,
                provider=self.provider_name,
                key_id=key.id,
            ) from exc
        except httpx.HTTPError as exc:
            raise GatewayError(
                message=f"Network error contacting {self.provider_name}: {exc}",
                error_class=ErrorClass.PROVIDER_UNAVAILABLE,
                status_code=503,
                provider=self.provider_name,
                key_id=key.id,
            ) from exc

        if response.status_code >= 400:
            error_class = ErrorClass.UNKNOWN
            if response.status_code == 401:
                error_class = ErrorClass.AUTH_INVALID
            elif response.status_code == 403:
                error_class = ErrorClass.AUTH_FORBIDDEN
            elif response.status_code == 429:
                error_class = ErrorClass.RATE_LIMIT
            elif 500 <= response.status_code < 600:
                error_class = ErrorClass.PROVIDER_UNAVAILABLE
            body = response.text[:1000]
            raise GatewayError(
                message=f"Provider {self.provider_name} returned {response.status_code}: {body}",
                error_class=error_class,
                status_code=response.status_code,
                provider=self.provider_name,
                key_id=key.id,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise GatewayError(
                message=f"Malformed JSON from {self.provider_name}",
                error_class=ErrorClass.MALFORMED_RESPONSE,
                status_code=502,
                provider=self.provider_name,
                key_id=key.id,
            ) from exc

    async def chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        payload = self._request_payload(request)
        return await self._post("/v1/chat/completions", payload, key)

    async def responses(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        payload = self._request_payload(request)
        return await self._post("/v1/responses", payload, key)

    async def stream_chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> AsyncIterator[bytes]:
        payload = self._request_payload(request)
        payload["stream"] = True
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)

        async def iterator() -> AsyncIterator[bytes]:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST",
                        f"{self.config.endpoint.rstrip('/')}/v1/chat/completions",
                        headers=self._build_headers(key),
                        json=payload,
                    ) as response:
                        if response.status_code >= 400:
                            body = (await response.aread()).decode("utf-8", errors="replace")[:1000]
                            error_class = ErrorClass.UNKNOWN
                            if response.status_code == 401:
                                error_class = ErrorClass.AUTH_INVALID
                            elif response.status_code == 403:
                                error_class = ErrorClass.AUTH_FORBIDDEN
                            elif response.status_code == 429:
                                error_class = ErrorClass.RATE_LIMIT
                            elif 500 <= response.status_code < 600:
                                error_class = ErrorClass.PROVIDER_UNAVAILABLE
                            raise GatewayError(
                                message=(
                                    f"Provider {self.provider_name} stream error {response.status_code}: {body}"
                                ),
                                error_class=error_class,
                                status_code=response.status_code,
                                provider=self.provider_name,
                                key_id=key.id,
                            )
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            yield (line + "\n").encode("utf-8")
            except httpx.TimeoutException as exc:
                raise GatewayError(
                    message=f"Timeout contacting {self.provider_name}",
                    error_class=ErrorClass.NETWORK_TIMEOUT,
                    status_code=504,
                    provider=self.provider_name,
                    key_id=key.id,
                ) from exc
            except httpx.HTTPError as exc:
                raise GatewayError(
                    message=f"Network error contacting {self.provider_name}: {exc}",
                    error_class=ErrorClass.PROVIDER_UNAVAILABLE,
                    status_code=503,
                    provider=self.provider_name,
                    key_id=key.id,
                ) from exc

        return iterator()

    async def validate_key(self, key: KeyConfig) -> dict:
        try:
            models = await self.list_models(key)
            return {
                "status": "valid" if models else "degraded",
                "models": models,
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

    async def list_models(self, key: KeyConfig) -> list[str]:
        data = await self._post("/v1/models", {}, key)
        items = data.get("data", []) if isinstance(data, dict) else []
        models: list[str] = []
        for item in items:
            if isinstance(item, dict) and "id" in item:
                models.append(str(item["id"]))
        return models
