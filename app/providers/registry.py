"""Provider adapter registry and factory."""

from __future__ import annotations

from app.config.models import GatewayConfig
from app.providers.base import ProviderAdapter
from app.providers.cerebras import CerebrasAdapter
from app.providers.cloudflare_workers_ai import CloudflareWorkersAIAdapter
from app.providers.gemini import GeminiAdapter
from app.providers.github_models import GitHubModelsAdapter
from app.providers.groq import GroqAdapter
from app.providers.openrouter import OpenRouterAdapter
from app.providers.together import TogetherAdapter


def build_provider_registry(config: GatewayConfig) -> dict[str, ProviderAdapter]:
    adapters: dict[str, ProviderAdapter] = {}
    for name, provider_cfg in config.providers.items():
        if not provider_cfg.enabled:
            continue
        if name == "gemini":
            adapters[name] = GeminiAdapter(provider_cfg)
        elif name == "github":
            adapters[name] = GitHubModelsAdapter(provider_cfg)
        elif name == "groq":
            adapters[name] = GroqAdapter(provider_cfg)
        elif name == "together":
            adapters[name] = TogetherAdapter(provider_cfg)
        elif name == "cerebras":
            adapters[name] = CerebrasAdapter(provider_cfg)
        elif name == "cloudflare":
            adapters[name] = CloudflareWorkersAIAdapter(provider_cfg)
        elif name == "openrouter":
            adapters[name] = OpenRouterAdapter(provider_cfg)
        else:
            # Unknown providers are ignored until an adapter is registered.
            continue
    return adapters
