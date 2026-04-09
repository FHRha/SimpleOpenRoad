"""Thread-safe runtime configuration manager with reload support."""

from __future__ import annotations

from threading import RLock

from app.config.loader import load_env_settings, load_gateway_config
from app.config.models import EnvSettings, GatewayConfig


class RuntimeConfig:
    """Holds current validated config and allows atomic reload."""

    def __init__(self, config: GatewayConfig, env: EnvSettings):
        self._lock = RLock()
        self._config = config
        self._env = env

    @classmethod
    def bootstrap(cls, config_path: str | None = None) -> "RuntimeConfig":
        env = load_env_settings()
        cfg = load_gateway_config(config_path=config_path, env=env)
        return cls(config=cfg, env=env)

    @property
    def env(self) -> EnvSettings:
        return self._env

    def get(self) -> GatewayConfig:
        with self._lock:
            return self._config

    def reload(self, config_path: str | None = None) -> GatewayConfig:
        with self._lock:
            new_config = load_gateway_config(config_path=config_path, env=self._env)
            self._config = new_config
            return self._config
