"""Security helpers for API key checks."""

from __future__ import annotations

from app.core.constants import HEADER_ADMIN_KEY, HEADER_API_KEY, HEADER_AUTHORIZATION


def extract_bearer_token(header_value: str | None) -> str | None:
    if not header_value:
        return None
    prefix = "bearer "
    lowered = header_value.lower()
    if not lowered.startswith(prefix):
        return None
    return header_value[len(prefix):].strip()


def extract_user_api_key(headers: dict[str, str]) -> str | None:
    normalized = {k.lower(): v for k, v in headers.items()}
    direct = normalized.get(HEADER_API_KEY)
    if direct:
        return direct
    return extract_bearer_token(normalized.get(HEADER_AUTHORIZATION))


def extract_admin_key(headers: dict[str, str]) -> str | None:
    normalized = {k.lower(): v for k, v in headers.items()}
    direct = normalized.get(HEADER_ADMIN_KEY)
    if direct:
        return direct
    return extract_bearer_token(normalized.get(HEADER_AUTHORIZATION))
