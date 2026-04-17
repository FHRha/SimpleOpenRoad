from __future__ import annotations

from app.core.errors import ErrorClass, GatewayError, user_facing_error_message


def test_user_facing_message_for_free_tier_rate_limit_is_specific() -> None:
    error = GatewayError(
        message="Provider openrouter returned 429: free tier limit",
        error_class=ErrorClass.RATE_LIMIT,
        status_code=429,
        provider="openrouter",
        details={
            "route_alias": "auto/free",
            "retry_after_seconds": 20,
            "rate_limit_scope": "provider_free_tier",
            "free_alias": {"free_only": True},
        },
    )

    message = user_facing_error_message(error)

    assert "OpenRouter free-tier rate limit reached" in message
    assert "`auto/free`" in message
    assert "No paid fallback was used" in message
    assert "20s" in message


def test_user_facing_message_for_auth_invalid_is_specific() -> None:
    error = GatewayError(
        message="Provider github returned 401",
        error_class=ErrorClass.AUTH_INVALID,
        status_code=401,
        provider="github",
    )

    assert user_facing_error_message(error) == "GitHub Models credentials are invalid or missing required permissions."


def test_user_facing_message_for_malformed_response_is_specific() -> None:
    error = GatewayError(
        message="Malformed JSON from openrouter",
        error_class=ErrorClass.MALFORMED_RESPONSE,
        status_code=502,
        provider="openrouter",
    )

    assert user_facing_error_message(error) == "OpenRouter returned an empty or invalid response."
