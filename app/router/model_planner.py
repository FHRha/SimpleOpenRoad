"""Lightweight model candidate planning for adaptive aliases."""

from __future__ import annotations

from typing import Any, Literal

from app.config.models import GatewayConfig
from app.core.types import RouteCandidate, UnifiedLLMRequest, stringify_content
from app.inventory.models import GeneratedAlias
from app.router.alias_resolver import resolve_candidates
from app.router.model_capabilities import candidate_supports_tools

TaskProfile = Literal["fast", "balanced", "strong", "code"]
GENERATED_TEXT_ALIAS_PREFIX = "auto/text/"
COMPAT_TEXT_ALIASES = {"auto/free", "auto/fast", "auto/general", "auto/reasoning", "auto/code"}

CODE_HINTS = {
    "```",
    "traceback",
    "stack trace",
    "exception",
    "pytest",
    "typescript",
    "javascript",
    "python",
    "golang",
    "rust",
    "react",
    "fastapi",
    "sql",
    "dockerfile",
    "refactor",
    "debug",
    "function",
    "class ",
    "import ",
}

STRONG_HINTS = {
    "architecture",
    "design",
    "analyze",
    "analysis",
    "research",
    "compare",
    "evaluate",
    "optimize",
    "проект",
    "архитект",
    "проанализ",
    "сравни",
    "исслед",
    "оптимиз",
}

PROFILE_SCORE: dict[TaskProfile, dict[TaskProfile, int]] = {
    "fast": {"fast": 100, "balanced": 70, "code": 45, "strong": 30},
    "balanced": {"balanced": 100, "fast": 75, "strong": 70, "code": 60},
    "strong": {"strong": 100, "code": 85, "balanced": 65, "fast": 25},
    "code": {"code": 100, "strong": 85, "balanced": 60, "fast": 25},
}


def _stringify_input(value: Any) -> str:
    return stringify_content(value)


def _request_uses_tools(request: UnifiedLLMRequest) -> bool:
    if request.extra_body.get("tools"):
        return True
    return any(message.role in {"tool", "function"} or bool(message.tool_calls) for message in request.messages)


def estimate_request_tokens(request: UnifiedLLMRequest) -> int:
    text_parts = [stringify_content(message.content) for message in request.messages]
    text_parts.append(_stringify_input(request.input))
    text_parts.append(_stringify_input(request.extra_body.get("instructions")))
    text_parts.extend(str(value) for value in request.metadata.values())
    char_count = sum(len(part) for part in text_parts)
    output_budget = request.max_tokens or 0
    return max(1, char_count // 4) + output_budget


def classify_request_profile(request: UnifiedLLMRequest) -> TaskProfile:
    explicit = request.metadata.get("sor_profile") or request.metadata.get("task_profile")
    if isinstance(explicit, str) and explicit in {"fast", "balanced", "strong", "code"}:
        return explicit  # type: ignore[return-value]

    if _request_uses_tools(request):
        return "code"

    text = "\n".join(
        [
            stringify_content(message.content) for message in request.messages
        ]
        + [_stringify_input(request.input), _stringify_input(request.extra_body.get("instructions"))]
    ).lower()
    token_estimate = estimate_request_tokens(request)
    code_hits = sum(1 for hint in CODE_HINTS if hint in text)
    strong_hits = sum(1 for hint in STRONG_HINTS if hint in text)

    if code_hits >= 2:
        return "code"
    if token_estimate >= 128000 or (request.max_tokens or 0) >= 8000 or strong_hits >= 3:
        return "strong"
    if token_estimate >= 32000 or (request.max_tokens or 0) >= 2500 or strong_hits >= 1:
        return "balanced"
    if code_hits:
        return "code"
    return "fast"


def classify_candidate_profile(candidate: RouteCandidate) -> TaskProfile:
    model = candidate.model.lower()
    if any(marker in model for marker in ("codex", "coder", "grok-code", "customtools", "kimi-k2.5")):
        return "code"
    if any(marker in model for marker in ("nano", "flash-lite", "haiku", "gpt-4.1-mini", "gemini-2.5-flash")):
        return "fast"
    if any(marker in model for marker in ("gpt-5.4-mini", "gemini-3-flash", "sonnet", "qwen3.6", "gpt-4.1")):
        return "balanced"
    if any(marker in model for marker in ("gpt-5.4-pro", "gpt-5.4", "gemini-3.1-pro", "opus", "grok-4.20")):
        return "strong"
    return "balanced"


def _rank_adaptive_candidates(
    config: GatewayConfig,
    candidates: list[RouteCandidate],
    profile: TaskProfile,
) -> list[RouteCandidate]:
    tool_capable = [candidate for candidate in candidates if candidate_supports_tools(config, candidate)]
    if profile == "code" and tool_capable:
        candidates = tool_capable
        code_candidates = [candidate for candidate in candidates if classify_candidate_profile(candidate) == "code"]
        if not code_candidates:
            return candidates
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (
            0 if profile != "code" else int(not candidate_supports_tools(config, item[1])),
            -PROFILE_SCORE[profile][classify_candidate_profile(item[1])],
            item[0],
        ),
    )
    return [candidate for _, candidate in ranked]


def plan_candidates(
    config: GatewayConfig,
    request: UnifiedLLMRequest,
    generated_aliases: list[GeneratedAlias] | None = None,
) -> tuple[list[RouteCandidate], str | None]:
    candidates, alias = resolve_candidates(config, request.model, generated_aliases=generated_aliases)
    if not alias:
        return candidates, alias

    generated_alias = _generated_alias_by_id(generated_aliases or [], alias)
    if generated_alias is not None and _is_adaptive_generated_alias(generated_alias):
        profile = classify_request_profile(request)
        candidates = _adaptive_generated_candidates(generated_aliases or [], generated_alias, profile) or candidates
        if profile == "code" and _request_uses_tools(request):
            tool_capable = [candidate for candidate in candidates if candidate_supports_tools(config, candidate)]
            if tool_capable:
                candidates = tool_capable
            elif candidates:
                profile = "fast"
        return _rank_adaptive_candidates(config, candidates, profile), alias

    alias_config = config.routes.aliases.get(alias)
    if alias_config is None or alias_config.selection != "adaptive":
        return candidates, alias

    profile = classify_request_profile(request)
    if profile == "code" and _request_uses_tools(request):
        tool_capable = [candidate for candidate in candidates if candidate_supports_tools(config, candidate)]
        if tool_capable:
            candidates = tool_capable
        elif candidates:
            profile = "fast"

    return _rank_adaptive_candidates(config, candidates, profile), alias


def _generated_alias_by_id(generated_aliases: list[GeneratedAlias], alias_id: str) -> GeneratedAlias | None:
    return next((item for item in generated_aliases if item.alias_id == alias_id), None)


def _is_adaptive_generated_alias(alias: GeneratedAlias) -> bool:
    if alias.modality != "text":
        return False
    return alias.alias_id in COMPAT_TEXT_ALIASES or alias.alias_id.startswith(GENERATED_TEXT_ALIAS_PREFIX)


def _adaptive_generated_candidates(
    generated_aliases: list[GeneratedAlias],
    requested_alias: GeneratedAlias,
    profile: TaskProfile,
) -> list[RouteCandidate]:
    alias_map = {alias.alias_id: alias for alias in generated_aliases}
    category = _category_for_profile(profile)
    categories = _category_fallbacks(requested_alias.category, category)
    resolved: list[RouteCandidate] = []
    for candidate_alias in _matching_generated_aliases(alias_map, requested_alias, categories):
        for candidate in candidate_alias.candidates:
            resolved.append(RouteCandidate(provider=candidate.provider, model=candidate.model_id))
    return _dedupe_route_candidates(resolved)


def _category_for_profile(profile: TaskProfile) -> str:
    if profile == "balanced":
        return "general"
    if profile == "strong":
        return "reasoning"
    return profile


def _category_fallbacks(requested_category: str, preferred_category: str) -> list[str]:
    if requested_category == "free":
        return ["free"]
    if preferred_category == "code":
        ordered = ["code", "reasoning", "general", requested_category]
    elif preferred_category == "reasoning":
        ordered = ["reasoning", "general", requested_category]
    elif preferred_category == "general":
        ordered = ["general", "fast", requested_category]
    else:
        ordered = ["fast", "general", requested_category]
    return _dedupe_strings(ordered)


def _matching_generated_aliases(
    alias_map: dict[str, GeneratedAlias],
    requested_alias: GeneratedAlias,
    categories: list[str],
) -> list[GeneratedAlias]:
    aliases: list[GeneratedAlias] = []
    if requested_alias.provider_scope:
        for category in categories:
            alias = alias_map.get(f"{requested_alias.provider_scope}/text/{category}")
            if alias is not None:
                aliases.append(alias)
        return aliases

    for category in categories:
        alias = alias_map.get(f"auto/text/{category}") or alias_map.get(f"auto/{category}")
        if alias is not None:
            aliases.append(alias)
    return aliases


def _dedupe_route_candidates(candidates: list[RouteCandidate]) -> list[RouteCandidate]:
    seen: set[tuple[str, str]] = set()
    result: list[RouteCandidate] = []
    for candidate in candidates:
        marker = (candidate.provider, candidate.model)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(candidate)
    return result


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
