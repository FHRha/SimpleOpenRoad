"""Experimental Gemini CLI OAuth adapter using the Code Assist backend."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import UnifiedLLMRequest, stringify_content
from app.credentials.google_code_assist import (
    CODE_ASSIST_ENDPOINT,
    CODE_ASSIST_VERSION,
    credential_path,
    ensure_access_token,
    load_credentials,
    parse_credential_ref,
    save_credentials,
    setup_user,
)
from app.providers.base import ProviderAdapter


DEFAULT_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
]


class GoogleCodeAssistAdapter(ProviderAdapter):
    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="google_code_assist", config=config)

    def _credential_file(self, key: KeyConfig) -> Path:
        profile, explicit_path = parse_credential_ref(key.key)
        return explicit_path or credential_path(profile)

    def _load_ready_credentials(self, key: KeyConfig) -> dict[str, Any]:
        path = self._credential_file(key)
        if not path.exists():
            raise GatewayError(
                message=(
                    "Gemini CLI OAuth credentials are missing. "
                    "Run: sor providers connect google"
                ),
                error_class=ErrorClass.AUTH_INVALID,
                status_code=401,
                provider=self.provider_name,
                key_id=key.id,
            )
        try:
            credentials = load_credentials(path)
            credentials = ensure_access_token(credentials)
            if not credentials.get("project_id"):
                credentials = setup_user(credentials)
            save_credentials(path, credentials)
            return credentials
        except httpx.HTTPStatusError as exc:
            raise self._gateway_error_from_response(exc.response, key, "Google OAuth refresh failed") from exc
        except Exception as exc:  # noqa: BLE001
            raise GatewayError(
                message=f"Gemini CLI OAuth credentials could not be loaded: {exc}",
                error_class=ErrorClass.AUTH_INVALID,
                status_code=401,
                provider=self.provider_name,
                key_id=key.id,
            ) from exc

    def _method_url(self, method: str) -> str:
        endpoint = (self.config.endpoint or CODE_ASSIST_ENDPOINT).rstrip("/")
        return f"{endpoint}/{CODE_ASSIST_VERSION}:{method}"

    def _headers(self, credentials: dict[str, Any]) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {credentials['access_token']}",
            "Content-Type": "application/json",
        }
        headers.update(self.config.headers)
        return headers

    @staticmethod
    def _to_code_assist_payload(request: UnifiedLLMRequest, project_id: str | None) -> dict[str, Any]:
        contents: list[dict[str, Any]] = []
        system_parts: list[str] = []
        for msg in request.messages:
            if msg.role in {"system", "developer"}:
                text = stringify_content(msg.content)
                if text:
                    system_parts.append(text)
                continue
            role = "model" if msg.role == "assistant" else "user"
            text = stringify_content(msg.content)
            if msg.role in {"tool", "function"} and msg.name:
                text = f"{msg.name} result:\n{text}"
            contents.append({"role": role, "parts": [{"text": text}]})

        if request.input is not None:
            contents.append({"role": "user", "parts": [{"text": stringify_content(request.input)}]})

        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})

        instructions = stringify_content(request.extra_body.get("instructions"))
        if instructions:
            system_parts.append(instructions)

        generation_config: dict[str, Any] = {}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.max_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_tokens
        if request.extra_body.get("top_p") is not None:
            generation_config["topP"] = request.extra_body["top_p"]
        if request.extra_body.get("stop") is not None:
            stop = request.extra_body["stop"]
            generation_config["stopSequences"] = stop if isinstance(stop, list) else [stop]

        vertex_request: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config or None,
        }
        if system_parts:
            vertex_request["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(part for part in system_parts if part)}]
            }

        return {
            "model": request.model,
            "project": project_id,
            "user_prompt_id": uuid.uuid4().hex,
            "request": {k: v for k, v in vertex_request.items() if v is not None},
        }

    @staticmethod
    def _extract_response(data: dict[str, Any]) -> dict[str, Any]:
        response = data.get("response") if isinstance(data, dict) else None
        return response if isinstance(response, dict) else {}

    @staticmethod
    def _extract_text(response: dict[str, Any]) -> tuple[str, str | None]:
        candidates = response.get("candidates", []) if isinstance(response, dict) else []
        text = ""
        finish_reason = None
        if candidates:
            candidate = candidates[0]
            finish_reason = candidate.get("finishReason")
            content = candidate.get("content", {})
            parts = content.get("parts", []) if isinstance(content, dict) else []
            text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        return text, finish_reason

    def _map_non_stream_to_openai(self, data: dict[str, Any], request: UnifiedLLMRequest) -> dict[str, Any]:
        response = self._extract_response(data)
        text, finish_reason = self._extract_text(response)
        if not text:
            reason_suffix = f" finishReason={finish_reason}" if finish_reason else ""
            raise GatewayError(
                message=f"Gemini CLI OAuth returned no assistant text.{reason_suffix}",
                error_class=ErrorClass.MALFORMED_RESPONSE,
                status_code=502,
                provider=self.provider_name,
            )

        usage_meta = response.get("usageMetadata", {}) if isinstance(response, dict) else {}
        prompt_tokens = int(usage_meta.get("promptTokenCount", 0) or 0)
        completion_tokens = int(usage_meta.get("candidatesTokenCount", 0) or 0)
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    async def _post(self, method: str, payload: dict[str, Any], key: KeyConfig) -> dict[str, Any]:
        credentials = self._load_ready_credentials(key)
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    self._method_url(method),
                    headers=self._headers(credentials),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise GatewayError(
                message="Timeout contacting Gemini CLI OAuth backend",
                error_class=ErrorClass.NETWORK_TIMEOUT,
                status_code=504,
                provider=self.provider_name,
                key_id=key.id,
            ) from exc
        except httpx.HTTPError as exc:
            raise GatewayError(
                message=f"Network error contacting Gemini CLI OAuth backend: {exc}",
                error_class=ErrorClass.PROVIDER_UNAVAILABLE,
                status_code=503,
                provider=self.provider_name,
                key_id=key.id,
            ) from exc
        if response.status_code >= 400:
            raise self._gateway_error_from_response(response, key, "Gemini CLI OAuth backend returned an error")
        return response.json()

    def _gateway_error_from_response(self, response: httpx.Response, key: KeyConfig, prefix: str) -> GatewayError:
        body = response.text[:1000]
        error_class = ErrorClass.UNKNOWN
        if response.status_code == 401:
            error_class = ErrorClass.AUTH_INVALID
        elif response.status_code == 403:
            error_class = ErrorClass.AUTH_FORBIDDEN
        elif response.status_code == 429:
            error_class = ErrorClass.RATE_LIMIT
        elif response.status_code == 400 and "model" in body.lower():
            error_class = ErrorClass.UNSUPPORTED_MODEL
        elif 500 <= response.status_code < 600:
            error_class = ErrorClass.PROVIDER_UNAVAILABLE
        return GatewayError(
            message=f"{prefix} {response.status_code}: {body}",
            error_class=error_class,
            status_code=response.status_code,
            provider=self.provider_name,
            key_id=key.id,
        )

    async def chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        credentials = self._load_ready_credentials(key)
        payload = self._to_code_assist_payload(request, str(credentials.get("project_id") or ""))
        data = await self._post("generateContent", payload, key)
        return self._map_non_stream_to_openai(data, request)

    async def responses(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        chat_payload = await self.chat_completions(request, key)
        text = ""
        choices = chat_payload.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content", "")
        return {
            "id": f"resp_{uuid.uuid4().hex}",
            "object": "response",
            "created": chat_payload.get("created", int(time.time())),
            "model": request.model,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
            "usage": chat_payload.get("usage", {}),
        }

    async def stream_chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> AsyncIterator[bytes]:
        credentials = self._load_ready_credentials(key)
        payload = self._to_code_assist_payload(request, str(credentials.get("project_id") or ""))
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)

        async def iterator() -> AsyncIterator[bytes]:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST",
                        self._method_url("streamGenerateContent"),
                        params={"alt": "sse"},
                        headers=self._headers(credentials),
                        json=payload,
                    ) as response:
                        if response.status_code >= 400:
                            body = (await response.aread()).decode("utf-8", errors="replace")[:1000]
                            raise self._gateway_error_from_response(
                                response,
                                key,
                                f"Gemini CLI OAuth stream error: {body}",
                            )

                        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
                        emitted_role = False
                        emitted_text = False
                        buffered: list[str] = []
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                buffered.append(line[6:].strip())
                                continue
                            if line:
                                continue
                            if not buffered:
                                continue
                            try:
                                payload_obj = json.loads("\n".join(buffered))
                            except json.JSONDecodeError:
                                buffered = []
                                continue
                            buffered = []
                            text, _finish_reason = self._extract_text(self._extract_response(payload_obj))
                            if not text:
                                continue
                            if not emitted_role:
                                role_chunk = {
                                    "id": chunk_id,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": request.model,
                                    "choices": [
                                        {
                                            "index": 0,
                                            "delta": {"role": "assistant"},
                                            "finish_reason": None,
                                        }
                                    ],
                                }
                                yield f"data: {json.dumps(role_chunk, ensure_ascii=True)}\n\n".encode("utf-8")
                                emitted_role = True
                            chunk = {
                                "id": chunk_id,
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": request.model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": text},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(chunk, ensure_ascii=True)}\n\n".encode("utf-8")
                            emitted_text = True

                        if not emitted_text:
                            raise GatewayError(
                                message="Gemini CLI OAuth stream returned no assistant text.",
                                error_class=ErrorClass.MALFORMED_RESPONSE,
                                status_code=502,
                                provider=self.provider_name,
                                key_id=key.id,
                            )

                        final_chunk = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": request.model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        }
                        yield f"data: {json.dumps(final_chunk, ensure_ascii=True)}\n\n".encode("utf-8")
                        yield b"data: [DONE]\n\n"
            except httpx.TimeoutException as exc:
                raise GatewayError(
                    message="Timeout contacting Gemini CLI OAuth backend",
                    error_class=ErrorClass.NETWORK_TIMEOUT,
                    status_code=504,
                    provider=self.provider_name,
                    key_id=key.id,
                ) from exc
            except httpx.HTTPError as exc:
                raise GatewayError(
                    message=f"Network error contacting Gemini CLI OAuth backend: {exc}",
                    error_class=ErrorClass.PROVIDER_UNAVAILABLE,
                    status_code=503,
                    provider=self.provider_name,
                    key_id=key.id,
                ) from exc

        return iterator()

    async def validate_key(self, key: KeyConfig) -> dict:
        try:
            credentials = self._load_ready_credentials(key)
            models = await self.list_models(key)
            return {
                "status": "valid" if models else "degraded",
                "models": models,
                "error_code": None,
                "error_message": f"account={credentials.get('account_email', '')}; tier={credentials.get('user_tier_name') or credentials.get('user_tier') or ''}",
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
        _ = self._load_ready_credentials(key)
        return list(DEFAULT_MODELS)

    async def list_model_records(self, key: KeyConfig) -> list[dict[str, Any]]:
        return [{"id": model, "name": model} for model in await self.list_models(key)]
