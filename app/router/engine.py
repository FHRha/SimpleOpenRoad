"""Routing engine with retry/fallback behavior across keys and providers."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from app.config.runtime import RuntimeConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.security import is_configured_secret
from app.core.types import LLMUsage, RequestContext, RouterAttempt, RouterDecision, UnifiedLLMRequest
from app.core.utils import mask_secret, utcnow_iso
from app.observability.logging import get_logger
from app.providers.base import ProviderAdapter
from app.providers.registry import build_provider_registry
from app.registry.keys import KeyRegistry
from app.router.backoff import sleep_with_backoff
from app.router.classifier import classify_error
from app.router.model_planner import plan_candidates
from app.router.policy import policy_action, should_retry_same_key, should_switch_provider
from app.router.selector import select_keys
from app.storage.repositories.attempts_repo import AttemptsRepository
from app.storage.repositories.stats_repo import StatsRepository


class RoutingEngine:
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        key_registry: KeyRegistry,
        attempts_repo: AttemptsRepository,
        stats_repo: StatsRepository,
    ):
        self.runtime_config = runtime_config
        self.key_registry = key_registry
        self.attempts_repo = attempts_repo
        self.stats_repo = stats_repo
        self.logger = get_logger("gateway.router")
        self.providers: dict[str, ProviderAdapter] = build_provider_registry(runtime_config.get())

    def refresh_providers(self) -> None:
        self.providers = build_provider_registry(self.runtime_config.get())

    @staticmethod
    def _usage_from_payload(payload: dict) -> LLMUsage:
        usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
        return LLMUsage(
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
        )

    @staticmethod
    def _sanitize_error_message(message: str, key_value: str, mask_secrets: bool) -> str:
        if not mask_secrets or not key_value:
            return message
        return message.replace(key_value, mask_secret(key_value))

    @staticmethod
    def _cooldown_error(
        config,
        candidates,
        runtime_states: dict[str, dict],
    ) -> GatewayError | None:
        candidate_providers = {candidate.provider for candidate in candidates}
        if not candidate_providers:
            return None

        now = datetime.now().astimezone()
        any_rate_limited = False
        retry_after_seconds: int | None = None
        any_blocked = False

        for provider_name in candidate_providers:
            provider = config.providers.get(provider_name)
            if provider is None or not provider.enabled:
                continue
            for key in provider.keys:
                if not key.active or not is_configured_secret(key.key):
                    continue
                runtime = runtime_states.get(key.id)
                if runtime and not bool(runtime.get("active", 1)):
                    continue
                if runtime and runtime.get("status") == "blocked":
                    any_blocked = True
                    if runtime.get("last_error_code") == ErrorClass.RATE_LIMIT.value:
                        any_rate_limited = True
                cooldown_until_raw = runtime.get("cooldown_until") if runtime else None
                if not cooldown_until_raw:
                    continue
                try:
                    cooldown_until = datetime.fromisoformat(cooldown_until_raw)
                except ValueError:
                    continue
                if cooldown_until <= now:
                    continue
                seconds_left = max(1, int((cooldown_until - now).total_seconds()))
                retry_after_seconds = (
                    seconds_left
                    if retry_after_seconds is None
                    else min(retry_after_seconds, seconds_left)
                )
                if runtime.get("last_error_code") == ErrorClass.RATE_LIMIT.value:
                    any_rate_limited = True

        if any_rate_limited:
            details = {"retry_after_seconds": retry_after_seconds} if retry_after_seconds is not None else None
            message = "All configured keys are cooling down after rate limit. Retry shortly."
            if retry_after_seconds is not None:
                message = f"{message} Retry after about {retry_after_seconds}s."
            return GatewayError(
                message=message,
                error_class=ErrorClass.RATE_LIMIT,
                status_code=429,
                details=details,
            )

        if any_blocked:
            return GatewayError(
                message="All configured keys for the selected route are currently blocked.",
                error_class=ErrorClass.PROVIDER_UNAVAILABLE,
                status_code=503,
            )

        return None

    async def route_chat_completion(
        self,
        request: UnifiedLLMRequest,
        context: RequestContext,
    ) -> tuple[dict, RouterDecision]:
        return await self._route_non_stream(kind="chat", request=request, context=context)

    async def route_responses(
        self,
        request: UnifiedLLMRequest,
        context: RequestContext,
    ) -> tuple[dict, RouterDecision]:
        return await self._route_non_stream(kind="responses", request=request, context=context)

    async def _route_non_stream(
        self,
        kind: str,
        request: UnifiedLLMRequest,
        context: RequestContext,
    ) -> tuple[dict, RouterDecision]:
        config = self.runtime_config.get()
        candidates, resolved_alias = plan_candidates(config, request)
        selection_strategy = config.routing.default_strategy
        if resolved_alias and resolved_alias in config.routes.aliases:
            selection_strategy = config.routes.aliases[resolved_alias].strategy
        decision = RouterDecision(
            request_id=context.request_id,
            requested_model=request.model,
            resolved_alias=resolved_alias,
            selected_provider=None,
            selected_key_id=None,
        )

        runtime_states = {s["key_id"]: s for s in self.key_registry.runtime_repo.list_states()}
        final_error: GatewayError | None = None
        attempt_index = 0

        for candidate_index, candidate in enumerate(candidates):
            adapter = self.providers.get(candidate.provider)
            if adapter is None:
                continue

            configured_keys = self.key_registry.get_available_keys_for_runtime(
                config,
                candidate.provider,
                runtime_states,
            )
            if not configured_keys:
                continue
            selected_keys = select_keys(
                strategy=selection_strategy,
                keys=configured_keys,
                runtime_by_key=runtime_states,
            )

            switch_provider_now = False
            for key in selected_keys:
                max_attempts = max(
                    1,
                    min(
                        config.routing.retry.max_attempts_per_candidate,
                        key.max_retries + 1,
                    ),
                )

                for key_attempt in range(1, max_attempts + 1):
                    attempt_index += 1
                    start = time.perf_counter()
                    candidate_request = request.model_copy(update={"model": candidate.model, "stream": False})
                    try:
                        if kind == "chat":
                            payload = await adapter.chat_completions(candidate_request, key)
                        else:
                            payload = await adapter.responses(candidate_request, key)
                        latency_ms = (time.perf_counter() - start) * 1000

                        self.key_registry.record_success(key.id, latency_ms)
                        self.stats_repo.record_request(
                            provider=candidate.provider,
                            key_id=key.id,
                            success=True,
                            latency_ms=latency_ms,
                            usage=self._usage_from_payload(payload),
                        )
                        if config.observability.save_attempt_events:
                            self.attempts_repo.add_attempt(
                                request_id=context.request_id,
                                route_alias=context.route_alias,
                                provider=candidate.provider,
                                key_id=key.id,
                                model=candidate.model,
                                attempt_index=attempt_index,
                                outcome="success",
                                error_class=None,
                                latency_ms=latency_ms,
                                created_at=utcnow_iso(),
                            )
                        router_attempt = RouterAttempt(
                            attempt_index=attempt_index,
                            provider=candidate.provider,
                            key_id=key.id,
                            model=candidate.model,
                            success=True,
                            latency_ms=latency_ms,
                        )
                        decision.attempts.append(router_attempt)
                        decision.selected_provider = candidate.provider
                        decision.selected_key_id = key.id
                        payload["model"] = f"{candidate.provider}/{candidate.model}"
                        return payload, decision
                    except Exception as exc:  # noqa: BLE001 - normalized below
                        latency_ms = (time.perf_counter() - start) * 1000
                        error_class = classify_error(exc)
                        gateway_error = (
                            exc
                            if isinstance(exc, GatewayError)
                            else GatewayError(
                                message=str(exc),
                                error_class=ErrorClass.UNKNOWN,
                                status_code=500,
                                provider=candidate.provider,
                                key_id=key.id,
                            )
                        )
                        error_message = self._sanitize_error_message(
                            message=gateway_error.message,
                            key_value=key.key,
                            mask_secrets=config.security.mask_secrets_in_logs,
                        )
                        final_error = gateway_error

                        self.key_registry.record_failure(key, error_class, error_message)
                        self.stats_repo.record_request(
                            provider=candidate.provider,
                            key_id=key.id,
                            success=False,
                            latency_ms=latency_ms,
                            usage=None,
                        )
                        if config.observability.save_attempt_events:
                            self.attempts_repo.add_attempt(
                                request_id=context.request_id,
                                route_alias=context.route_alias,
                                provider=candidate.provider,
                                key_id=key.id,
                                model=candidate.model,
                                attempt_index=attempt_index,
                                outcome="failure",
                                error_class=error_class.value,
                                latency_ms=latency_ms,
                                created_at=utcnow_iso(),
                            )
                        decision.attempts.append(
                            RouterAttempt(
                                attempt_index=attempt_index,
                                provider=candidate.provider,
                                key_id=key.id,
                                model=candidate.model,
                                success=False,
                                latency_ms=latency_ms,
                                error_class=error_class,
                                error_message=error_message,
                            )
                        )

                        action = policy_action(config.routing.error_policy, error_class)
                        if config.observability.router_decision_log:
                            self.logger.warning(
                                "route attempt failed",
                                extra={
                                    "request_id": context.request_id,
                                    "provider": candidate.provider,
                                    "key_id": key.id,
                                    "model": candidate.model,
                                    "error_class": error_class.value,
                                },
                            )

                        if error_class == ErrorClass.RATE_LIMIT and candidate_index < len(candidates) - 1:
                            self.key_registry.bump_switch(key.id)
                            break

                        if should_retry_same_key(action, key_attempt, max_attempts):
                            await sleep_with_backoff(config.routing.retry, key_attempt)
                            continue

                        if should_switch_provider(action):
                            switch_provider_now = True
                            self.key_registry.bump_switch(key.id)
                            break

                        self.key_registry.bump_switch(key.id)
                        break

                if switch_provider_now:
                    break

        if final_error is not None:
            raise final_error

        cooldown_error = self._cooldown_error(config, candidates, runtime_states)
        if cooldown_error is not None:
            raise cooldown_error

        raise GatewayError(
            message="No healthy route candidates available",
            error_class=ErrorClass.PROVIDER_UNAVAILABLE,
            status_code=503,
        )

    async def route_chat_completion_stream(
        self,
        request: UnifiedLLMRequest,
        context: RequestContext,
    ) -> tuple[AsyncIterator[bytes], RouterDecision]:
        config = self.runtime_config.get()
        candidates, resolved_alias = plan_candidates(config, request)
        selection_strategy = config.routing.default_strategy
        if resolved_alias and resolved_alias in config.routes.aliases:
            selection_strategy = config.routes.aliases[resolved_alias].strategy
        decision = RouterDecision(
            request_id=context.request_id,
            requested_model=request.model,
            resolved_alias=resolved_alias,
            selected_provider=None,
            selected_key_id=None,
        )

        runtime_states = {s["key_id"]: s for s in self.key_registry.runtime_repo.list_states()}
        final_error: GatewayError | None = None
        attempt_index = 0

        for candidate_index, candidate in enumerate(candidates):
            adapter = self.providers.get(candidate.provider)
            if adapter is None:
                continue

            configured_keys = self.key_registry.get_available_keys_for_runtime(
                config,
                candidate.provider,
                runtime_states,
            )
            if not configured_keys:
                continue
            selected_keys = select_keys(
                strategy=selection_strategy,
                keys=configured_keys,
                runtime_by_key=runtime_states,
            )

            switch_provider_now = False
            for key in selected_keys:
                max_attempts = max(
                    1,
                    min(
                        config.routing.retry.max_attempts_per_candidate,
                        key.max_retries + 1,
                    ),
                )
                for key_attempt in range(1, max_attempts + 1):
                    attempt_index += 1
                    start = time.perf_counter()
                    candidate_request = request.model_copy(update={"model": candidate.model, "stream": True})
                    try:
                        iterator = await adapter.stream_chat_completions(candidate_request, key)
                        first_chunk = await anext(iterator)
                        latency_ms = (time.perf_counter() - start) * 1000

                        self.key_registry.record_success(key.id, latency_ms)
                        self.stats_repo.record_request(
                            provider=candidate.provider,
                            key_id=key.id,
                            success=True,
                            latency_ms=latency_ms,
                            usage=None,
                        )
                        if config.observability.save_attempt_events:
                            self.attempts_repo.add_attempt(
                                request_id=context.request_id,
                                route_alias=context.route_alias,
                                provider=candidate.provider,
                                key_id=key.id,
                                model=candidate.model,
                                attempt_index=attempt_index,
                                outcome="success",
                                error_class=None,
                                latency_ms=latency_ms,
                                created_at=utcnow_iso(),
                            )
                        decision.attempts.append(
                            RouterAttempt(
                                attempt_index=attempt_index,
                                provider=candidate.provider,
                                key_id=key.id,
                                model=candidate.model,
                                success=True,
                                latency_ms=latency_ms,
                            )
                        )
                        decision.selected_provider = candidate.provider
                        decision.selected_key_id = key.id

                        async def with_first_chunk() -> AsyncIterator[bytes]:
                            yield first_chunk
                            async for chunk in iterator:
                                yield chunk

                        return with_first_chunk(), decision
                    except StopAsyncIteration:
                        async def done_stream() -> AsyncIterator[bytes]:
                            yield b"data: [DONE]\\n\\n"

                        return done_stream(), decision
                    except Exception as exc:  # noqa: BLE001 - normalized below
                        latency_ms = (time.perf_counter() - start) * 1000
                        error_class = classify_error(exc)
                        gateway_error = (
                            exc
                            if isinstance(exc, GatewayError)
                            else GatewayError(
                                message=str(exc),
                                error_class=ErrorClass.UNKNOWN,
                                status_code=500,
                                provider=candidate.provider,
                                key_id=key.id,
                            )
                        )
                        error_message = self._sanitize_error_message(
                            message=gateway_error.message,
                            key_value=key.key,
                            mask_secrets=config.security.mask_secrets_in_logs,
                        )
                        final_error = gateway_error
                        self.key_registry.record_failure(key, error_class, error_message)
                        self.stats_repo.record_request(
                            provider=candidate.provider,
                            key_id=key.id,
                            success=False,
                            latency_ms=latency_ms,
                            usage=None,
                        )
                        if config.observability.save_attempt_events:
                            self.attempts_repo.add_attempt(
                                request_id=context.request_id,
                                route_alias=context.route_alias,
                                provider=candidate.provider,
                                key_id=key.id,
                                model=candidate.model,
                                attempt_index=attempt_index,
                                outcome="failure",
                                error_class=error_class.value,
                                latency_ms=latency_ms,
                                created_at=utcnow_iso(),
                            )
                        decision.attempts.append(
                            RouterAttempt(
                                attempt_index=attempt_index,
                                provider=candidate.provider,
                                key_id=key.id,
                                model=candidate.model,
                                success=False,
                                latency_ms=latency_ms,
                                error_class=error_class,
                                error_message=error_message,
                            )
                        )
                        action = policy_action(config.routing.error_policy, error_class)
                        if config.observability.router_decision_log:
                            self.logger.warning(
                                "route stream attempt failed",
                                extra={
                                    "request_id": context.request_id,
                                    "provider": candidate.provider,
                                    "key_id": key.id,
                                    "model": candidate.model,
                                    "error_class": error_class.value,
                                },
                            )
                        if error_class == ErrorClass.RATE_LIMIT and candidate_index < len(candidates) - 1:
                            self.key_registry.bump_switch(key.id)
                            break

                        if should_retry_same_key(action, key_attempt, max_attempts):
                            await sleep_with_backoff(config.routing.retry, key_attempt)
                            continue
                        if should_switch_provider(action):
                            switch_provider_now = True
                            self.key_registry.bump_switch(key.id)
                            break
                        self.key_registry.bump_switch(key.id)
                        break

                if switch_provider_now:
                    break

        if final_error is not None:
            raise final_error
        cooldown_error = self._cooldown_error(config, candidates, runtime_states)
        if cooldown_error is not None:
            raise cooldown_error
        raise GatewayError(
            message="No healthy route candidates available for stream",
            error_class=ErrorClass.PROVIDER_UNAVAILABLE,
            status_code=503,
        )

    @staticmethod
    def build_context(route_alias: str | None, stream: bool, timeout_seconds: float | None = None) -> RequestContext:
        return RequestContext(
            request_id=str(uuid.uuid4()),
            route_alias=route_alias,
            stream=stream,
            timeout_seconds=timeout_seconds,
            profile=None,
        )
