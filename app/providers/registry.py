"""Provider adapter registry and factory."""

from __future__ import annotations

from app.config.models import GatewayConfig
from app.providers.base import ProviderAdapter
from app.providers.gemini import GeminiAdapter
from app.providers.github_models import GitHubModelsAdapter
from app.providers.openrouter import OpenRouterAdapter


def build_provider_registry(config: GatewayConfig) -> dict[str, ProviderAdapter]:
    adapters: dict[str, ProviderAdapter] = {}
    for name, provider_cfg in config.providers.items():
        if not provider_cfg.enabled:
            continue
        if name == "gemini":
            adapters[name] = GeminiAdapter(provider_cfg)
        elif name == "github":
            adapters[name] = GitHubModelsAdapter(provider_cfg)
        elif name == "openrouter":
            adapters[name] = OpenRouterAdapter(provider_cfg)
        else:
            # Unknown providers are ignored until an adapter is registered.
            continue
    return adapters
