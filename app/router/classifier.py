"""Error classification for router policies."""

from __future__ import annotations

from app.core.errors import ErrorClass, GatewayError


def classify_error(exc: Exception) -> ErrorClass:
    if isinstance(exc, GatewayError):
        return exc.error_class
    return ErrorClass.UNKNOWN
