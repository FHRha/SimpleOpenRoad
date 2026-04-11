"""Centralized model capability heuristics used by routing and planning."""

from __future__ import annotations

from app.config.models import GatewayConfig
from app.core.types import RouteCandidate

def candidate_supports_tools(config: GatewayConfig, candidate: RouteCandidate) -> bool:
    model = candidate.model.lower()
    if any(marker.lower() in model for marker in config.model_capabilities.tool_disabled):
        return False
    return any(marker.lower() in model for marker in config.model_capabilities.tool_capable)
