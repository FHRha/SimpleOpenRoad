"""Lightweight model candidate planning for adaptive aliases."""

from __future__ import annotations

from typing import Any, Literal

from app.config.models import GatewayConfig
from app.core.types import RouteCandidate, UnifiedLLMRequest, stringify_content
from app.router.alias_resolver import resolve_candidates

TaskProfile = Literal["fast", "balanced", "strong", "code"]

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


def _candidate_supports_tools(candidate: RouteCandidate) -> bool:
    model = candidate.model.lower()
    provider = candidate.provider.lower()
    if provider == "gemini":
        return "customtools" in model
    return any(
        marker in model
        for marker in (
            "codex",
            "coder",
            "grok-code",
            "customtools",
            "kimi-k2.5",
            "gpt-5.",
            "gpt-4.1",
            "gpt-4o",
            "claude",
            "qwen",
        )
    )


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
    if token_estimate >= 24000 or (request.max_tokens or 0) >= 8000 or strong_hits >= 3:
        return "strong"
    if token_estimate >= 6000 or (request.max_tokens or 0) >= 2500 or strong_hits >= 1:
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


def _rank_adaptive_candidates(candidates: list[RouteCandidate], profile: TaskProfile) -> list[RouteCandidate]:
    tool_capable = [candidate for candidate in candidates if _candidate_supports_tools(candidate)]
    if profile == "code" and tool_capable:
        candidates = tool_capable
    return sorted(
        candidates,
        key=lambda candidate: (
            0 if profile != "code" else int(not _candidate_supports_tools(candidate)),
            -PROFILE_SCORE[profile][classify_candidate_profile(candidate)],
        ),
    )


def plan_candidates(config: GatewayConfig, request: UnifiedLLMRequest) -> tuple[list[RouteCandidate], str | None]:
    candidates, alias = resolve_candidates(config, request.model)
    if not alias:
        return candidates, alias

    alias_config = config.routes.aliases.get(alias)
    if alias_config is None or alias_config.selection != "adaptive":
        return candidates, alias

    return _rank_adaptive_candidates(candidates, classify_request_profile(request)), alias
