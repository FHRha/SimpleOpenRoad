"""Pydantic models for env and YAML gateway configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, ROUTE_STRICT_PRIORITY


class EnvSettings(BaseSettings):
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 12345
    app_log_level: str = "INFO"
    app_config_path: str = DEFAULT_CONFIG_PATH
    app_db_path: str = DEFAULT_DB_PATH
    master_api_key: str = ""
    admin_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 12345
    request_timeout_seconds: int = 60
    stream_timeout_seconds: int = 300


class SecurityConfig(BaseModel):
    require_master_key: bool = True
    require_admin_key: bool = True
    mask_secrets_in_logs: bool = True


class RetryConfig(BaseModel):
    max_attempts_per_candidate: int = 2
    backoff_base_ms: int = 200
    backoff_max_ms: int = 2000
    jitter_ms: int = 100


class ErrorPolicyConfig(BaseModel):
    auth_invalid: str = "switch_key"
    auth_forbidden: str = "switch_key"
    rate_limit: str = "retry_then_switch_key"
    provider_unavailable: str = "retry_then_switch_provider"
    network_timeout: str = "retry_then_switch_key"
    malformed_response: str = "switch_provider"
    unsupported_model: str = "switch_provider"


class RoutingConfig(BaseModel):
    default_strategy: str = ROUTE_STRICT_PRIORITY
    retry: RetryConfig = Field(default_factory=RetryConfig)
    error_policy: ErrorPolicyConfig = Field(default_factory=ErrorPolicyConfig)


class KeyLimitsConfig(BaseModel):
    rpm: int | None = None
    tpm: int | None = None


class KeyCooldownConfig(BaseModel):
    rate_limit_seconds: int = 30
    error_seconds: int = 15


class KeyConfig(BaseModel):
    id: str
    key: str
    alias: str | None = None
    active: bool = True
    priority: int = 100
    weight: int = 1
    tags: list[str] = Field(default_factory=list)
    limits: KeyLimitsConfig = Field(default_factory=KeyLimitsConfig)
    cooldown: KeyCooldownConfig = Field(default_factory=KeyCooldownConfig)
    max_retries: int = 1
    max_consecutive_errors: int = 5


class ProviderConfig(BaseModel):
    enabled: bool = True
    priority: int = 100
    endpoint: str
    timeout_seconds: int = 45
    headers: dict[str, str] = Field(default_factory=dict)
    keys: list[KeyConfig] = Field(default_factory=list)


class RouteCandidateConfig(BaseModel):
    provider: str
    model: str


class AliasRouteConfig(BaseModel):
    strategy: str = ROUTE_STRICT_PRIORITY
    selection: str = "ordered"
    candidates: list[RouteCandidateConfig] = Field(default_factory=list)


class RoutesConfig(BaseModel):
    aliases: dict[str, AliasRouteConfig] = Field(default_factory=dict)


class StorageConfig(BaseModel):
    sqlite_path: str = DEFAULT_DB_PATH


class HealthConfig(BaseModel):
    check_interval_seconds: int = 300
    startup_check: bool = True
    check_timeout_seconds: int = 20


class ObservabilityConfig(BaseModel):
    json_logs: bool = True
    request_log: bool = True
    router_decision_log: bool = True
    save_attempt_events: bool = True


class GatewayConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    routes: RoutesConfig = Field(default_factory=RoutesConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @field_validator("providers")
    @classmethod
    def validate_provider_keys(cls, value: dict[str, ProviderConfig]) -> dict[str, ProviderConfig]:
        seen_key_ids: set[str] = set()
        for provider_name, provider in value.items():
            for key in provider.keys:
                if key.id in seen_key_ids:
                    raise ValueError(f"duplicate key id detected: {key.id}")
                seen_key_ids.add(key.id)
                if not key.id.startswith(provider_name):
                    # Convention only; this is an actionable warning in logs later.
                    continue
        return value
