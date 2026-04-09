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


class ConfigError(Exception):
    """Raised when config cannot be loaded or validated."""


class AuthError(Exception):
    """Raised when request authentication fails."""


class ProviderError(Exception):
    """Provider adapter low-level error."""
