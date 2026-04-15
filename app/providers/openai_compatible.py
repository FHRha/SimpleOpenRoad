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
    chat_completions_path = "/v1/chat/completions"
    responses_path = "/v1/responses"
    models_path = "/v1/models"

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

    def _url(self, path: str) -> str:
        endpoint = self.config.endpoint.rstrip("/")
        normalized_path = path if path.startswith("/") else f"/{path}"
        if endpoint.endswith("/v1") and normalized_path.startswith("/v1/"):
            normalized_path = normalized_path[3:]
        return f"{endpoint}{normalized_path}"

    def _request_payload(self, request: UnifiedLLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "stream": request.stream,
        }
        payload.update(request.extra_body)
        if request.messages:
            payload["messages"] = [m.model_dump(exclude_none=True) for m in request.messages]
        if request.input is not None:
            payload["input"] = request.input
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        return payload

    @staticmethod
    def _classify_error_response(status_code: int, body: str) -> ErrorClass:
        body_lower = body.lower()
        if status_code == 401:
            return ErrorClass.AUTH_INVALID
        if status_code == 403:
            quota_markers = (
                "limit exceeded",
                "rate limit",
                "quota",
                "insufficient credits",
                "insufficient balance",
                "billing",
                "credits",
            )
            if any(marker in body_lower for marker in quota_markers):
                return ErrorClass.RATE_LIMIT
            return ErrorClass.AUTH_FORBIDDEN
        if status_code == 429:
            return ErrorClass.RATE_LIMIT
        if 500 <= status_code < 600:
            return ErrorClass.PROVIDER_UNAVAILABLE
        return ErrorClass.UNKNOWN

    async def _post(self, path: str, payload: dict[str, Any], key: KeyConfig) -> dict:
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    self._url(path),
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
            body = response.text[:1000]
            error_class = self._classify_error_response(response.status_code, body)
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
        return await self._post(self.chat_completions_path, payload, key)

    async def responses(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        payload = self._request_payload(request)
        return await self._post(self.responses_path, payload, key)

    async def stream_chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> AsyncIterator[bytes]:
        payload = self._request_payload(request)
        payload["stream"] = True
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)

        async def iterator() -> AsyncIterator[bytes]:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST",
                        self._url(self.chat_completions_path),
                        headers=self._build_headers(key),
                        json=payload,
                    ) as response:
                        if response.status_code >= 400:
                            body = (await response.aread()).decode("utf-8", errors="replace")[:1000]
                            error_class = self._classify_error_response(response.status_code, body)
                            raise GatewayError(
                                message=(
                                    f"Provider {self.provider_name} stream error {response.status_code}: {body}"
                                ),
                                error_class=error_class,
                                status_code=response.status_code,
                                provider=self.provider_name,
                                key_id=key.id,
                            )
                        event_lines: list[str] = []
                        async for line in response.aiter_lines():
                            if line:
                                event_lines.append(line)
                                continue
                            if event_lines:
                                yield ("\n".join(event_lines) + "\n\n").encode("utf-8")
                                event_lines.clear()
                        if event_lines:
                            yield ("\n".join(event_lines) + "\n\n").encode("utf-8")
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

    async def _get(self, path: str, key: KeyConfig) -> dict:
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    self._url(path),
                    headers=self._build_headers(key),
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
            body = response.text[:1000]
            error_class = self._classify_error_response(response.status_code, body)
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

    async def list_models(self, key: KeyConfig) -> list[str]:
        records = await self.list_model_records(key)
        return [str(item["id"]) for item in records if item.get("id")]

    async def list_model_records(self, key: KeyConfig) -> list[dict[str, Any]]:
        data = await self._get(self.models_path, key)
        items = data.get("data", []) if isinstance(data, dict) else []
        models: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict) and "id" in item:
                models.append(dict(item))
        return models
