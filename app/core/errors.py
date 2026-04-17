"""Domain-level exceptions and gateway error helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ErrorClass(str, Enum):
    AUTH_INVALID = "auth_invalid"
    AUTH_FORBIDDEN = "auth_forbidden"
    RATE_LIMIT = "rate_limit"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    NETWORK_TIMEOUT = "network_timeout"
    MALFORMED_RESPONSE = "malformed_response"
    UNSUPPORTED_MODEL = "unsupported_model"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class GatewayError(Exception):
    """Typed gateway error with machine-readable class and status code."""

    message: str
    error_class: ErrorClass = ErrorClass.UNKNOWN
    status_code: int = 500
    provider: str | None = None
    key_id: str | None = None
    details: dict[str, Any] | None = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


def _provider_label(provider: str | None) -> str:
    if not provider:
        return "Upstream provider"
    labels = {
        "openrouter": "OpenRouter",
        "github": "GitHub Models",
        "gemini": "Gemini",
        "groq": "Groq",
        "together": "Together AI",
        "cerebras": "Cerebras Inference",
        "cloudflare": "Cloudflare Workers AI",
    }
    return labels.get(provider, provider)


def _retry_after_fragment(details: dict[str, Any] | None) -> str:
    if not isinstance(details, dict):
        return ""
    retry_after = details.get("retry_after_seconds")
    if isinstance(retry_after, int) and retry_after > 0:
        return f" Retry after about {retry_after}s."
    return ""


def user_facing_error_message(error: GatewayError) -> str:
    details = error.details if isinstance(error.details, dict) else {}
    provider = error.provider or details.get("cooldown_provider")
    provider_label = _provider_label(str(provider) if provider else None)
    free_alias = details.get("free_alias") if isinstance(details.get("free_alias"), dict) else {}
    route_alias = details.get("route_alias")
    model = details.get("model")
    retry_fragment = _retry_after_fragment(details)
    rate_limit_scope = details.get("rate_limit_scope")

    if error.error_class == ErrorClass.RATE_LIMIT:
        if free_alias.get("free_only"):
            if rate_limit_scope == "provider_free_tier":
                return (
                    f"{provider_label} free-tier rate limit reached for the free-only route"
                    f" `{route_alias or 'auto/free'}`. No paid fallback was used.{retry_fragment}"
                )
            return (
                f"Free-only route `{route_alias or 'auto/free'}` is temporarily cooling down after rate limit."
                f" No paid fallback was used.{retry_fragment}"
            )
        if provider:
            return f"{provider_label} rate limit reached.{retry_fragment}".strip()
        return f"Route is temporarily cooling down after rate limit.{retry_fragment}".strip()

    if error.error_class == ErrorClass.AUTH_INVALID:
        return f"{provider_label} credentials are invalid or missing required permissions."

    if error.error_class == ErrorClass.AUTH_FORBIDDEN:
        return f"{provider_label} rejected the request due to access restrictions."

    if error.error_class == ErrorClass.NETWORK_TIMEOUT:
        return f"{provider_label} timed out while generating a response."

    if error.error_class == ErrorClass.MALFORMED_RESPONSE:
        return f"{provider_label} returned an empty or invalid response."

    if error.error_class == ErrorClass.UNSUPPORTED_MODEL:
        if provider and model:
            return f"{provider_label} does not support model `{model}` for this request."
        if provider:
            return f"{provider_label} does not support this request format or model."
        return "The selected model does not support this request."

    if error.error_class == ErrorClass.PROVIDER_UNAVAILABLE:
        if free_alias.get("free_only"):
            return (
                f"No free-only route candidates are currently available for `{route_alias or 'auto/free'}`."
                f"{retry_fragment}"
            )
        return "No healthy route candidates are currently available."

    upstream_status = details.get("upstream_status")
    if provider and upstream_status:
        return f"{provider_label} returned HTTP {upstream_status}."
    if provider:
        return f"{provider_label} returned an unexpected error."
    return error.message


class ConfigError(Exception):
    """Raised when config cannot be loaded or validated."""


class AuthError(Exception):
    """Raised when request authentication fails."""


class ProviderError(Exception):
    """Provider adapter low-level error."""
