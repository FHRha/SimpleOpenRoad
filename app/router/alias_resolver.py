"""Resolve requested model aliases into ordered provider/model candidates."""

from __future__ import annotations

from app.config.models import GatewayConfig, ProviderConfig
from app.core.security import is_configured_secret
from app.core.types import RouteCandidate


def _provider_has_configured_keys(provider: ProviderConfig) -> bool:
    if not provider.enabled:
        return False
    return any(key.active and is_configured_secret(key.key) for key in provider.keys)


def _candidate_provider_is_configured(config: GatewayConfig, candidate: RouteCandidate) -> bool:
    provider = config.providers.get(candidate.provider)
    return bool(provider and _provider_has_configured_keys(provider))


def resolve_candidates(config: GatewayConfig, requested_model: str) -> tuple[list[RouteCandidate], str | None]:
    if requested_model in config.routes.aliases:
        alias_cfg = config.routes.aliases[requested_model]
        return (
            [
                candidate
                for candidate in [RouteCandidate(provider=c.provider, model=c.model) for c in alias_cfg.candidates]
                if _candidate_provider_is_configured(config, candidate)
            ],
            requested_model,
        )

    if "/" in requested_model:
        provider_name, model_name = requested_model.split("/", 1)
        provider = config.providers.get(provider_name)
        if provider and _provider_has_configured_keys(provider):
            return [RouteCandidate(provider=provider_name, model=model_name)], None

    ordered_providers = sorted(
        (
            (name, provider.priority)
            for name, provider in config.providers.items()
            if _provider_has_configured_keys(provider)
        ),
        key=lambda item: item[1],
    )
    return [RouteCandidate(provider=name, model=requested_model) for name, _ in ordered_providers], None
