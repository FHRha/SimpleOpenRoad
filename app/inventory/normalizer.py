"""Normalization helpers for provider model inventory."""

from __future__ import annotations

from app.inventory.models import DiscoveredModel, Modality
from app.inventory.special_routes import is_special_route


def guess_modality(model_id: str) -> Modality:
    normalized = model_id.lower()
    if "embedding" in normalized:
        return "embedding"
    if any(marker in normalized for marker in ("veo", "video")):
        return "video"
    if any(marker in normalized for marker in ("image", "imagen")):
        return "image"
    if any(marker in normalized for marker in ("audio", "tts", "lyria", "live")):
        return "audio"
    if any(marker in normalized for marker in ("robotics", "computer-use", "research", "aqa")):
        return "other"
    return "text"


def supports_tools(model_id: str) -> bool:
    normalized = model_id.lower()
    return any(marker in normalized for marker in ("codex", "coder", "customtools", "grok-code"))


def normalize_discovered_model(provider: str, model_id: str, key_id: str) -> DiscoveredModel:
    modality = guess_modality(model_id)
    normalized = model_id.lower()
    special = is_special_route(provider, model_id)
    return DiscoveredModel(
        provider=provider,
        model_id=model_id,
        display_name=model_id,
        source_key_ids=[key_id],
        modality=modality,
        supports_chat=modality == "text" and not special,
        supports_responses=modality == "text" and not special,
        supports_stream=modality == "text" and not special,
        supports_tools=supports_tools(model_id),
        is_free=":free" in normalized,
        is_preview="preview" in normalized,
        is_special=special,
        is_text_candidate=modality == "text" and not special,
    )
