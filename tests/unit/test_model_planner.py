from app.config.models import GatewayConfig
from app.core.types import ChatMessage, RouteCandidate, UnifiedLLMRequest
from app.inventory.models import GeneratedAlias, GeneratedAliasCandidate
from app.router.model_capabilities import candidate_supports_tools
from app.router.model_planner import classify_request_profile, plan_candidates


def _adaptive_config() -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            "providers": {
                "gemini": {
                    "enabled": True,
                    "priority": 10,
                    "endpoint": "https://example.invalid",
                    "keys": [{"id": "gemini-main", "key": "k"}],
                },
                "openrouter": {
                    "enabled": True,
                    "priority": 20,
                    "endpoint": "https://example.invalid",
                    "keys": [{"id": "openrouter-main", "key": "k"}],
                },
            },
            "routes": {
                "aliases": {
                    "custom/adaptive": {
                        "strategy": "strict_priority",
                        "selection": "adaptive",
                        "candidates": [
                            {"provider": "openrouter", "model": "openai/gpt-5.3-codex"},
                            {"provider": "openrouter", "model": "openai/gpt-5.4-pro"},
                            {"provider": "openrouter", "model": "openai/gpt-5.4-nano"},
                            {"provider": "gemini", "model": "gemini-3-flash-preview"},
                        ],
                    }
                }
            },
        }
    )


def test_adaptive_planner_prefers_fast_model_for_small_request() -> None:
    cfg = _adaptive_config()
    request = UnifiedLLMRequest(
        model="custom/adaptive",
        messages=[ChatMessage(role="user", content="Summarize: hello")],
    )

    candidates, alias = plan_candidates(cfg, request)

    assert alias == "custom/adaptive"
    assert candidates[0].provider == "openrouter"
    assert candidates[0].model == "openai/gpt-5.4-nano"


def test_adaptive_planner_prefers_codex_for_code_request() -> None:
    cfg = _adaptive_config()
    request = UnifiedLLMRequest(
        model="custom/adaptive",
        messages=[
            ChatMessage(
                role="user",
                content="Debug this pytest traceback and refactor the Python function:\n```python\nimport os\n```",
            )
        ],
    )

    candidates, alias = plan_candidates(cfg, request)

    assert alias == "custom/adaptive"
    assert candidates[0].provider == "openrouter"
    assert candidates[0].model == "openai/gpt-5.3-codex"


def test_adaptive_planner_prefers_strong_model_for_large_analysis() -> None:
    cfg = _adaptive_config()
    request = UnifiedLLMRequest(
        model="custom/adaptive",
        messages=[ChatMessage(role="user", content="Analyze architecture tradeoffs. " * 1000)],
        max_tokens=9000,
    )

    candidates, alias = plan_candidates(cfg, request)

    assert alias == "custom/adaptive"
    assert candidates[0].provider == "openrouter"
    assert candidates[0].model == "openai/gpt-5.4-pro"


def test_request_profile_can_be_overridden_by_metadata() -> None:
    request = UnifiedLLMRequest(
        model="custom/adaptive",
        messages=[ChatMessage(role="user", content="hello")],
        metadata={"sor_profile": "code"},
    )

    assert classify_request_profile(request) == "code"


def test_adaptive_planner_prefers_tool_capable_candidate_for_tool_request() -> None:
    cfg = _adaptive_config()
    request = UnifiedLLMRequest(
        model="custom/adaptive",
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "read_file", "parameters": {"type": "object", "properties": {}}},
                }
            ]
        },
    )

    candidates, alias = plan_candidates(cfg, request)

    assert alias == "custom/adaptive"
    assert candidates[0].provider == "openrouter"
    assert candidates[0].model == "openai/gpt-5.3-codex"


def test_adaptive_planner_avoids_gemini_pro_for_gemini_only_tool_request() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "providers": {
                "gemini": {
                    "enabled": True,
                    "priority": 10,
                    "endpoint": "https://example.invalid",
                    "keys": [{"id": "gemini-main", "key": "k"}],
                }
            },
            "routes": {
                "aliases": {
                        "custom/adaptive": {
                        "strategy": "strict_priority",
                        "selection": "adaptive",
                        "candidates": [
                            {"provider": "gemini", "model": "gemini-2.5-flash"},
                            {"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"},
                            {"provider": "gemini", "model": "gemini-3-flash-preview"},
                            {"provider": "gemini", "model": "gemini-3.1-pro-preview"},
                        ],
                    }
                }
            },
        }
    )
    request = UnifiedLLMRequest(
        model="custom/adaptive",
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "read_file", "parameters": {"type": "object", "properties": {}}},
                }
            ]
        },
    )

    candidates, alias = plan_candidates(cfg, request)

    assert alias == "custom/adaptive"
    assert candidates[0].provider == "gemini"
    assert candidates[0].model in {"gemini-2.5-flash", "gemini-3.1-flash-lite-preview"}


def test_model_capabilities_are_centralized_not_provider_special_cased() -> None:
    cfg = GatewayConfig()
    assert candidate_supports_tools(cfg, RouteCandidate(provider="openrouter", model="openai/gpt-5.3-codex")) is True
    assert candidate_supports_tools(cfg, RouteCandidate(provider="github", model="gpt-4.1-mini")) is True
    assert candidate_supports_tools(cfg, RouteCandidate(provider="gemini", model="gemini-2.5-flash")) is False
    assert candidate_supports_tools(cfg, RouteCandidate(provider="openrouter", model="anthropic/claude-haiku-4.5")) is False


def test_generated_alias_planner_adapts_candidate_order_for_small_request() -> None:
    cfg = _adaptive_config()
    generated_alias = GeneratedAlias(
        alias_id="auto/reasoning",
        scope="compat",
        modality="text",
        category="reasoning",
        candidates=[
            GeneratedAliasCandidate(provider="openrouter", model_id="openai/gpt-5.4-pro"),
            GeneratedAliasCandidate(provider="openrouter", model_id="openai/gpt-5.4-nano"),
            GeneratedAliasCandidate(provider="openrouter", model_id="anthropic/claude-sonnet-4.6"),
        ],
    )
    request = UnifiedLLMRequest(
        model="auto/reasoning",
        messages=[ChatMessage(role="user", content="hello")],
    )

    candidates, alias = plan_candidates(cfg, request, generated_aliases=[generated_alias])

    assert alias == "auto/reasoning"
    assert candidates[0].model == "openai/gpt-5.4-nano"


def test_generated_reasoning_alias_can_use_fast_bucket_for_simple_request() -> None:
    cfg = _adaptive_config()
    generated_aliases = [
        GeneratedAlias(
            alias_id="auto/text/fast",
            scope="global",
            modality="text",
            category="fast",
            candidates=[GeneratedAliasCandidate(provider="openrouter", model_id="openai/gpt-5.4-nano")],
        ),
        GeneratedAlias(
            alias_id="auto/text/general",
            scope="global",
            modality="text",
            category="general",
            candidates=[GeneratedAliasCandidate(provider="openrouter", model_id="openai/gpt-5.4-mini")],
        ),
        GeneratedAlias(
            alias_id="auto/reasoning",
            scope="compat",
            modality="text",
            category="reasoning",
            candidates=[GeneratedAliasCandidate(provider="openrouter", model_id="openai/gpt-5.4-pro")],
        ),
    ]
    request = UnifiedLLMRequest(
        model="auto/reasoning",
        messages=[ChatMessage(role="user", content="hello")],
    )

    candidates, alias = plan_candidates(cfg, request, generated_aliases=generated_aliases)

    assert alias == "auto/reasoning"
    assert [candidate.model for candidate in candidates[:3]] == [
        "openai/gpt-5.4-nano",
        "openai/gpt-5.4-mini",
        "openai/gpt-5.4-pro",
    ]


def test_generated_reasoning_alias_keeps_reasoning_floor_for_short_planning_request() -> None:
    cfg = _adaptive_config()
    generated_aliases = [
        GeneratedAlias(
            alias_id="auto/text/fast",
            scope="global",
            modality="text",
            category="fast",
            candidates=[GeneratedAliasCandidate(provider="openrouter", model_id="openai/gpt-5.4-nano")],
        ),
        GeneratedAlias(
            alias_id="auto/text/general",
            scope="global",
            modality="text",
            category="general",
            candidates=[GeneratedAliasCandidate(provider="openrouter", model_id="openai/gpt-5.4-mini")],
        ),
        GeneratedAlias(
            alias_id="auto/text/reasoning",
            scope="global",
            modality="text",
            category="reasoning",
            candidates=[GeneratedAliasCandidate(provider="openrouter", model_id="openai/gpt-5.4-pro")],
        ),
        GeneratedAlias(
            alias_id="auto/reasoning",
            scope="compat",
            modality="text",
            category="reasoning",
            candidates=[GeneratedAliasCandidate(provider="openrouter", model_id="openai/gpt-5.4-pro")],
        ),
    ]
    request = UnifiedLLMRequest(
        model="auto/reasoning",
        messages=[ChatMessage(role="user", content="Make an auth migration plan")],
    )

    candidates, alias = plan_candidates(cfg, request, generated_aliases=generated_aliases)

    assert alias == "auto/reasoning"
    assert candidates[0].model == "openai/gpt-5.4-pro"
    assert all(candidate.model != "openai/gpt-5.4-nano" for candidate in candidates)


def test_generated_alias_planner_prefers_tool_capable_for_tool_request() -> None:
    cfg = _adaptive_config()
    generated_alias = GeneratedAlias(
        alias_id="auto/code",
        scope="compat",
        modality="text",
        category="code",
        candidates=[
            GeneratedAliasCandidate(provider="gemini", model_id="gemini-3.1-flash-lite-preview"),
            GeneratedAliasCandidate(provider="openrouter", model_id="openai/gpt-5.3-codex"),
        ],
    )
    request = UnifiedLLMRequest(
        model="auto/code",
        messages=[ChatMessage(role="user", content="edit this repository")],
        extra_body={
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "read_file", "parameters": {"type": "object", "properties": {}}},
                }
            ]
        },
    )

    candidates, alias = plan_candidates(cfg, request, generated_aliases=[generated_alias])

    assert alias == "auto/code"
    assert candidates[0].model == "openai/gpt-5.3-codex"


def test_generated_free_alias_never_upgrades_to_paid_reasoning_for_complex_request() -> None:
    cfg = _adaptive_config()
    generated_aliases = [
        GeneratedAlias(
            alias_id="auto/text/free",
            scope="global",
            modality="text",
            category="free",
            candidates=[GeneratedAliasCandidate(provider="openrouter", model_id="openrouter/free")],
        ),
        GeneratedAlias(
            alias_id="auto/text/reasoning",
            scope="global",
            modality="text",
            category="reasoning",
            candidates=[GeneratedAliasCandidate(provider="openrouter", model_id="openai/gpt-5.4-pro")],
        ),
        GeneratedAlias(
            alias_id="auto/free",
            scope="compat",
            modality="text",
            category="free",
            candidates=[GeneratedAliasCandidate(provider="openrouter", model_id="openrouter/free")],
        ),
    ]
    request = UnifiedLLMRequest(
        model="auto/free",
        messages=[ChatMessage(role="user", content="Make a production auth migration plan")],
    )

    candidates, alias = plan_candidates(cfg, request, generated_aliases=generated_aliases)

    assert alias == "auto/free"
    assert [candidate.model for candidate in candidates] == ["openrouter/free"]


def test_generated_free_cheap_alias_uses_free_then_fast_fallback() -> None:
    cfg = _adaptive_config()
    generated_aliases = [
        GeneratedAlias(
            alias_id="auto/text/free",
            scope="global",
            modality="text",
            category="free",
            candidates=[GeneratedAliasCandidate(provider="openrouter", model_id="openrouter/free")],
        ),
        GeneratedAlias(
            alias_id="auto/text/fast",
            scope="global",
            modality="text",
            category="fast",
            candidates=[GeneratedAliasCandidate(provider="github", model_id="gpt-4.1-mini")],
        ),
        GeneratedAlias(
            alias_id="auto/free-cheap",
            scope="compat",
            modality="text",
            category="free-cheap",
            candidates=[
                GeneratedAliasCandidate(provider="openrouter", model_id="openrouter/free"),
                GeneratedAliasCandidate(provider="github", model_id="gpt-4.1-mini"),
            ],
        ),
    ]
    request = UnifiedLLMRequest(
        model="auto/free-cheap",
        messages=[ChatMessage(role="user", content="hello")],
    )

    candidates, alias = plan_candidates(cfg, request, generated_aliases=generated_aliases)

    assert alias == "auto/free-cheap"
    assert [candidate.model for candidate in candidates] == ["openrouter/free", "gpt-4.1-mini"]


def test_missing_generated_alias_is_not_treated_as_direct_provider_model() -> None:
    cfg = _adaptive_config()
    request = UnifiedLLMRequest(
        model="auto/fast",
        messages=[ChatMessage(role="user", content="hello")],
    )

    candidates, alias = plan_candidates(cfg, request, generated_aliases=[])

    assert alias == "auto/fast"
    assert candidates == []


def test_missing_provider_scoped_generated_alias_is_not_treated_as_direct_model() -> None:
    cfg = _adaptive_config()
    request = UnifiedLLMRequest(
        model="openrouter/text/fast",
        messages=[ChatMessage(role="user", content="hello")],
    )

    candidates, alias = plan_candidates(cfg, request, generated_aliases=[])

    assert alias == "openrouter/text/fast"
    assert candidates == []
