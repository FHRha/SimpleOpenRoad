from app.core.types import ChatMessage, UnifiedLLMRequest
from app.router.request_analyzer import analyze_request_route, context_bucket


def test_analyzer_routes_smoke_prompt_to_fast_trivial() -> None:
    request = UnifiedLLMRequest(model="auto/general", messages=[ChatMessage(role="user", content="hello")])

    analysis = analyze_request_route(request)

    assert analysis.intent == "trivial"
    assert analysis.profile == "fast"
    assert analysis.context_bucket == "small"
    assert any(reason.startswith("trivial:") for reason in analysis.reasons)


def test_analyzer_routes_short_planning_prompt_to_reasoning() -> None:
    request = UnifiedLLMRequest(
        model="auto/general",
        messages=[ChatMessage(role="user", content="Make an auth migration plan for production")],
    )

    analysis = analyze_request_route(request)

    assert analysis.intent in {"planning", "critical"}
    assert analysis.profile == "strong"
    assert analysis.complexity_score >= 55
    assert "small" == analysis.context_bucket


def test_analyzer_routes_tool_request_to_code() -> None:
    request = UnifiedLLMRequest(
        model="auto/general",
        messages=[ChatMessage(role="user", content="read files and edit the repo")],
        extra_body={"tools": [{"type": "function", "function": {"name": "read_file"}}]},
    )

    analysis = analyze_request_route(request)

    assert analysis.intent == "code"
    assert analysis.profile == "code"
    assert analysis.requires_tools is True


def test_analyzer_context_bucket_thresholds() -> None:
    assert context_bucket(7_999) == "small"
    assert context_bucket(8_000) == "medium"
    assert context_bucket(32_000) == "large"
    assert context_bucket(128_000) == "huge"
