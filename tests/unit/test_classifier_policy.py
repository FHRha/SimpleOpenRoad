from app.config.models import ErrorPolicyConfig
from app.core.errors import ErrorClass, GatewayError
from app.router.classifier import classify_error
from app.router.policy import policy_action, should_retry_same_key, should_switch_provider


def test_classifier_reads_gateway_error_class() -> None:
    exc = GatewayError(message="rate limited", error_class=ErrorClass.RATE_LIMIT, status_code=429)
    assert classify_error(exc) == ErrorClass.RATE_LIMIT


def test_policy_action_mapping() -> None:
    cfg = ErrorPolicyConfig()
    assert policy_action(cfg, ErrorClass.AUTH_INVALID) == "switch_key"
    assert policy_action(cfg, ErrorClass.PROVIDER_UNAVAILABLE) == "retry_then_switch_provider"


def test_retry_and_switch_helpers() -> None:
    assert should_retry_same_key("retry_then_switch_key", current_attempt=1, max_attempts=2)
    assert not should_retry_same_key("switch_provider", current_attempt=1, max_attempts=2)
    assert should_switch_provider("switch_provider")
    assert not should_switch_provider("switch_key")
