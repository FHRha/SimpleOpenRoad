"""Registry for provider-defined special routes."""

from __future__ import annotations

from app.inventory.models import Modality, ProviderSpecialRoute

_SPECIAL_ROUTES: dict[tuple[str, str], ProviderSpecialRoute] = {
    ("openrouter", "openrouter/free"): ProviderSpecialRoute(
        provider="openrouter",
        route_id="openrouter/free",
        modality="text",
        supports_chat=True,
        supports_tools=False,
        category_hints=["free"],
        notes="OpenRouter provider-defined route for free-tier text models.",
    ),
    ("openrouter", "openrouter/auto"): ProviderSpecialRoute(
        provider="openrouter",
        route_id="openrouter/auto",
        modality="text",
        supports_chat=True,
        supports_tools=False,
        category_hints=["general"],
        notes="OpenRouter provider-defined auto-routing text route.",
    ),
}


def get_special_route(provider: str, route_id: str) -> ProviderSpecialRoute | None:
    route = _SPECIAL_ROUTES.get((provider, route_id.lower()))
    if route is None:
        return None
    return ProviderSpecialRoute(
        provider=route.provider,
        route_id=route.route_id,
        modality=route.modality,
        supports_chat=route.supports_chat,
        supports_tools=route.supports_tools,
        category_hints=list(route.category_hints),
        notes=route.notes,
    )


def is_special_route(provider: str, route_id: str) -> bool:
    return (provider, route_id.lower()) in _SPECIAL_ROUTES


def special_route_modality(provider: str, route_id: str) -> Modality | None:
    route = _SPECIAL_ROUTES.get((provider, route_id.lower()))
    return route.modality if route is not None else None
