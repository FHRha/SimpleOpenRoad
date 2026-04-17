"""Normalization helpers for provider model inventory."""

from __future__ import annotations

from typing import Any

from app.inventory.models import DiscoveredModel, Modality
from app.inventory.special_routes import is_special_route


def guess_modality(model_id: str, raw_metadata: dict[str, Any] | None = None) -> Modality:
    inferred = _modality_from_metadata(raw_metadata or {})
    if inferred is not None:
        return inferred

    normalized = model_id.lower()
    if "embedding" in normalized:
        return "embedding"
    if any(marker in normalized for marker in ("veo", "video", "seedance", "hailuo")):
        return "video"
    if any(marker in normalized for marker in ("image", "imagen")):
        return "image"
    if any(marker in normalized for marker in ("audio", "tts", "lyria", "live", "speech")):
        return "audio"
    if any(marker in normalized for marker in ("robotics", "computer-use", "research", "aqa")):
        return "other"
    return "text"


def supports_tools(model_id: str) -> bool:
    normalized = model_id.lower()
    return any(marker in normalized for marker in ("codex", "coder", "customtools", "grok-code"))


def normalize_discovered_model(
    provider: str,
    model_id: str,
    key_id: str,
    raw_metadata: dict[str, Any] | None = None,
) -> DiscoveredModel:
    modality = guess_modality(model_id, raw_metadata)
    normalized = model_id.lower()
    special = is_special_route(provider, model_id)
    metadata = raw_metadata or {}
    limits = _extract_token_limits(metadata)
    supports_chat = _supports_chat_task(modality, metadata) and not special
    return DiscoveredModel(
        provider=provider,
        model_id=model_id,
        display_name=model_id,
        source_key_ids=[key_id],
        modality=modality,
        supports_chat=supports_chat,
        supports_responses=supports_chat,
        supports_stream=supports_chat,
        supports_tools=supports_tools(model_id),
        is_free=":free" in normalized,
        is_preview="preview" in normalized,
        is_special=special,
        is_text_candidate=supports_chat,
        max_input_tokens=limits["max_input_tokens"],
        max_output_tokens=limits["max_output_tokens"],
        max_context_tokens=limits["max_context_tokens"],
        raw_metadata=metadata,
    )


def _modality_from_metadata(metadata: dict[str, Any]) -> Modality | None:
    hints: list[str] = []
    for key in ("type", "modality"):
        value = metadata.get(key)
        if isinstance(value, str):
            hints.append(value)

    task = metadata.get("task")
    if isinstance(task, dict):
        for key in ("name", "description", "id"):
            value = task.get(key)
            if isinstance(value, str):
                hints.append(value)
    elif isinstance(task, str):
        hints.append(task)

    normalized = " ".join(hints).lower()
    if not normalized:
        return None
    if "embedding" in normalized:
        return "embedding"
    if any(marker in normalized for marker in ("text-to-image", "image generation", "image to text", "vision", "image")):
        return "image"
    if "video" in normalized:
        return "video"
    if any(marker in normalized for marker in ("speech", "audio", "transcription", "asr", "text-to-speech")):
        return "audio"
    if any(marker in normalized for marker in ("text generation", "language", "chat", "summarization", "translation")):
        return "text"
    return None


def _supports_chat_task(modality: Modality, metadata: dict[str, Any]) -> bool:
    if modality != "text":
        return False

    hints: list[str] = []
    for key in ("type", "modality"):
        value = metadata.get(key)
        if isinstance(value, str):
            hints.append(value)

    task = metadata.get("task")
    if isinstance(task, dict):
        for key in ("name", "description", "id"):
            value = task.get(key)
            if isinstance(value, str):
                hints.append(value)
    elif isinstance(task, str):
        hints.append(task)

    normalized = " ".join(hints).lower()
    if not normalized:
        return True
    if any(
        marker in normalized
        for marker in (
            "text generation",
            "language model",
            "large language model",
            "chat",
            "dialogue",
            "instruct",
        )
    ):
        return True
    if any(
        marker in normalized
        for marker in (
            "text classification",
            "summarization",
            "translation",
            "embeddings",
            "automatic speech recognition",
            "speech recognition",
            "rerank",
            "reranker",
            "feature extraction",
        )
    ):
        return False
    return True


def _extract_token_limits(metadata: dict[str, Any]) -> dict[str, int | None]:
    direct_context = _first_int(
        metadata,
        "max_context_tokens",
        "context_length",
        "context_window",
        "context",
        "max_tokens",
    )
    direct_input = _first_int(
        metadata,
        "max_input_tokens",
        "input_token_limit",
        "inputTokenLimit",
        "maxInputTokens",
    )
    direct_output = _first_int(
        metadata,
        "max_output_tokens",
        "output_token_limit",
        "outputTokenLimit",
        "maxOutputTokens",
    )

    limits = metadata.get("limits")
    if isinstance(limits, dict):
        direct_context = direct_context or _first_int(
            limits,
            "max_context_tokens",
            "context_length",
            "context_window",
            "max_tokens",
        )
        direct_input = direct_input or _first_int(
            limits,
            "max_input_tokens",
            "max_input",
            "input_tokens",
            "max_prompt_tokens",
        )
        direct_output = direct_output or _first_int(
            limits,
            "max_output_tokens",
            "max_output",
            "output_tokens",
            "max_completion_tokens",
        )

    top_provider = metadata.get("top_provider")
    if isinstance(top_provider, dict):
        direct_context = direct_context or _first_int(
            top_provider,
            "context_length",
            "max_context_tokens",
            "max_completion_tokens",
        )
    architecture = metadata.get("architecture")
    if isinstance(architecture, dict):
        direct_input = direct_input or _first_int(architecture, "input_token_limit", "max_input_tokens")

    max_context = direct_context or direct_input
    return {
        "max_input_tokens": direct_input,
        "max_output_tokens": direct_output,
        "max_context_tokens": max_context,
    }


def _first_int(data: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, float):
            return int(value) if value > 0 else None
        if isinstance(value, str):
            compact = value.replace("_", "").replace(",", "").strip()
            if compact.isdigit():
                parsed = int(compact)
                return parsed if parsed > 0 else None
    return None
