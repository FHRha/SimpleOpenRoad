from __future__ import annotations

from app.config.models import GatewayConfig
from app.providers.cerebras import CerebrasAdapter
from app.providers.cloudflare_workers_ai import CloudflareWorkersAIAdapter
from app.providers.gemini import GeminiAdapter
from app.providers.groq import GroqAdapter
from app.providers.github_models import GitHubModelsAdapter
from app.providers.openrouter import OpenRouterAdapter
from app.providers.registry import build_provider_registry
from app.providers.together import TogetherAdapter


def test_provider_registry_builds_all_supported_adapters() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "providers": {
                "gemini": {"enabled": True, "priority": 10, "endpoint": "https://gemini.invalid"},
                "github": {"enabled": True, "priority": 20, "endpoint": "https://models.github.ai"},
                "groq": {"enabled": True, "priority": 25, "endpoint": "https://api.groq.com/openai/v1"},
                "together": {"enabled": True, "priority": 27, "endpoint": "https://api.together.xyz/v1"},
                "cerebras": {"enabled": True, "priority": 28, "endpoint": "https://api.cerebras.ai/v1"},
                "cloudflare": {
                    "enabled": True,
                    "priority": 29,
                    "endpoint": "https://api.cloudflare.com/client/v4",
                    "account_id": "acc-123",
                },
                "openrouter": {"enabled": True, "priority": 30, "endpoint": "https://openrouter.ai/api/v1"},
            }
        }
    )

    adapters = build_provider_registry(cfg)

    assert isinstance(adapters["gemini"], GeminiAdapter)
    assert isinstance(adapters["github"], GitHubModelsAdapter)
    assert isinstance(adapters["groq"], GroqAdapter)
    assert isinstance(adapters["together"], TogetherAdapter)
    assert isinstance(adapters["cerebras"], CerebrasAdapter)
    assert isinstance(adapters["cloudflare"], CloudflareWorkersAIAdapter)
    assert isinstance(adapters["openrouter"], OpenRouterAdapter)
