"""Gemini provider adapter with OpenAI-style normalization."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config.models import KeyConfig, ProviderConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.types import UnifiedLLMRequest, stringify_content
from app.providers.base import ProviderAdapter


class GeminiAdapter(ProviderAdapter):
    def __init__(self, config: ProviderConfig):
        super().__init__(provider_name="gemini", config=config)

    def _gemini_url(self, model: str, method: str, key: KeyConfig, stream: bool = False) -> str:
        model_path = model
        if "/" in model_path:
            model_path = model_path.split("/", 1)[1]
        action = "streamGenerateContent" if stream else "generateContent"
        suffix = f"?alt=sse&key={key.key}" if stream else f"?key={key.key}"
        return f"{self.config.endpoint.rstrip('/')}/{method}/models/{model_path}:{action}{suffix}"

    def _to_gemini_payload(self, request: UnifiedLLMRequest) -> dict[str, Any]:
        contents: list[dict[str, Any]] = []
        system_parts: list[str] = []
        for msg in request.messages:
            if msg.role in {"system", "developer"}:
                text = stringify_content(msg.content)
                if text:
                    system_parts.append(text)
                continue
            role = "model" if msg.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": stringify_content(msg.content)}]})
        instructions = stringify_content(request.extra_body.get("instructions"))
        if instructions:
            system_parts.append(instructions)
        if not contents and request.messages:
            contents.append({"role": "user", "parts": [{"text": ""}]})
        elif request.input is not None:
            contents.append({"role": "user", "parts": [{"text": stringify_content(request.input)}]})

        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(part for part in system_parts if part)}]}
        generation_config: dict[str, Any] = {}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.max_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_tokens
        if generation_config:
            payload["generationConfig"] = generation_config
        return payload

    def _map_non_stream_to_openai(self, data: dict[str, Any], request: UnifiedLLMRequest) -> dict[str, Any]:
        candidates = data.get("candidates", []) if isinstance(data, dict) else []
        text = ""
        finish_reason = None
        if candidates:
            candidate = candidates[0]
            finish_reason = candidate.get("finishReason")
            content = candidate.get("content", {})
            parts = content.get("parts", []) if isinstance(content, dict) else []
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))

        if not text:
            reason_suffix = f" finishReason={finish_reason}" if finish_reason else ""
            raise GatewayError(
                message=f"Gemini returned no assistant text.{reason_suffix}",
                error_class=ErrorClass.MALFORMED_RESPONSE,
                status_code=502,
                provider=self.provider_name,
            )

        usage_meta = data.get("usageMetadata", {}) if isinstance(data, dict) else {}
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

    async def chat_completions(self, request: UnifiedLLMRequest, key: KeyConfig) -> dict:
        payload = self._to_gemini_payload(request)
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    self._gemini_url(request.model, "v1beta", key, stream=False),
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise GatewayError(
                message="Timeout contacting gemini",
                error_class=ErrorClass.NETWORK_TIMEOUT,
                status_code=504,
                provider=self.provider_name,
                key_id=key.id,
            ) from exc
        except httpx.HTTPError as exc:
            raise GatewayError(
                message=f"Network error contacting gemini: {exc}",
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
            elif response.status_code == 400 and "model" in response.text.lower():
                error_class = ErrorClass.UNSUPPORTED_MODEL
            elif 500 <= response.status_code < 600:
                error_class = ErrorClass.PROVIDER_UNAVAILABLE

            raise GatewayError(
                message=f"Gemini returned {response.status_code}: {response.text[:1000]}",
                error_class=error_class,
                status_code=response.status_code,
                provider=self.provider_name,
                key_id=key.id,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise GatewayError(
                message="Malformed response from gemini",
                error_class=ErrorClass.MALFORMED_RESPONSE,
                status_code=502,
                provider=self.provider_name,
                key_id=key.id,
            ) from exc

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
        payload = self._to_gemini_payload(request)
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)

        async def iterator() -> AsyncIterator[bytes]:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST",
                        self._gemini_url(request.model, "v1beta", key, stream=True),
                        json=payload,
                        headers={"Content-Type": "application/json"},
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
                            elif response.status_code == 400 and "model" in body.lower():
                                error_class = ErrorClass.UNSUPPORTED_MODEL
                            elif 500 <= response.status_code < 600:
                                error_class = ErrorClass.PROVIDER_UNAVAILABLE
                            raise GatewayError(
                                message=f"Gemini stream error {response.status_code}: {body}",
                                error_class=error_class,
                                status_code=response.status_code,
                                provider=self.provider_name,
                                key_id=key.id,
                            )

                        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
                        emitted_role = False
                        emitted_text = False
                        finish_reason = None
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            data_line = line[6:] if line.startswith("data: ") else line
                            if data_line.strip() == "[DONE]":
                                continue
                            try:
                                payload_obj = json.loads(data_line)
                            except json.JSONDecodeError:
                                continue
                            text_delta = ""
                            candidates = payload_obj.get("candidates", [])
                            if candidates:
                                candidate = candidates[0]
                                finish_reason = candidate.get("finishReason") or finish_reason
                                content = candidate.get("content", {})
                                parts = content.get("parts", []) if isinstance(content, dict) else []
                                text_delta = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
                            if not text_delta:
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
                                        "delta": {"content": text_delta},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(chunk, ensure_ascii=True)}\n\n".encode("utf-8")
                            emitted_text = True

                        if not emitted_text:
                            reason_suffix = f" finishReason={finish_reason}" if finish_reason else ""
                            raise GatewayError(
                                message=f"Gemini stream returned no assistant text.{reason_suffix}",
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
                    message="Timeout contacting gemini",
                    error_class=ErrorClass.NETWORK_TIMEOUT,
                    status_code=504,
                    provider=self.provider_name,
                    key_id=key.id,
                ) from exc
            except httpx.HTTPError as exc:
                raise GatewayError(
                    message=f"Network error contacting gemini: {exc}",
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
        records = await self.list_model_records(key)
        return [str(item["id"]) for item in records if item.get("id")]

    async def list_model_records(self, key: KeyConfig) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(timeout=self.config.timeout_seconds)
        url = f"{self.config.endpoint.rstrip('/')}/v1beta/models?key={key.key}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
        except httpx.TimeoutException as exc:
            raise GatewayError(
                message="Timeout listing gemini models",
                error_class=ErrorClass.NETWORK_TIMEOUT,
                status_code=504,
                provider=self.provider_name,
                key_id=key.id,
            ) from exc
        except httpx.HTTPError as exc:
            raise GatewayError(
                message=f"Network error listing gemini models: {exc}",
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
            raise GatewayError(
                message=f"Gemini list models error {response.status_code}: {response.text[:1000]}",
                error_class=error_class,
                status_code=response.status_code,
                provider=self.provider_name,
                key_id=key.id,
            )

        payload = response.json()
        models: list[dict[str, Any]] = []
        for item in payload.get("models", []):
            name = item.get("name") if isinstance(item, dict) else None
            if name:
                record = dict(item)
                record["id"] = str(name).split("/")[-1]
                models.append(record)
        return models
