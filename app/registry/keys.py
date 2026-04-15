"""Key registry that merges static config and runtime SQLite state."""

from __future__ import annotations

from datetime import UTC, datetime

from app.config.models import GatewayConfig, KeyConfig
from app.core.errors import ErrorClass
from app.core.security import is_configured_secret
from app.core.utils import utcnow
from app.storage.repositories.keys_repo import KeysRuntimeRepository


class KeyRegistry:
    def __init__(self, runtime_repo: KeysRuntimeRepository):
        self.runtime_repo = runtime_repo

    def sync_defaults(self, config: GatewayConfig) -> None:
        for provider_name, provider in config.providers.items():
            for key in provider.keys:
                if not is_configured_secret(key.key):
                    continue
                self.runtime_repo.upsert_default(
                    provider=provider_name,
                    key_id=key.id,
                    active=key.active,
                )

    def list_configured_keys(self, config: GatewayConfig, include_unconfigured: bool = False) -> list[dict]:
        runtime_map = {item["key_id"]: item for item in self.runtime_repo.list_states()}
        items: list[dict] = []
        for provider_name, provider in config.providers.items():
            for key in provider.keys:
                configured = is_configured_secret(key.key)
                if not configured and not include_unconfigured:
                    continue
                state = runtime_map.get(key.id, {})
                items.append(
                    {
                        "provider": provider_name,
                        "id": key.id,
                        "alias": key.alias,
                        "configured": configured,
                        "active": bool(state.get("active", 1)) and key.active,
                        "status": state.get("status", "unknown"),
                        "priority": key.priority,
                        "weight": key.weight,
                        "consecutive_errors": state.get("consecutive_errors", 0),
                        "cooldown_until": state.get("cooldown_until"),
                        "last_check_at": state.get("last_check_at"),
                        "last_success_at": state.get("last_success_at"),
                        "last_error_at": state.get("last_error_at"),
                        "last_error_code": state.get("last_error_code"),
                        "success_count": state.get("success_count", 0),
                        "failure_count": state.get("failure_count", 0),
                        "switch_count": state.get("switch_count", 0),
                        "avg_latency_ms": state.get("avg_latency_ms", 0.0),
                    }
                )
        return items

    def get_available_keys(self, config: GatewayConfig, provider_name: str) -> list[KeyConfig]:
        provider = config.providers.get(provider_name)
        if not provider or not provider.enabled:
            return []

        runtime_map = {item["key_id"]: item for item in self.runtime_repo.list_states()}
        return self._available_keys_from_runtime_map(provider=provider, runtime_map=runtime_map)

    def get_available_keys_for_runtime(
        self,
        config: GatewayConfig,
        provider_name: str,
        runtime_map: dict[str, dict],
    ) -> list[KeyConfig]:
        provider = config.providers.get(provider_name)
        if not provider or not provider.enabled:
            return []
        return self._available_keys_from_runtime_map(provider=provider, runtime_map=runtime_map)

    @staticmethod
    def _available_keys_from_runtime_map(provider, runtime_map: dict[str, dict]) -> list[KeyConfig]:
        available: list[KeyConfig] = []
        now = utcnow()
        for key in provider.keys:
            runtime = runtime_map.get(key.id)
            if not is_configured_secret(key.key):
                continue
            if not key.active:
                continue
            if runtime and not bool(runtime.get("active", 1)):
                continue
            if runtime and runtime.get("status") == "blocked":
                continue
            cooldown_until = runtime.get("cooldown_until") if runtime else None
            if cooldown_until:
                try:
                    if datetime.fromisoformat(cooldown_until) > now:
                        continue
                except ValueError:
                    pass
            available.append(key)

        # Higher number means higher priority; ties are deterministic by key id.
        available.sort(key=lambda k: (-k.priority, k.id))
        return available

    def record_success(self, key_id: str, latency_ms: float) -> None:
        self.runtime_repo.record_success(key_id, latency_ms)

    def record_failure(
        self,
        key: KeyConfig,
        error_class: ErrorClass,
        error_message: str,
    ) -> None:
        cooldown_seconds = key.cooldown.error_seconds
        new_status: str | None = None

        if error_class == ErrorClass.RATE_LIMIT:
            cooldown_seconds = key.cooldown.rate_limit_seconds
            new_status = "degraded"
        elif error_class in (ErrorClass.AUTH_INVALID, ErrorClass.AUTH_FORBIDDEN):
            new_status = "invalid"
            cooldown_seconds = max(cooldown_seconds, 300)
        elif error_class == ErrorClass.PROVIDER_UNAVAILABLE:
            new_status = "degraded"

        cooldown_until = datetime.now(UTC).timestamp() + cooldown_seconds
        cooldown_until_iso = datetime.fromtimestamp(cooldown_until, UTC).isoformat()

        self.runtime_repo.record_failure(
            key_id=key.id,
            error_code=error_class.value,
            error_message=error_message,
            cooldown_until_iso=cooldown_until_iso,
            new_status=new_status,
        )
        state = self.runtime_repo.get_state(key.id)
        if state and int(state.get("consecutive_errors", 0)) >= key.max_consecutive_errors:
            self.runtime_repo.set_status(key.id, "blocked")

    def mark_health(
        self,
        key_id: str,
        status: str,
        checked_at: str,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        self.runtime_repo.update_health(
            key_id=key_id,
            status=status,
            checked_at=checked_at,
            error_code=error_code,
            error_message=error_message,
        )

    def set_active(self, key_id: str, active: bool) -> None:
        self.runtime_repo.set_active(key_id, active)

    def reset_state(self, provider: str, key_id: str, active: bool) -> None:
        self.runtime_repo.reset_state(provider=provider, key_id=key_id, active=active)

    def bump_switch(self, key_id: str) -> None:
        self.runtime_repo.bump_switch_counter(key_id)
