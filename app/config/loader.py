"""Configuration loading from .env and YAML with env variable expansion."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from app.config.models import EnvSettings, GatewayConfig
from app.core.errors import ConfigError


def _read_yaml_with_env_expansion(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    text = path.read_text(encoding="utf-8")
    # Expand ${VAR} placeholders before YAML parsing.
    expanded = os.path.expandvars(text)
    raw = yaml.safe_load(expanded) or {}
    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a mapping object")
    return raw


def load_env_settings() -> EnvSettings:
    return EnvSettings()


def load_gateway_config(config_path: str | None = None, env: EnvSettings | None = None) -> GatewayConfig:
    env_settings = env or load_env_settings()
    path = Path(config_path or env_settings.app_config_path)
    try:
        raw = _read_yaml_with_env_expansion(path)
        config = GatewayConfig.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - converted into domain error
        raise ConfigError(f"Failed to load config {path}: {exc}") from exc

    if not config.storage.sqlite_path:
        config.storage.sqlite_path = env_settings.app_db_path
    return config
