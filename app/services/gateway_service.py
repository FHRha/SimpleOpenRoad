"""Gateway service for handling user-facing inference requests."""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.types import RequestContext, UnifiedLLMRequest
from app.observability.logging import get_logger
from app.router.engine import RoutingEngine


class GatewayService:
    def __init__(self, routing_engine: RoutingEngine):
        self.routing_engine = routing_engine
        self.logger = get_logger("gateway.service")

    def _should_log_decisions(self) -> bool:
        return self.routing_engine.runtime_config.get().observability.router_decision_log

    async def chat_completions(self, request: UnifiedLLMRequest) -> tuple[dict, str]:
        context = self.routing_engine.build_context(route_alias=request.model if request.model.startswith("auto/") else None, stream=False)
        payload, decision = await self.routing_engine.route_chat_completion(request, context)
        if self._should_log_decisions():
            self.logger.info(
                "chat completion routed",
                extra={
                    "request_id": context.request_id,
                    "provider": decision.selected_provider,
                    "key_id": decision.selected_key_id,
                    "route_alias": decision.resolved_alias,
                },
            )
        return payload, context.request_id

    async def responses(self, request: UnifiedLLMRequest) -> tuple[dict, str]:
        context = self.routing_engine.build_context(route_alias=request.model if request.model.startswith("auto/") else None, stream=False)
        payload, decision = await self.routing_engine.route_responses(request, context)
        if self._should_log_decisions():
            self.logger.info(
                "responses routed",
                extra={
                    "request_id": context.request_id,
                    "provider": decision.selected_provider,
                    "key_id": decision.selected_key_id,
                    "route_alias": decision.resolved_alias,
                },
            )
        return payload, context.request_id

    async def stream_chat_completions(self, request: UnifiedLLMRequest) -> tuple[AsyncIterator[bytes], RequestContext]:
        context = self.routing_engine.build_context(route_alias=request.model if request.model.startswith("auto/") else None, stream=True)
        stream_iter, decision = await self.routing_engine.route_chat_completion_stream(request, context)
        if self._should_log_decisions():
            self.logger.info(
                "chat stream routed",
                extra={
                    "request_id": context.request_id,
                    "provider": decision.selected_provider,
                    "key_id": decision.selected_key_id,
                    "route_alias": decision.resolved_alias,
                },
            )
        return stream_iter, context
