from app.config.models import GatewayConfig
from app.core.types import ChatMessage, UnifiedLLMRequest
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
                    "auto/smart": {
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
        model="auto/smart",
        messages=[ChatMessage(role="user", content="Summarize: hello")],
    )

    candidates, alias = plan_candidates(cfg, request)

    assert alias == "auto/smart"
    assert candidates[0].provider == "openrouter"
    assert candidates[0].model == "openai/gpt-5.4-nano"


def test_adaptive_planner_prefers_codex_for_code_request() -> None:
    cfg = _adaptive_config()
    request = UnifiedLLMRequest(
        model="auto/smart",
        messages=[
            ChatMessage(
                role="user",
                content="Debug this pytest traceback and refactor the Python function:\n```python\nimport os\n```",
            )
        ],
    )

    candidates, alias = plan_candidates(cfg, request)

    assert alias == "auto/smart"
    assert candidates[0].provider == "openrouter"
    assert candidates[0].model == "openai/gpt-5.3-codex"


def test_adaptive_planner_prefers_strong_model_for_large_analysis() -> None:
    cfg = _adaptive_config()
    request = UnifiedLLMRequest(
        model="auto/smart",
        messages=[ChatMessage(role="user", content="Analyze architecture tradeoffs. " * 1000)],
        max_tokens=9000,
    )

    candidates, alias = plan_candidates(cfg, request)

    assert alias == "auto/smart"
    assert candidates[0].provider == "openrouter"
    assert candidates[0].model == "openai/gpt-5.4-pro"


def test_request_profile_can_be_overridden_by_metadata() -> None:
    request = UnifiedLLMRequest(
        model="auto/smart",
        messages=[ChatMessage(role="user", content="hello")],
        metadata={"sor_profile": "code"},
    )

    assert classify_request_profile(request) == "code"
