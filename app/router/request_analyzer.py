"""Lightweight local request analysis for adaptive routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.types import UnifiedLLMRequest, stringify_content

TaskProfile = Literal["fast", "balanced", "strong", "code"]
RequestIntent = Literal["trivial", "light", "standard", "planning", "analysis", "code", "critical"]
ContextBucket = Literal["small", "medium", "large", "huge"]

PROFILE_ALIASES: dict[str, TaskProfile] = {
    "fast": "fast",
    "light": "fast",
    "balanced": "balanced",
    "general": "balanced",
    "standard": "balanced",
    "strong": "strong",
    "reasoning": "strong",
    "deep": "strong",
    "code": "code",
}

TRIVIAL_HINTS = {
    "hello",
    "hi",
    "ping",
    "smoke",
    "test",
    "\u043f\u0440\u0438\u0432\u0435\u0442",
}

LIGHT_HINTS = {
    "translate",
    "rewrite",
    "grammar",
    "summarize briefly",
    "briefly summarize",
    "short summary",
    "\u043f\u0435\u0440\u0435\u0432\u0435\u0434\u0438",
    "\u043f\u0435\u0440\u0435\u043f\u0438\u0448\u0438",
    "\u043a\u0440\u0430\u0442\u043a\u043e",
}

PLANNING_HINTS = {
    "plan",
    "roadmap",
    "steps",
    "implementation",
    "migration",
    "strategy",
    "design approach",
    "\u043f\u043b\u0430\u043d",
    "\u044d\u0442\u0430\u043f",
    "\u043c\u0438\u0433\u0440\u0430\u0446",
    "\u0441\u0442\u0440\u0430\u0442\u0435\u0433",
}

ARCHITECTURE_HINTS = {
    "architecture",
    "architect",
    "scalability",
    "gateway",
    "database",
    "auth",
    "system design",
    "\u0430\u0440\u0445\u0438\u0442\u0435\u043a\u0442",
    "\u0441\u043f\u0440\u043e\u0435\u043a\u0442",
    "\u043c\u0430\u0441\u0448\u0442\u0430\u0431",
}

ANALYSIS_HINTS = {
    "analyze",
    "analysis",
    "compare",
    "evaluate",
    "tradeoff",
    "investigate",
    "optimize",
    "research",
    "\u043f\u0440\u043e\u0430\u043d\u0430\u043b\u0438\u0437",
    "\u0441\u0440\u0430\u0432\u043d",
    "\u043e\u0446\u0435\u043d",
    "\u0440\u0438\u0441\u043a",
}

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
    "\u043e\u0448\u0438\u0431\u043a",
    "\u0440\u0435\u0444\u0430\u043a\u0442\u043e\u0440",
}

CRITICAL_HINTS = {
    "security",
    "payment",
    "billing",
    "production",
    "incident",
    "data loss",
    "credentials",
    "secret",
    "\u0431\u0435\u0437\u043e\u043f\u0430\u0441",
    "\u043f\u043b\u0430\u0442\u0435\u0436",
    "\u043f\u0440\u043e\u0434",
}

CONSTRAINT_HINTS = {
    "must",
    "should",
    "without",
    "with minimal",
    "requirements",
    "constraints",
    "\u043d\u0443\u0436\u043d\u043e",
    "\u0443\u0447\u0442\u0438",
    "\u0431\u0435\u0437 ",
}


@dataclass(slots=True)
class RequestRouteAnalysis:
    intent: RequestIntent
    profile: TaskProfile
    complexity_score: int
    context_bucket: ContextBucket
    token_estimate: int
    requires_tools: bool = False
    reasons: list[str] = field(default_factory=list)


def analyze_request_route(request: UnifiedLLMRequest) -> RequestRouteAnalysis:
    explicit = _explicit_profile(request)
    text = _normalized_request_text(request)
    token_estimate = estimate_request_tokens(request)
    requires_tools = request_uses_tools(request)
    reasons: list[str] = []

    if explicit is not None:
        reasons.append(f"explicit_profile:{explicit}")
        return RequestRouteAnalysis(
            intent="code" if explicit == "code" else "standard",
            profile=explicit,
            complexity_score=50 if explicit in {"strong", "code"} else 20,
            context_bucket=context_bucket(token_estimate),
            token_estimate=token_estimate,
            requires_tools=requires_tools,
            reasons=reasons,
        )

    counts = {
        "trivial": _count_hits(text, TRIVIAL_HINTS, "trivial", reasons),
        "light": _count_hits(text, LIGHT_HINTS, "light", reasons),
        "planning": _count_hits(text, PLANNING_HINTS, "planning", reasons),
        "architecture": _count_hits(text, ARCHITECTURE_HINTS, "architecture", reasons),
        "analysis": _count_hits(text, ANALYSIS_HINTS, "analysis", reasons),
        "code": _count_hits(text, CODE_HINTS, "code", reasons),
        "critical": _count_hits(text, CRITICAL_HINTS, "critical", reasons),
        "constraints": _count_hits(text, CONSTRAINT_HINTS, "constraint", reasons),
    }
    score = _complexity_score(counts, token_estimate, request.max_tokens or 0, requires_tools, reasons)
    intent = _classify_intent(text, counts, score, requires_tools)
    profile = _profile_for_intent(intent, score, token_estimate)
    return RequestRouteAnalysis(
        intent=intent,
        profile=profile,
        complexity_score=score,
        context_bucket=context_bucket(token_estimate),
        token_estimate=token_estimate,
        requires_tools=requires_tools,
        reasons=reasons[:10],
    )


def request_uses_tools(request: UnifiedLLMRequest) -> bool:
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


def context_bucket(token_estimate: int) -> ContextBucket:
    if token_estimate < 8_000:
        return "small"
    if token_estimate < 32_000:
        return "medium"
    if token_estimate < 128_000:
        return "large"
    return "huge"


def _explicit_profile(request: UnifiedLLMRequest) -> TaskProfile | None:
    raw = request.metadata.get("sor_profile") or request.metadata.get("task_profile")
    if not isinstance(raw, str):
        return None
    return PROFILE_ALIASES.get(raw.strip().lower())


def _normalized_request_text(request: UnifiedLLMRequest) -> str:
    parts = [stringify_content(message.content) for message in request.messages]
    parts.append(_stringify_input(request.input))
    parts.append(_stringify_input(request.extra_body.get("instructions")))
    return "\n".join(part for part in parts if part).lower()


def _stringify_input(value: Any) -> str:
    return stringify_content(value)


def _count_hits(text: str, hints: set[str], label: str, reasons: list[str]) -> int:
    count = 0
    for hint in hints:
        if hint in text:
            count += 1
            if len(reasons) < 10:
                reasons.append(f"{label}:{hint}")
    return count


def _complexity_score(
    counts: dict[str, int],
    token_estimate: int,
    max_tokens: int,
    requires_tools: bool,
    reasons: list[str],
) -> int:
    score = 20
    score -= 40 if counts["trivial"] else 0
    score -= 20 if counts["light"] else 0
    score += 30 if counts["planning"] else 0
    score += 35 if counts["architecture"] else 0
    score += 25 if counts["analysis"] else 0
    score += 30 if counts["code"] else 0
    score += 45 if counts["critical"] else 0
    score += 45 if requires_tools else 0
    score += 15 if counts["constraints"] >= 2 else 0
    score += 30 if token_estimate >= 128_000 else 15 if token_estimate >= 32_000 else 0
    score += 25 if max_tokens >= 8_000 else 10 if max_tokens >= 2_500 else 0
    if requires_tools and len(reasons) < 10:
        reasons.append("tools:present")
    return max(0, min(100, score))


def _classify_intent(
    text: str,
    counts: dict[str, int],
    score: int,
    requires_tools: bool,
) -> RequestIntent:
    if requires_tools or counts["code"] >= 2:
        return "code"
    if counts["critical"]:
        return "critical"
    if counts["planning"] or counts["architecture"]:
        return "planning"
    if counts["analysis"]:
        return "analysis"
    if counts["trivial"] and score <= 10 and len(text) < 80:
        return "trivial"
    if counts["light"] and score <= 25:
        return "light"
    return "standard"


def _profile_for_intent(intent: RequestIntent, score: int, token_estimate: int) -> TaskProfile:
    if intent == "code":
        return "code"
    if intent == "critical":
        return "strong"
    if intent in {"planning", "analysis"}:
        return "strong" if score >= 55 or token_estimate >= 32_000 else "balanced"
    if intent in {"trivial", "light"}:
        return "fast"
    if score >= 66 or token_estimate >= 128_000:
        return "strong"
    if score >= 36 or token_estimate >= 32_000:
        return "balanced"
    return "balanced"
