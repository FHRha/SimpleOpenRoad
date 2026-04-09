"""Resolve requested model aliases into ordered provider/model candidates."""

from __future__ import annotations

from app.config.models import GatewayConfig
from app.core.types import RouteCandidate


def resolve_candidates(config: GatewayConfig, requested_model: str) -> tuple[list[RouteCandidate], str | None]:
    if requested_model in config.routes.aliases:
        alias_cfg = config.routes.aliases[requested_model]
        return (
            [RouteCandidate(provider=c.provider, model=c.model) for c in alias_cfg.candidates],
            requested_model,
        )

    if "/" in requested_model:
        provider_name, model_name = requested_model.split("/", 1)
        if provider_name in config.providers:
            return [RouteCandidate(provider=provider_name, model=model_name)], None

    ordered_providers = sorted(
        (
            (name, provider.priority)
            for name, provider in config.providers.items()
            if provider.enabled
        ),
        key=lambda item: item[1],
    )
    return [RouteCandidate(provider=name, model=requested_model) for name, _ in ordered_providers], None
