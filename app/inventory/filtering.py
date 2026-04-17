"""Filtering helpers for discovered inventory models."""

from __future__ import annotations

from app.inventory.models import DiscoveredModel

GLOBAL_TEXT_EXCLUDE_MARKERS: tuple[tuple[str, str], ...] = (
    ("embedding", "embedding_model"),
    ("image", "image_or_vision_model"),
    ("audio", "audio_model"),
    ("speech", "audio_model"),
    ("tts", "audio_model"),
    ("generate", "generation_or_media_model"),
    ("seedance", "video_model"),
    ("hailuo", "video_model"),
    ("veo", "video_model"),
    ("imagen", "image_model"),
    ("lyria", "audio_model"),
    ("robotics", "robotics_model"),
    ("computer-use", "computer_use_model"),
    ("live", "live_or_realtime_model"),
    ("research", "research_model"),
)

PROVIDER_TEXT_EXCLUDE_MARKERS: dict[str, tuple[tuple[str, str], ...]] = {
    "gemini": (
        ("aqa", "non_chat_model"),
    ),
    "openrouter": (
        ("search", "search_or_retrieval_route"),
        ("router", "special_router_route"),
        ("guard", "guard_or_safeguard_model"),
        ("safeguard", "guard_or_safeguard_model"),
        ("bodybuilder", "special_provider_route"),
    ),
}


def apply_text_filter(model: DiscoveredModel) -> DiscoveredModel:
    normalized = model.model_id.lower()

    if model.is_special:
        model.is_text_candidate = False
        model.excluded_reason = "special_route"
        return model

    if model.modality != "text":
        model.is_text_candidate = False
        model.excluded_reason = f"non_text_modality:{model.modality}"
        return model

    for marker, reason in GLOBAL_TEXT_EXCLUDE_MARKERS:
        if marker in normalized:
            model.is_text_candidate = False
            model.excluded_reason = reason
            return model

    for marker, reason in PROVIDER_TEXT_EXCLUDE_MARKERS.get(model.provider, ()):
        if marker in normalized:
            model.is_text_candidate = False
            model.excluded_reason = reason
            return model

    model.is_text_candidate = True
    model.excluded_reason = None
    return model
