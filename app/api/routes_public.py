"""Public (user-facing) OpenAI-style API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import get_container, require_user_auth
from app.api.schemas_openai import ChatCompletionsRequestSchema, ResponsesRequestSchema
from app.container import AppContainer
from app.core.errors import GatewayError
from app.core.types import ChatMessage, RouterDecision, UnifiedLLMRequest
from app.inventory.models import GeneratedAlias, GeneratedAliasCandidate
from app.router.alias_resolver import resolve_candidates
router = APIRouter()

_CHAT_KNOWN_EXTRA_FIELDS = {
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "stop",
    "n",
    "user",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "response_format",
    "stream_options",
    "reasoning_effort",
    "modalities",
}
_RESPONSES_KNOWN_EXTRA_FIELDS = {
    "instructions",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "response_format",
    "stream_options",
    "reasoning_effort",
    "text",
    "user",
}


def _model_item(model_id: str) -> dict:
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "simple-open-road",
    }


def _message_to_core(message) -> ChatMessage:
    extra = dict(message.model_extra or {})
    return ChatMessage(
        role=message.role,
        content=message.content,
        name=message.name,
        tool_call_id=message.tool_call_id,
        tool_calls=message.tool_calls,
        **extra,
    )


def _chat_extra_body(payload: ChatCompletionsRequestSchema) -> dict:
    extra = dict(payload.model_extra or {})
    for field_name in _CHAT_KNOWN_EXTRA_FIELDS:
        value = getattr(payload, field_name, None)
        if value is not None:
            extra[field_name] = value
    return extra


def _responses_extra_body(payload: ResponsesRequestSchema) -> dict:
    extra = dict(payload.model_extra or {})
    for field_name in _RESPONSES_KNOWN_EXTRA_FIELDS:
        value = getattr(payload, field_name, None)
        if value is not None:
            extra[field_name] = value
    return extra


def _decision_headers(request_id: str, decision: RouterDecision, payload: dict | None = None) -> dict[str, str]:
    headers = {"x-request-id": request_id}
    selected_model = None
    selected_attempt = next((item for item in reversed(decision.attempts) if item.success), None)
    if selected_attempt is not None:
        selected_model = f"{selected_attempt.provider}/{selected_attempt.model}"
    elif isinstance(payload, dict):
        model_value = payload.get("model")
        if isinstance(model_value, str) and model_value.strip():
            selected_model = model_value.strip()
    if selected_model:
        headers["x-sor-selected-model"] = selected_model

    failed_candidates: list[str] = []
    seen: set[str] = set()
    for attempt in decision.attempts:
        if attempt.success:
            continue
        label = f"{attempt.provider}/{attempt.model}"
        if label in seen:
            continue
        seen.add(label)
        failed_candidates.append(label)
    if failed_candidates:
        headers["x-sor-failed-candidates"] = ", ".join(failed_candidates[:10])
    return headers


@router.get("/health")
async def health(container: AppContainer = Depends(get_container)) -> dict:
    cfg = container.runtime_config.get()
    inventory = container.admin_service.current_inventory()
    generated_aliases = inventory.get("generated_aliases", []) if isinstance(inventory, dict) else []
    return {
        "status": "ok",
        "providers": len(container.routing_engine.providers),
        "aliases": len(generated_aliases) + len(cfg.routes.aliases),
    }


@router.get("/providers", dependencies=[Depends(require_user_auth)])
async def providers(container: AppContainer = Depends(get_container)) -> list[dict]:
    return container.admin_service.list_providers()


@router.get("/v1/models", dependencies=[Depends(require_user_auth)])
async def models(container: AppContainer = Depends(get_container)) -> dict:
    cfg = container.runtime_config.get()
    seen: set[str] = set()
    data: list[dict] = []
    inventory = container.admin_service.current_inventory()
    if not inventory:
        inventory = await container.admin_service.refresh_inventory()

    generated_aliases = inventory.get("generated_aliases", []) if isinstance(inventory, dict) else []
    generated_alias_objects: list[GeneratedAlias] = []
    for alias in generated_aliases:
        if not isinstance(alias, dict):
            continue
        if str(alias.get("modality", "text")) != "text":
            continue
        alias_name = str(alias.get("alias_id", "")).strip()
        if not alias_name or alias_name in seen:
            continue
        generated_alias_objects.append(
            GeneratedAlias(
                alias_id=alias_name,
                scope=str(alias.get("scope", "global")),
                modality=str(alias.get("modality", "text")),
                category=str(alias.get("category", "")),
                provider_scope=alias.get("provider_scope"),
                candidates=[
                    GeneratedAliasCandidate(
                        provider=str(candidate.get("provider", "")),
                        model_id=str(candidate.get("model_id", "")),
                        candidate_type=str(candidate.get("candidate_type", "model")),
                    )
                    for candidate in alias.get("candidates", [])
                    if isinstance(candidate, dict)
                ],
                generation_reason=str(alias.get("generation_reason", "")),
            )
        )
        data.append(_model_item(alias_name))
        seen.add(alias_name)
        candidates = alias.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            provider = str(candidate.get("provider", "")).strip()
            model_id = str(candidate.get("model_id", "")).strip()
            if not provider or not model_id:
                continue
            direct_model_id = f"{provider}/{model_id}"
            if direct_model_id in seen:
                continue
            data.append(_model_item(direct_model_id))
            seen.add(direct_model_id)
    for alias_name in cfg.routes.aliases:
        if alias_name in seen:
            continue
        candidates, _ = resolve_candidates(cfg, alias_name, generated_aliases=generated_alias_objects)
        if not candidates:
            continue
        data.append(_model_item(alias_name))
        seen.add(alias_name)
        for candidate in candidates:
            direct_model_id = f"{candidate.provider}/{candidate.model}"
            if direct_model_id in seen:
                continue
            data.append(_model_item(direct_model_id))
            seen.add(direct_model_id)

    return {"object": "list", "data": data}


@router.post("/v1/chat/completions", dependencies=[Depends(require_user_auth)])
async def chat_completions(
    payload: ChatCompletionsRequestSchema,
    container: AppContainer = Depends(get_container),
):
    request = UnifiedLLMRequest(
        model=payload.model,
        messages=[_message_to_core(m) for m in payload.messages],
        input=payload.input,
        stream=payload.stream,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens or payload.max_completion_tokens,
        metadata=payload.metadata,
        extra_body=_chat_extra_body(payload),
    )
    try:
        if payload.stream:
            stream, ctx = await container.gateway_service.stream_chat_completions(request)
            return StreamingResponse(stream, media_type="text/event-stream", headers={"x-request-id": ctx.request_id})

        result, request_id, decision = await container.gateway_service.chat_completions(request)
        return JSONResponse(content=result, headers=_decision_headers(request_id, decision, result))
    except GatewayError as exc:
        detail = {
            "message": exc.message,
            "type": exc.error_class.value,
            "provider": exc.provider,
            "key_id": exc.key_id,
        }
        if exc.details:
            detail["details"] = exc.details
        raise HTTPException(
            status_code=exc.status_code,
            detail=detail,
        ) from exc


@router.post("/v1/responses", dependencies=[Depends(require_user_auth)])
async def responses(
    payload: ResponsesRequestSchema,
    container: AppContainer = Depends(get_container),
):
    request = UnifiedLLMRequest(
        model=payload.model,
        input=payload.input,
        stream=payload.stream,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens or payload.max_output_tokens,
        metadata=payload.metadata,
        extra_body=_responses_extra_body(payload),
    )
    try:
        result, request_id, decision = await container.gateway_service.responses(request)
        return JSONResponse(content=result, headers=_decision_headers(request_id, decision, result))
    except GatewayError as exc:
        detail = {
            "message": exc.message,
            "type": exc.error_class.value,
            "provider": exc.provider,
            "key_id": exc.key_id,
        }
        if exc.details:
            detail["details"] = exc.details
        raise HTTPException(
            status_code=exc.status_code,
            detail=detail,
        ) from exc
