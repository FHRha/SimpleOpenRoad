"""Key selection strategies."""

from __future__ import annotations

import random
from datetime import datetime

from app.config.models import KeyConfig


def _priority_order_key(key: KeyConfig) -> tuple[int, str]:
    return (-key.priority, key.id)


def select_keys(
    strategy: str,
    keys: list[KeyConfig],
    runtime_by_key: dict[str, dict] | None = None,
) -> list[KeyConfig]:
    runtime = runtime_by_key or {}
    if strategy == "strict_priority":
        return sorted(keys, key=_priority_order_key)

    if strategy == "random_by_weight":
        weighted = []
        for key in keys:
            weighted.extend([key] * max(1, key.weight))
        random.shuffle(weighted)
        seen: set[str] = set()
        result: list[KeyConfig] = []
        for key in weighted:
            if key.id not in seen:
                seen.add(key.id)
                result.append(key)
        return result

    if strategy == "least_errors":
        return sorted(
            keys,
            key=lambda k: (
                int(runtime.get(k.id, {}).get("consecutive_errors", 0)),
                -k.priority,
                k.id,
            ),
        )

    if strategy == "least_recently_used":
        def lru_score(key: KeyConfig) -> float:
            value = runtime.get(key.id, {}).get("last_success_at")
            if not value:
                return 0.0
            try:
                return datetime.fromisoformat(str(value)).timestamp()
            except ValueError:
                return 0.0

        return sorted(keys, key=lru_score)

    # Fallback to deterministic behavior.
    return sorted(keys, key=_priority_order_key)
