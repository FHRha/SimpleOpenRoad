"""Lightweight classification and scoring for discovered text models."""

from __future__ import annotations

from app.config.models import InventoryOverrideConfig, ModelCapabilitiesConfig
from app.inventory.models import DiscoveredModel, ModelClassification
from app.inventory.overrides import apply_classification_overrides

FAST_MARKERS = ("nano", "mini", "lite", "flash", "haiku", "small")
REASONING_MARKERS = ("pro", "opus", "sonnet", "thinking", "reasoning", "o1", "o3", "o4")
CODE_MARKERS = ("codex", "coder", "codestral", "devstral", "mercury-coder", "grok-code")
GENERAL_MARKERS = (
    "gpt-4.1",
    "gpt-4o",
    "gpt-5-chat",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "claude-sonnet",
    "qwen-plus",
    "qwen-max",
)
TOOL_DISABLED_MARKERS = ("haiku", "nano")


def classify_model(
    model: DiscoveredModel,
    capabilities: ModelCapabilitiesConfig | None = None,
    overrides: list[InventoryOverrideConfig] | None = None,
) -> ModelClassification:
    normalized = model.model_id.lower()
    free_score = 100 if model.is_free else 0
    fast_score = sum(30 for marker in FAST_MARKERS if marker in normalized)
    reasoning_score = sum(30 for marker in REASONING_MARKERS if marker in normalized)
    code_score = sum(45 for marker in CODE_MARKERS if marker in normalized)
    general_score = 20 if model.is_text_candidate else 0
    general_score += sum(15 for marker in GENERAL_MARKERS if marker in normalized)
    if model.is_text_candidate and general_score == 0:
        general_score = 10

    tool_capable = model.supports_tools or code_score > 0 or "customtools" in normalized
    tool_disabled = any(marker in normalized for marker in TOOL_DISABLED_MARKERS)

    tags: list[str] = []
    if free_score > 0:
        tags.append("free")
    if fast_score > 0:
        tags.append("fast")
    if general_score > 0:
        tags.append("general")
    if reasoning_score > 0:
        tags.append("reasoning")
    if code_score > 0:
        tags.append("code")
    if tool_capable and not tool_disabled:
        tags.append("tool_capable")
    if tool_disabled:
        tags.append("tool_disabled")
    if model.excluded_reason:
        tags.append("excluded")

    reason_parts: list[str] = []
    if model.is_free:
        reason_parts.append("free_suffix")
    if fast_score:
        reason_parts.append("fast_markers")
    if reasoning_score:
        reason_parts.append("reasoning_markers")
    if code_score:
        reason_parts.append("code_markers")
    if general_score:
        reason_parts.append("general_text_candidate")
    if model.excluded_reason:
        reason_parts.append(f"excluded:{model.excluded_reason}")

    classification = ModelClassification(
        provider=model.provider,
        model_id=model.model_id,
        modality=model.modality,
        free_score=free_score,
        fast_score=fast_score,
        general_score=general_score,
        reasoning_score=reasoning_score,
        code_score=code_score,
        tool_capable=tool_capable,
        tool_disabled=tool_disabled,
        classification_tags=tags,
        classification_reason=", ".join(reason_parts) or "unclassified",
    )
    if capabilities is None:
        return classification
    return apply_classification_overrides(
        classification=classification,
        model=model,
        overrides=overrides or [],
        capabilities=capabilities,
    )
