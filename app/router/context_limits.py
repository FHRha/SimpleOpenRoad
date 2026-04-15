"""Context limit helpers for route candidate filtering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.types import RouteCandidate
from app.inventory.models import InventorySnapshot


@dataclass(frozen=True, slots=True)
class CandidateContextLimit:
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_context_tokens: int | None = None


def limits_from_snapshot(snapshot: InventorySnapshot | None) -> dict[tuple[str, str], CandidateContextLimit]:
    if snapshot is None:
        return {}
    return {
        (model.provider, model.model_id): CandidateContextLimit(
            max_input_tokens=model.max_input_tokens,
            max_output_tokens=model.max_output_tokens,
            max_context_tokens=model.max_context_tokens,
        )
        for model in snapshot.models
    }


def limits_from_snapshot_dict(snapshot: dict[str, Any] | None) -> dict[tuple[str, str], CandidateContextLimit]:
    if not isinstance(snapshot, dict):
        return {}
    models = snapshot.get("models")
    if not isinstance(models, list):
        return {}
    result: dict[tuple[str, str], CandidateContextLimit] = {}
    for item in models:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider", "")).strip()
        model_id = str(item.get("model_id", "")).strip()
        if not provider or not model_id:
            continue
        result[(provider, model_id)] = CandidateContextLimit(
            max_input_tokens=_as_positive_int(item.get("max_input_tokens")),
            max_output_tokens=_as_positive_int(item.get("max_output_tokens")),
            max_context_tokens=_as_positive_int(item.get("max_context_tokens")),
        )
    return result


def context_skip_detail(
    candidate: RouteCandidate,
    token_estimate: int,
    limits: dict[tuple[str, str], CandidateContextLimit],
) -> dict | None:
    limit = limits.get((candidate.provider, candidate.model))
    if limit is None:
        return None
    effective_limit = limit.max_context_tokens or limit.max_input_tokens
    if effective_limit is None or token_estimate <= effective_limit:
        return None
    return {
        "provider": candidate.provider,
        "model": candidate.model,
        "status": "skipped",
        "reason": "context_too_large",
        "token_estimate": token_estimate,
        "max_context_tokens": effective_limit,
    }


def filter_candidates_by_context(
    candidates: list[RouteCandidate],
    token_estimate: int,
    limits: dict[tuple[str, str], CandidateContextLimit],
) -> tuple[list[RouteCandidate], list[dict]]:
    kept: list[RouteCandidate] = []
    skipped: list[dict] = []
    for candidate in candidates:
        detail = context_skip_detail(candidate, token_estimate, limits)
        if detail is not None:
            skipped.append(detail)
            continue
        kept.append(candidate)
    return kept, skipped


def _as_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
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
