"""Capability enrichment for discovered inventory models."""

from __future__ import annotations

from app.inventory.models import CapabilityState, DiscoveredModel, ModelClassification


def enrich_model_capabilities(model: DiscoveredModel, classification: ModelClassification) -> DiscoveredModel:
    notes: list[str] = []

    if model.is_text_candidate and not model.excluded_reason and model.supports_chat:
        model.chat_state = "supported"
        notes.append("chat:text_candidate")
    else:
        model.chat_state = "unsupported"

    if model.is_text_candidate and not model.excluded_reason and model.supports_responses:
        model.responses_state = "supported"
        notes.append("responses:text_candidate")
    else:
        model.responses_state = "unsupported"

    if model.is_text_candidate and not model.excluded_reason and model.supports_stream:
        model.stream_state = "supported"
        notes.append("stream:text_candidate")
    else:
        model.stream_state = "unsupported"

    model.tools_state = _tools_state(model, classification)
    if model.tools_state == "supported":
        notes.append("tools:tool_capable")
    elif model.tools_state == "unsupported":
        notes.append("tools:tool_disabled_or_missing")

    model.capability_notes = notes
    return model


def _tools_state(model: DiscoveredModel, classification: ModelClassification) -> CapabilityState:
    if not model.is_text_candidate or model.excluded_reason:
        return "unsupported"
    if classification.tool_disabled:
        return "unsupported"
    if classification.tool_capable or model.supports_tools:
        return "supported"
    return "unknown"
