"""Manual override helpers for runtime inventory."""

from __future__ import annotations

from fnmatch import fnmatch

from app.config.models import InventoryOverrideConfig, ModelCapabilitiesConfig
from app.inventory.models import DiscoveredModel, ModelClassification

_CATEGORY_SCORE_FIELDS = {
    "free": "free_score",
    "fast": "fast_score",
    "general": "general_score",
    "reasoning": "reasoning_score",
    "code": "code_score",
}


def apply_model_overrides(model: DiscoveredModel, overrides: list[InventoryOverrideConfig]) -> DiscoveredModel:
    matched_reasons: list[str] = []
    for override in overrides:
        if not _override_matches(model.provider, model.model_id, override):
            continue
        if override.force_modality is not None:
            model.modality = override.force_modality
            if model.modality == "text":
                model.is_text_candidate = True
                model.supports_chat = True
                model.supports_responses = True
                model.supports_stream = True
                if model.excluded_reason and model.excluded_reason.startswith("non_text_modality:"):
                    model.excluded_reason = None
            else:
                model.is_text_candidate = False
                model.supports_chat = False
                model.supports_responses = False
                model.supports_stream = False
                model.excluded_reason = f"manual_override_modality:{model.modality}"
        if override.force_include and model.modality == "text":
            model.is_text_candidate = True
            model.excluded_reason = None
        if override.force_exclude:
            model.is_text_candidate = False
            model.excluded_reason = "manual_override_exclude"
        if override.reason:
            matched_reasons.append(override.reason)
    if matched_reasons:
        model.raw_metadata["override_reasons"] = matched_reasons
    return model


def apply_classification_overrides(
    classification: ModelClassification,
    model: DiscoveredModel,
    overrides: list[InventoryOverrideConfig],
    capabilities: ModelCapabilitiesConfig,
) -> ModelClassification:
    reasons: list[str] = []
    normalized_model = model.model_id.lower()

    if any(pattern.lower() in normalized_model for pattern in capabilities.tool_capable):
        classification.tool_capable = True
        reasons.append("tool_capable_patterns")
    if any(pattern.lower() in normalized_model for pattern in capabilities.tool_disabled):
        classification.tool_disabled = True
        reasons.append("tool_disabled_patterns")

    for override in overrides:
        if not _override_matches(model.provider, model.model_id, override):
            continue
        if override.force_include and model.modality == "text" and classification.general_score == 0:
            classification.general_score = 1
            reasons.append("override:force_include")
        if override.force_exclude:
            reasons.append("override:force_exclude")
        for category in override.force_categories:
            field_name = _CATEGORY_SCORE_FIELDS[category]
            current = getattr(classification, field_name)
            setattr(classification, field_name, max(current, 100))
            reasons.append(f"override:category:{category}")
        if override.force_tool_capable is True:
            classification.tool_capable = True
            classification.tool_disabled = False
            reasons.append("override:tool_capable")
        elif override.force_tool_capable is False:
            classification.tool_capable = False
            reasons.append("override:not_tool_capable")
        if override.force_tool_disabled is True:
            classification.tool_disabled = True
            reasons.append("override:tool_disabled")
        elif override.force_tool_disabled is False:
            classification.tool_disabled = False
            reasons.append("override:not_tool_disabled")

    classification.classification_tags = _rebuild_tags(classification, model)
    if reasons:
        suffix = ", ".join(reasons)
        classification.classification_reason = (
            f"{classification.classification_reason}, {suffix}"
            if classification.classification_reason
            else suffix
        )
    return classification


def _override_matches(provider: str, model_id: str, override: InventoryOverrideConfig) -> bool:
    provider_pattern = (override.provider or "*").lower()
    return fnmatch(provider.lower(), provider_pattern) and fnmatch(model_id.lower(), override.model_pattern.lower())


def _rebuild_tags(classification: ModelClassification, model: DiscoveredModel) -> list[str]:
    tags: list[str] = []
    if classification.free_score > 0:
        tags.append("free")
    if classification.fast_score > 0:
        tags.append("fast")
    if classification.general_score > 0:
        tags.append("general")
    if classification.reasoning_score > 0:
        tags.append("reasoning")
    if classification.code_score > 0:
        tags.append("code")
    if classification.tool_capable and not classification.tool_disabled:
        tags.append("tool_capable")
    if classification.tool_disabled:
        tags.append("tool_disabled")
    if model.excluded_reason:
        tags.append("excluded")
    return tags
