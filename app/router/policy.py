"""Retry/fallback policy helpers."""

from __future__ import annotations

from app.config.models import ErrorPolicyConfig
from app.core.errors import ErrorClass


def policy_action(error_policy: ErrorPolicyConfig, error_class: ErrorClass) -> str:
    mapping = {
        ErrorClass.AUTH_INVALID: error_policy.auth_invalid,
        ErrorClass.AUTH_FORBIDDEN: error_policy.auth_forbidden,
        ErrorClass.RATE_LIMIT: error_policy.rate_limit,
        ErrorClass.PROVIDER_UNAVAILABLE: error_policy.provider_unavailable,
        ErrorClass.NETWORK_TIMEOUT: error_policy.network_timeout,
        ErrorClass.MALFORMED_RESPONSE: error_policy.malformed_response,
        ErrorClass.UNSUPPORTED_MODEL: error_policy.unsupported_model,
    }
    return mapping.get(error_class, "switch_provider")


def should_retry_same_key(action: str, current_attempt: int, max_attempts: int) -> bool:
    if current_attempt >= max_attempts:
        return False
    return action in {
        "retry",
        "retry_then_switch_key",
        "retry_then_switch_provider",
    }


def should_switch_provider(action: str) -> bool:
    return action in {
        "switch_provider",
        "retry_then_switch_provider",
    }
