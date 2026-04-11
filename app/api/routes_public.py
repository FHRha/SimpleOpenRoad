"""Public (user-facing) OpenAI-style API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import get_container, require_user_auth
from app.api.schemas_openai import ChatCompletionsRequestSchema, ResponsesRequestSchema
from app.container import AppContainer
from app.core.errors import GatewayError
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.router.alias_resolver import resolve_candidates

router = APIRouter()


def _model_item(model_id: str) -> dict:
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "simple-open-road",
    }


@router.get("/health")
async def health(container: AppContainer = Depends(get_container)) -> dict:
    cfg = container.runtime_config.get()
    return {
        "status": "ok",
        "providers": len(container.routing_engine.providers),
        "aliases": len(cfg.routes.aliases),
    }


@router.get("/providers", dependencies=[Depends(require_user_auth)])
async def providers(container: AppContainer = Depends(get_container)) -> list[dict]:
    return container.admin_service.list_providers()


@router.get("/v1/models", dependencies=[Depends(require_user_auth)])
async def models(container: AppContainer = Depends(get_container)) -> dict:
    cfg = container.runtime_config.get()
    seen: set[str] = set()
    data: list[dict] = []

    for alias_name in cfg.routes.aliases:
        candidates, _ = resolve_candidates(cfg, alias_name)
        if not candidates:
            continue
        if alias_name not in seen:
            data.append(_model_item(alias_name))
            seen.add(alias_name)
        for candidate in candidates:
            direct_model_id = f"{candidate.provider}/{candidate.model}"
            if direct_model_id not in seen:
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
        messages=[ChatMessage(role=m.role, content=m.content) for m in payload.messages],
        input=payload.input,
        stream=payload.stream,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        metadata=payload.metadata,
    )
    try:
        if payload.stream:
            stream, ctx = await container.gateway_service.stream_chat_completions(request)
            return StreamingResponse(stream, media_type="text/event-stream", headers={"x-request-id": ctx.request_id})

        result, request_id = await container.gateway_service.chat_completions(request)
        return JSONResponse(content=result, headers={"x-request-id": request_id})
    except GatewayError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "message": exc.message,
                "type": exc.error_class.value,
                "provider": exc.provider,
                "key_id": exc.key_id,
            },
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
        max_tokens=payload.max_tokens,
        metadata=payload.metadata,
    )
    try:
        result, request_id = await container.gateway_service.responses(request)
        return JSONResponse(content=result, headers={"x-request-id": request_id})
    except GatewayError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "message": exc.message,
                "type": exc.error_class.value,
                "provider": exc.provider,
                "key_id": exc.key_id,
            },
        ) from exc
