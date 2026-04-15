"""Data structures for runtime provider model inventory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Modality = Literal["text", "image", "video", "audio", "embedding", "other"]
AliasScope = Literal["provider", "global", "compat"]
CapabilityState = Literal["supported", "unknown", "unsupported"]


@dataclass(slots=True)
class DiscoveredModel:
    provider: str
    model_id: str
    display_name: str
    source_key_ids: list[str] = field(default_factory=list)
    modality: Modality = "other"
    supports_chat: bool = False
    supports_responses: bool = False
    supports_stream: bool = False
    supports_tools: bool = False
    is_free: bool = False
    is_preview: bool = False
    is_special: bool = False
    is_deprecated: bool = False
    is_text_candidate: bool = False
    excluded_reason: str | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_context_tokens: int | None = None
    chat_state: CapabilityState = "unknown"
    responses_state: CapabilityState = "unknown"
    stream_state: CapabilityState = "unknown"
    tools_state: CapabilityState = "unknown"
    capability_notes: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DiscoveredModel":
        return cls(**data)


@dataclass(slots=True)
class ProviderSpecialRoute:
    provider: str
    route_id: str
    modality: Modality
    supports_chat: bool
    supports_tools: bool
    category_hints: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderSpecialRoute":
        return cls(**data)


@dataclass(slots=True)
class ModelClassification:
    provider: str
    model_id: str
    modality: Modality
    free_score: int = 0
    fast_score: int = 0
    general_score: int = 0
    reasoning_score: int = 0
    code_score: int = 0
    tool_capable: bool = False
    tool_disabled: bool = False
    classification_tags: list[str] = field(default_factory=list)
    classification_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelClassification":
        return cls(**data)


@dataclass(slots=True)
class GeneratedAliasCandidate:
    provider: str
    model_id: str
    candidate_type: str = "model"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeneratedAliasCandidate":
        return cls(**data)


@dataclass(slots=True)
class GeneratedAlias:
    alias_id: str
    scope: AliasScope
    modality: Modality
    category: str
    provider_scope: str | None = None
    candidates: list[GeneratedAliasCandidate] = field(default_factory=list)
    generation_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias_id": self.alias_id,
            "scope": self.scope,
            "modality": self.modality,
            "category": self.category,
            "provider_scope": self.provider_scope,
            "candidates": [item.to_dict() for item in self.candidates],
            "generation_reason": self.generation_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeneratedAlias":
        payload = dict(data)
        payload["candidates"] = [
            GeneratedAliasCandidate.from_dict(item)
            for item in payload.get("candidates", [])
            if isinstance(item, dict)
        ]
        return cls(**payload)


@dataclass(slots=True)
class InventoryKeyResult:
    provider: str
    key_id: str
    status: str
    discovered_models: int
    latency_ms: float | None
    error_code: str | None
    error_message: str | None
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InventoryKeyResult":
        return cls(**data)


@dataclass(slots=True)
class InventorySnapshot:
    refreshed_at: str
    key_results: list[InventoryKeyResult] = field(default_factory=list)
    models: list[DiscoveredModel] = field(default_factory=list)
    special_routes: list[ProviderSpecialRoute] = field(default_factory=list)
    classifications: list[ModelClassification] = field(default_factory=list)
    generated_aliases: list[GeneratedAlias] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "refreshed_at": self.refreshed_at,
            "key_results": [item.to_dict() for item in self.key_results],
            "models": [item.to_dict() for item in self.models],
            "special_routes": [item.to_dict() for item in self.special_routes],
            "classifications": [item.to_dict() for item in self.classifications],
            "generated_aliases": [item.to_dict() for item in self.generated_aliases],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InventorySnapshot":
        return cls(
            refreshed_at=str(data.get("refreshed_at", "")),
            key_results=[
                InventoryKeyResult.from_dict(item)
                for item in data.get("key_results", [])
                if isinstance(item, dict)
            ],
            models=[
                DiscoveredModel.from_dict(item)
                for item in data.get("models", [])
                if isinstance(item, dict)
            ],
            special_routes=[
                ProviderSpecialRoute.from_dict(item)
                for item in data.get("special_routes", [])
                if isinstance(item, dict)
            ],
            classifications=[
                ModelClassification.from_dict(item)
                for item in data.get("classifications", [])
                if isinstance(item, dict)
            ],
            generated_aliases=[
                GeneratedAlias.from_dict(item)
                for item in data.get("generated_aliases", [])
                if isinstance(item, dict)
            ],
        )
