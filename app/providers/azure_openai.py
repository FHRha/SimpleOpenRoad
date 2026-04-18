"""Azure OpenAI adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import UnifiedLLMRequest
from app.providers.openai_compatible import OpenAICompatibleAdapter


class AzureOpenAIAdapter(OpenAICompatibleAdapter):
    chat_completions_path = "/chat/completions"
    default_api_version = "2024-10-21"

    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="azure_openai", config=config)

    def _build_headers(self, key: KeyConfig) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.auth_required:
            headers["api-key"] = key.key
        headers.update(self.extra_headers)
        headers.update(self.config.headers)
        return headers

    def _request_payload(self, request: UnifiedLLMRequest) -> dict[str, Any]:
        payload = super()._request_payload(request)
        # Azure selects the deployed model from the URL path, not from a body model field.
        payload.pop("model", None)
        return payload

    def _url_for_deployment(self, path: str, deployment: str) -> str:
        endpoint = self.config.endpoint.rstrip("/")
        parsed = urlsplit(endpoint)
        normalized_path = path if path.startswith("/") else f"/{path}"
        deployment_id = quote(deployment, safe="")

        base_path = parsed.path.rstrip("/")
        if "{deployment}" in base_path:
            base_path = base_path.replace("{deployment}", deployment_id)
        elif "{model}" in base_path:
            base_path = base_path.replace("{model}", deployment_id)
        elif "/deployments/" not in base_path:
            base_path = f"{base_path}/openai/deployments/{deployment_id}"

        query = parsed.query or f"api-version={self.default_api_version}"
        return urlunsplit((parsed.scheme, parsed.netloc, f"{base_path}{normalized_path}", query, parsed.fragment))

    async def chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        payload = self._request_payload(request)
        return await self._post_deployment(self.chat_completions_path, payload, request.model, key)

    async def stream_chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> AsyncIterator[bytes]:
        payload = self._request_payload(request)
        payload["stream"] = True
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)

        async def iterator() -> AsyncIterator[bytes]:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST",
                        self._url_for_deployment(self.chat_completions_path, request.model),
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
                                details=self._error_details(response, body, payload),
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

    async def _post_deployment(self, path: str, payload: dict, deployment: str, key: KeyConfig) -> dict:
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    self._url_for_deployment(path, deployment),
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
                details=self._error_details(response, body, payload),
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

    async def list_model_records(self, key: KeyConfig) -> list[dict]:
        return []
