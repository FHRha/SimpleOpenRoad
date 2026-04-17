"""Configuration loading from .env and YAML with env variable expansion."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path

import yaml

from app.config.models import EnvSettings, GatewayConfig
from app.core.errors import ConfigError


GENERATED_ALIAS_PREFIX = "auto/"


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


def _default_config_path(path: Path) -> Path | None:
    candidate = path.with_name("config.example.yaml")
    if candidate.exists():
        return candidate
    return None


def _merge_missing_defaults(raw: dict, defaults: dict) -> dict:
    merged = deepcopy(raw)
    for key, default_value in defaults.items():
        current_value = merged.get(key)
        if key not in merged:
            merged[key] = deepcopy(default_value)
            continue
        if isinstance(current_value, dict) and isinstance(default_value, dict):
            merged[key] = _merge_missing_defaults(current_value, default_value)
    return merged


def load_raw_gateway_config(config_path: str | Path) -> dict:
    path = Path(config_path)
    raw = _read_yaml_with_env_expansion(path)
    default_path = _default_config_path(path)
    if default_path is not None and default_path != path:
        defaults = _read_yaml_with_env_expansion(default_path)
        raw = _merge_missing_defaults(raw, defaults)
    return raw


def load_env_settings() -> EnvSettings:
    return EnvSettings()


def _apply_route_alias_migrations(config: GatewayConfig) -> None:
    for alias_name in list(config.routes.aliases):
        if not alias_name.startswith(GENERATED_ALIAS_PREFIX):
            continue
        config.routes.aliases.pop(alias_name, None)


def load_gateway_config(config_path: str | None = None, env: EnvSettings | None = None) -> GatewayConfig:
    env_settings = env or load_env_settings()
    path = Path(config_path or env_settings.app_config_path)
    try:
        raw = load_raw_gateway_config(path)
        config = GatewayConfig.model_validate(raw)
        _apply_route_alias_migrations(config)
    except Exception as exc:  # noqa: BLE001 - converted into domain error
        raise ConfigError(f"Failed to load config {path}: {exc}") from exc

    if not config.storage.sqlite_path:
        config.storage.sqlite_path = env_settings.app_db_path
    return config
