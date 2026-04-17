"""Routing engine with retry/fallback behavior across keys and providers."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from app.config.runtime import RuntimeConfig
from app.core.errors import ErrorClass, GatewayError
from app.core.security import is_configured_secret
from app.core.types import LLMUsage, RequestContext, RouteCandidate, RouterAttempt, RouterDecision, UnifiedLLMRequest
from app.core.utils import mask_secret, utcnow_iso
from app.inventory.discovery import InventoryDiscoveryService
from app.inventory.models import GeneratedAlias
from app.observability.logging import get_logger
from app.providers.base import ProviderAdapter
from app.providers.registry import build_provider_registry
from app.registry.keys import KeyRegistry
from app.router.backoff import sleep_with_backoff
from app.router.classifier import classify_error
from app.router.context_limits import filter_candidates_by_context, limits_from_snapshot
from app.router.alias_resolver import looks_like_generated_alias
from app.router.model_planner import plan_candidates
from app.router.policy import policy_action, should_retry_same_key, should_switch_provider
from app.router.request_analyzer import analyze_request_route
from app.router.response_validator import validate_chat_completion_payload, validate_responses_payload
from app.router.selector import select_keys
from app.router.stream_normalizer import normalize_openai_stream
from app.storage.repositories.attempts_repo import AttemptsRepository
from app.storage.repositories.route_memory_repo import RouteModelMemoryRepository
from app.storage.repositories.stats_repo import StatsRepository


class RoutingEngine:
    def __init__(
        self,
        runtime_config: RuntimeConfig,
        key_registry: KeyRegistry,
        attempts_repo: AttemptsRepository,
        route_memory_repo: RouteModelMemoryRepository | None,
        stats_repo: StatsRepository,
        inventory_discovery: InventoryDiscoveryService,
    ):
        self.runtime_config = runtime_config
        self.key_registry = key_registry
        self.attempts_repo = attempts_repo
        self.route_memory_repo = route_memory_repo
        self.stats_repo = stats_repo
        self.inventory_discovery = inventory_discovery
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
    def _candidate_detail(candidate, status: str, reason: str, keys: int | None = None) -> dict:
        detail = {
            "provider": candidate.provider,
            "model": candidate.model,
            "status": status,
            "reason": reason,
        }
        if keys is not None:
            detail["available_keys"] = keys
        return detail

    @staticmethod
    def _text_generated_aliases(snapshot) -> list[GeneratedAlias]:
        return [alias for alias in snapshot.generated_aliases if alias.modality == "text"] if snapshot else []

    @staticmethod
    def _snapshot_has_alias(snapshot, alias_id: str) -> bool:
        return any(alias.alias_id == alias_id for alias in RoutingEngine._text_generated_aliases(snapshot))

    async def _snapshot_for_request(self, config, request: UnifiedLLMRequest):
        snapshot = self.inventory_discovery.current_snapshot()
        if snapshot is None:
            return await self.inventory_discovery.refresh()
        if looks_like_generated_alias(config, request.model) and not self._snapshot_has_alias(snapshot, request.model):
            return await self.inventory_discovery.refresh()
        return snapshot

    @staticmethod
    def _diagnostic_candidates(
        config,
        request: UnifiedLLMRequest,
        candidates: list[RouteCandidate],
        generated_aliases: list[GeneratedAlias] | None = None,
    ) -> list[RouteCandidate]:
        if candidates:
            return candidates
        alias_map = {alias.alias_id: alias for alias in generated_aliases or []}
        generated_alias = alias_map.get(request.model)
        if generated_alias is not None:
            return [
                RouteCandidate(provider=candidate.provider, model=candidate.model_id)
                for candidate in generated_alias.candidates
            ]
        if request.model in config.routes.aliases:
            alias_cfg = config.routes.aliases[request.model]
            return [RouteCandidate(provider=c.provider, model=c.model) for c in alias_cfg.candidates]
        if "/" in request.model:
            provider_name, model_name = request.model.split("/", 1)
            if provider_name in config.providers:
                return [RouteCandidate(provider=provider_name, model=model_name)]
        if looks_like_generated_alias(config, request.model):
            return []
        return [
            RouteCandidate(provider=provider_name, model=request.model)
            for provider_name, provider in sorted(config.providers.items(), key=lambda item: item[1].priority)
            if provider.enabled
        ]

    @staticmethod
    def _route_memory_key(request: UnifiedLLMRequest, analysis=None) -> tuple[str, str]:
        if analysis is None:
            analysis = analyze_request_route(request)
        return analysis.profile, analysis.context_bucket

    @staticmethod
    def _analysis_detail(request: UnifiedLLMRequest) -> dict:
        analysis = analyze_request_route(request)
        return {
            "intent": analysis.intent,
            "profile": analysis.profile,
            "complexity_score": analysis.complexity_score,
            "context_bucket": analysis.context_bucket,
            "token_estimate": analysis.token_estimate,
            "requires_tools": analysis.requires_tools,
            "reasons": analysis.reasons,
        }

    @staticmethod
    def _generated_alias_by_id(generated_aliases: list[GeneratedAlias], alias_id: str | None) -> GeneratedAlias | None:
        if not alias_id:
            return None
        return next((alias for alias in generated_aliases if alias.alias_id == alias_id), None)

    @staticmethod
    def _is_free_alias(resolved_alias: str | None, generated_aliases: list[GeneratedAlias]) -> bool:
        if not resolved_alias:
            return False
        if resolved_alias in {"auto/free", "auto/text/free"} or resolved_alias.endswith("/text/free"):
            return True
        alias = RoutingEngine._generated_alias_by_id(generated_aliases, resolved_alias)
        return bool(alias and alias.category == "free")

    @staticmethod
    def _apply_free_alias_budget(
        config,
        candidates: list[RouteCandidate],
        resolved_alias: str | None,
        generated_aliases: list[GeneratedAlias],
    ) -> tuple[list[RouteCandidate], dict]:
        if not RoutingEngine._is_free_alias(resolved_alias, generated_aliases):
            return candidates, {"free_only": False, "route_alias": resolved_alias}
        limit = max(1, config.routing.free_alias.max_candidates_per_request)
        capped_candidates = candidates[:limit]
        return capped_candidates, {
            "free_only": True,
            "route_alias": resolved_alias,
            "paid_fallback": "disabled",
            "max_candidates_per_request": limit,
            "candidate_count_before_budget": len(candidates),
            "candidate_count_after_budget": len(capped_candidates),
        }

    @staticmethod
    def _attempts_detail(decision: RouterDecision) -> list[dict]:
        attempts: list[dict] = []
        for attempt in decision.attempts:
            item = {
                "attempt": attempt.attempt_index,
                "provider": attempt.provider,
                "key_id": attempt.key_id,
                "model": attempt.model,
                "success": attempt.success,
                "latency_ms": attempt.latency_ms,
            }
            if attempt.error_class is not None:
                item["error_class"] = attempt.error_class.value
            if attempt.error_message:
                item["error_message"] = attempt.error_message
            attempts.append(item)
        return attempts

    @staticmethod
    def _is_provider_free_tier_rate_limit(error: GatewayError) -> bool:
        return (
            error.error_class == ErrorClass.RATE_LIMIT
            and isinstance(error.details, dict)
            and error.details.get("rate_limit_scope") == "provider_free_tier"
        )

    def _with_route_error_details(
        self,
        error: GatewayError,
        request: UnifiedLLMRequest,
        route_memory_detail: dict,
        candidate_details: list[dict],
        decision: RouterDecision,
        free_alias_detail: dict,
    ) -> GatewayError:
        details = dict(error.details or {})
        details.update(
            {
                "analysis": self._analysis_detail(request),
                "route_memory": route_memory_detail,
                "candidates": candidate_details,
                "attempts": self._attempts_detail(decision),
                "route_alias": decision.resolved_alias,
                "free_alias": free_alias_detail,
            }
        )
        error.details = details
        return error

    def _prioritize_remembered_candidate(
        self,
        *,
        candidates: list[RouteCandidate],
        resolved_alias: str | None,
        profile: str,
        context_bucket: str,
    ) -> tuple[list[RouteCandidate], dict]:
        detail = {
            "status": "ignored_direct" if not resolved_alias else "disabled",
            "route_alias": resolved_alias,
            "profile": profile,
            "context_bucket": context_bucket,
        }
        if not resolved_alias:
            return candidates, detail
        if self.route_memory_repo is None:
            return candidates, detail
        remembered = self.route_memory_repo.get(resolved_alias, profile, context_bucket)
        if not remembered:
            detail["status"] = "miss"
            return candidates, detail
        remembered_marker = (remembered.get("provider"), remembered.get("model"))
        detail.update(
            {
                "status": "stale",
                "remembered_provider": remembered_marker[0],
                "remembered_model": remembered_marker[1],
                "success_count": remembered.get("success_count"),
                "avg_latency_ms": remembered.get("avg_latency_ms"),
                "updated_at": remembered.get("updated_at"),
            }
        )
        for index, candidate in enumerate(candidates):
            if (candidate.provider, candidate.model) != remembered_marker:
                continue
            detail["status"] = "hit"
            detail["position_before"] = index + 1
            return [candidate, *candidates[:index], *candidates[index + 1 :]], detail
        return candidates, detail

    def _remember_successful_candidate(
        self,
        *,
        resolved_alias: str | None,
        profile: str,
        context_bucket: str,
        candidate: RouteCandidate,
        latency_ms: float,
    ) -> None:
        if not resolved_alias or self.route_memory_repo is None:
            return
        self.route_memory_repo.record_success(
            route_alias=resolved_alias,
            profile=profile,
            context_bucket=context_bucket,
            provider=candidate.provider,
            model=candidate.model,
            latency_ms=latency_ms,
            updated_at=utcnow_iso(),
        )

    @staticmethod
    def _cooldown_error(
        config,
        candidates,
        runtime_states: dict[str, dict],
        *,
        resolved_alias: str | None = None,
        free_alias_detail: dict | None = None,
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
            details = {"retry_after_seconds": retry_after_seconds} if retry_after_seconds is not None else {}
            provider_name = next(iter(candidate_providers)) if len(candidate_providers) == 1 else None
            if provider_name is not None:
                details["cooldown_provider"] = provider_name
            if resolved_alias:
                details["route_alias"] = resolved_alias
            if free_alias_detail:
                details["free_alias"] = free_alias_detail

            if free_alias_detail and free_alias_detail.get("free_only"):
                message = "Free-only route is cooling down after rate limit. No paid fallback was used."
            else:
                message = "All configured keys are cooling down after rate limit. Retry shortly."
            if retry_after_seconds is not None:
                message = f"{message} Retry after about {retry_after_seconds}s."
            return GatewayError(
                message=message,
                error_class=ErrorClass.RATE_LIMIT,
                status_code=429,
                provider=provider_name,
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
        snapshot = await self._snapshot_for_request(config, request)
        generated_aliases = self._text_generated_aliases(snapshot)
        analysis = analyze_request_route(request)
        candidates, resolved_alias = plan_candidates(config, request, generated_aliases=generated_aliases)
        candidates, context_skipped_details = filter_candidates_by_context(
            candidates,
            analysis.token_estimate,
            limits_from_snapshot(snapshot),
        )
        route_profile, context_bucket = self._route_memory_key(request, analysis)
        candidates, route_memory_detail = self._prioritize_remembered_candidate(
            candidates=candidates,
            resolved_alias=resolved_alias,
            profile=route_profile,
            context_bucket=context_bucket,
        )
        candidates, free_alias_detail = self._apply_free_alias_budget(
            config,
            candidates,
            resolved_alias,
            generated_aliases,
        )
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
        candidate_details: list[dict] = list(context_skipped_details)
        stop_routing_now = False

        for candidate_index, candidate in enumerate(candidates):
            adapter = self.providers.get(candidate.provider)
            if adapter is None:
                candidate_details.append(self._candidate_detail(candidate, "skipped", "provider_not_registered"))
                continue

            configured_keys = self.key_registry.get_available_keys_for_runtime(
                config,
                candidate.provider,
                runtime_states,
            )
            if not configured_keys:
                candidate_details.append(self._candidate_detail(candidate, "skipped", "no_available_keys", 0))
                continue
            candidate_details.append(
                self._candidate_detail(candidate, "attempted", "keys_available", len(configured_keys))
            )
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
                            validate_chat_completion_payload(payload, provider=candidate.provider, key_id=key.id)
                        else:
                            payload = await adapter.responses(candidate_request, key)
                            validate_responses_payload(payload, provider=candidate.provider, key_id=key.id)
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
                        self._remember_successful_candidate(
                            resolved_alias=resolved_alias,
                            profile=route_profile,
                            context_bucket=context_bucket,
                            candidate=candidate,
                            latency_ms=latency_ms,
                        )
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

                        if (
                            free_alias_detail.get("free_only")
                            and config.routing.free_alias.stop_on_provider_free_tier_rate_limit
                            and self._is_provider_free_tier_rate_limit(gateway_error)
                        ):
                            final_error = GatewayError(
                                message=(
                                    f"{gateway_error.message} "
                                    "The selected free alias is strict free-only; paid fallback was not used."
                                ),
                                error_class=ErrorClass.RATE_LIMIT,
                                status_code=429,
                                provider=gateway_error.provider,
                                key_id=gateway_error.key_id,
                                details=gateway_error.details,
                            )
                            self.key_registry.bump_switch(key.id)
                            stop_routing_now = True
                            break

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

                if switch_provider_now or stop_routing_now:
                    break

            if stop_routing_now:
                break

        if final_error is not None:
            raise self._with_route_error_details(
                final_error,
                request,
                route_memory_detail,
                candidate_details,
                decision,
                free_alias_detail,
            )

        cooldown_error = self._cooldown_error(
            config,
            candidates,
            runtime_states,
            resolved_alias=resolved_alias,
            free_alias_detail=free_alias_detail,
        )
        if cooldown_error is not None:
            raise self._with_route_error_details(
                cooldown_error,
                request,
                route_memory_detail,
                candidate_details,
                decision,
                free_alias_detail,
            )

        if not candidate_details and looks_like_generated_alias(config, request.model):
            candidate_details.append(
                {
                    "provider": "alias",
                    "model": request.model,
                    "status": "skipped",
                    "reason": "generated_alias_not_available",
                }
            )

        if not candidate_details:
            for candidate in self._diagnostic_candidates(config, request, candidates, generated_aliases):
                provider = config.providers.get(candidate.provider)
                if provider is None:
                    candidate_details.append(self._candidate_detail(candidate, "skipped", "provider_not_configured"))
                elif not provider.enabled:
                    candidate_details.append(self._candidate_detail(candidate, "skipped", "provider_disabled"))
                else:
                    candidate_details.append(self._candidate_detail(candidate, "skipped", "no_available_keys", 0))

        raise GatewayError(
            message="No healthy route candidates available",
            error_class=ErrorClass.PROVIDER_UNAVAILABLE,
            status_code=503,
            details={
                "analysis": self._analysis_detail(request),
                "route_memory": route_memory_detail,
                "candidates": candidate_details,
                "attempts": self._attempts_detail(decision),
                "free_alias": free_alias_detail,
            },
        )

    async def route_chat_completion_stream(
        self,
        request: UnifiedLLMRequest,
        context: RequestContext,
    ) -> tuple[AsyncIterator[bytes], RouterDecision]:
        config = self.runtime_config.get()
        snapshot = await self._snapshot_for_request(config, request)
        generated_aliases = self._text_generated_aliases(snapshot)
        analysis = analyze_request_route(request)
        candidates, resolved_alias = plan_candidates(config, request, generated_aliases=generated_aliases)
        candidates, context_skipped_details = filter_candidates_by_context(
            candidates,
            analysis.token_estimate,
            limits_from_snapshot(snapshot),
        )
        route_profile, context_bucket = self._route_memory_key(request, analysis)
        candidates, route_memory_detail = self._prioritize_remembered_candidate(
            candidates=candidates,
            resolved_alias=resolved_alias,
            profile=route_profile,
            context_bucket=context_bucket,
        )
        candidates, free_alias_detail = self._apply_free_alias_budget(
            config,
            candidates,
            resolved_alias,
            generated_aliases,
        )
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
        candidate_details: list[dict] = list(context_skipped_details)
        stop_routing_now = False

        for candidate_index, candidate in enumerate(candidates):
            adapter = self.providers.get(candidate.provider)
            if adapter is None:
                candidate_details.append(self._candidate_detail(candidate, "skipped", "provider_not_registered"))
                continue

            configured_keys = self.key_registry.get_available_keys_for_runtime(
                config,
                candidate.provider,
                runtime_states,
            )
            if not configured_keys:
                candidate_details.append(self._candidate_detail(candidate, "skipped", "no_available_keys", 0))
                continue
            candidate_details.append(
                self._candidate_detail(candidate, "attempted", "keys_available", len(configured_keys))
            )
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
                        normalized_iterator = normalize_openai_stream(
                            iterator,
                            model=candidate.model,
                            provider=candidate.provider,
                            key_id=key.id,
                        )
                        first_chunk = await anext(normalized_iterator)
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
                        self._remember_successful_candidate(
                            resolved_alias=resolved_alias,
                            profile=route_profile,
                            context_bucket=context_bucket,
                            candidate=candidate,
                            latency_ms=latency_ms,
                        )

                        async def with_first_chunk() -> AsyncIterator[bytes]:
                            yield first_chunk
                            async for chunk in normalized_iterator:
                                yield chunk

                        return with_first_chunk(), decision
                    except StopAsyncIteration:
                        gateway_error = GatewayError(
                            message="Provider stream ended before assistant content or tool calls",
                            error_class=ErrorClass.MALFORMED_RESPONSE,
                            status_code=502,
                            provider=candidate.provider,
                            key_id=key.id,
                        )
                        latency_ms = (time.perf_counter() - start) * 1000
                        error_class = gateway_error.error_class
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
                        continue
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
                        if (
                            free_alias_detail.get("free_only")
                            and config.routing.free_alias.stop_on_provider_free_tier_rate_limit
                            and self._is_provider_free_tier_rate_limit(gateway_error)
                        ):
                            final_error = GatewayError(
                                message=(
                                    f"{gateway_error.message} "
                                    "The selected free alias is strict free-only; paid fallback was not used."
                                ),
                                error_class=ErrorClass.RATE_LIMIT,
                                status_code=429,
                                provider=gateway_error.provider,
                                key_id=gateway_error.key_id,
                                details=gateway_error.details,
                            )
                            self.key_registry.bump_switch(key.id)
                            stop_routing_now = True
                            break
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

                if switch_provider_now or stop_routing_now:
                    break

            if stop_routing_now:
                break

        if final_error is not None:
            raise self._with_route_error_details(
                final_error,
                request,
                route_memory_detail,
                candidate_details,
                decision,
                free_alias_detail,
            )
        cooldown_error = self._cooldown_error(
            config,
            candidates,
            runtime_states,
            resolved_alias=resolved_alias,
            free_alias_detail=free_alias_detail,
        )
        if cooldown_error is not None:
            raise self._with_route_error_details(
                cooldown_error,
                request,
                route_memory_detail,
                candidate_details,
                decision,
                free_alias_detail,
            )
        if not candidate_details and looks_like_generated_alias(config, request.model):
            candidate_details.append(
                {
                    "provider": "alias",
                    "model": request.model,
                    "status": "skipped",
                    "reason": "generated_alias_not_available",
                }
            )

        if not candidate_details:
            for candidate in self._diagnostic_candidates(config, request, candidates, generated_aliases):
                provider = config.providers.get(candidate.provider)
                if provider is None:
                    candidate_details.append(self._candidate_detail(candidate, "skipped", "provider_not_configured"))
                elif not provider.enabled:
                    candidate_details.append(self._candidate_detail(candidate, "skipped", "provider_disabled"))
                else:
                    candidate_details.append(self._candidate_detail(candidate, "skipped", "no_available_keys", 0))
        raise GatewayError(
            message="No healthy route candidates available for stream",
            error_class=ErrorClass.PROVIDER_UNAVAILABLE,
            status_code=503,
            details={
                "analysis": self._analysis_detail(request),
                "route_memory": route_memory_detail,
                "candidates": candidate_details,
                "attempts": self._attempts_detail(decision),
                "free_alias": free_alias_detail,
            },
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
