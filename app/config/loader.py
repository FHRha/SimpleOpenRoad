"""Configuration loading from .env and YAML with env variable expansion."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from app.config.models import AliasRouteConfig, EnvSettings, GatewayConfig
from app.core.errors import ConfigError


DEFAULT_ROUTE_ALIASES: dict[str, dict] = {
    "auto/smart": {
        "strategy": "strict_priority",
        "selection": "adaptive",
        "candidates": [
            {"provider": "gemini", "model": "gemini-2.5-flash"},
            {"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"},
            {"provider": "gemini", "model": "gemini-3-flash-preview"},
            {"provider": "gemini", "model": "gemini-3.1-pro-preview"},
            {"provider": "github", "model": "gpt-5.3-codex"},
            {"provider": "github", "model": "gpt-5.4-mini"},
            {"provider": "github", "model": "gpt-5.4"},
            {"provider": "github", "model": "gpt-4.1-mini"},
            {"provider": "openrouter", "model": "openai/gpt-5.4-nano"},
            {"provider": "openrouter", "model": "openai/gpt-5.4-mini"},
            {"provider": "openrouter", "model": "openai/gpt-5.4"},
            {"provider": "openrouter", "model": "openai/gpt-5.4-pro"},
            {"provider": "openrouter", "model": "openai/gpt-5.3-codex"},
            {"provider": "openrouter", "model": "google/gemini-3.1-flash-lite-preview"},
            {"provider": "openrouter", "model": "google/gemini-3-flash-preview"},
            {"provider": "openrouter", "model": "google/gemini-3.1-pro-preview"},
            {"provider": "openrouter", "model": "anthropic/claude-haiku-4.5"},
            {"provider": "openrouter", "model": "anthropic/claude-sonnet-4.6"},
            {"provider": "openrouter", "model": "anthropic/claude-opus-4.6"},
            {"provider": "openrouter", "model": "qwen/qwen3-coder-plus"},
            {"provider": "openrouter", "model": "qwen/qwen3-coder-next"},
            {"provider": "openrouter", "model": "qwen/qwen3.6-plus"},
            {"provider": "openrouter", "model": "moonshotai/kimi-k2.5"},
            {"provider": "openrouter", "model": "x-ai/grok-code-fast-1"},
            {"provider": "openrouter", "model": "x-ai/grok-4.20"},
        ],
    },
    "auto/fast": {
        "strategy": "strict_priority",
        "candidates": [
            {"provider": "gemini", "model": "gemini-2.5-flash"},
            {"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"},
            {"provider": "github", "model": "gpt-4.1-mini"},
            {"provider": "openrouter", "model": "openai/gpt-5.4-nano"},
            {"provider": "openrouter", "model": "google/gemini-3.1-flash-lite-preview"},
            {"provider": "openrouter", "model": "anthropic/claude-haiku-4.5"},
        ],
    },
    "auto/balanced": {
        "strategy": "strict_priority",
        "candidates": [
            {"provider": "gemini", "model": "gemini-3-flash-preview"},
            {"provider": "github", "model": "gpt-5.4-mini"},
            {"provider": "github", "model": "gpt-4.1"},
            {"provider": "openrouter", "model": "openai/gpt-5.4-mini"},
            {"provider": "openrouter", "model": "google/gemini-3-flash-preview"},
            {"provider": "openrouter", "model": "anthropic/claude-sonnet-4.6"},
            {"provider": "openrouter", "model": "qwen/qwen3.6-plus"},
        ],
    },
    "auto/strong": {
        "strategy": "strict_priority",
        "candidates": [
            {"provider": "gemini", "model": "gemini-3.1-pro-preview"},
            {"provider": "github", "model": "gpt-5.4-pro"},
            {"provider": "github", "model": "gpt-5.4"},
            {"provider": "openrouter", "model": "openai/gpt-5.4-pro"},
            {"provider": "openrouter", "model": "openai/gpt-5.4"},
            {"provider": "openrouter", "model": "google/gemini-3.1-pro-preview"},
            {"provider": "openrouter", "model": "anthropic/claude-opus-4.6"},
            {"provider": "openrouter", "model": "anthropic/claude-sonnet-4.6"},
            {"provider": "openrouter", "model": "x-ai/grok-4.20"},
        ],
    },
    "auto/code": {
        "strategy": "strict_priority",
        "candidates": [
            {"provider": "github", "model": "gpt-5.3-codex"},
            {"provider": "github", "model": "gpt-5.4"},
            {"provider": "openrouter", "model": "openai/gpt-5.3-codex"},
            {"provider": "openrouter", "model": "anthropic/claude-sonnet-4.6"},
            {"provider": "openrouter", "model": "anthropic/claude-opus-4.6"},
            {"provider": "openrouter", "model": "openai/gpt-5.4"},
            {"provider": "openrouter", "model": "google/gemini-3.1-pro-preview-customtools"},
            {"provider": "openrouter", "model": "qwen/qwen3-coder-plus"},
            {"provider": "openrouter", "model": "qwen/qwen3-coder-next"},
            {"provider": "openrouter", "model": "moonshotai/kimi-k2.5"},
            {"provider": "openrouter", "model": "x-ai/grok-code-fast-1"},
            {"provider": "gemini", "model": "gemini-3.1-pro-preview"},
        ],
    },
}

DEPRECATED_ROUTE_ALIASES = {"auto/fallback"}


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


def _apply_route_alias_migrations(config: GatewayConfig) -> None:
    had_deprecated_alias = any(alias_name in config.routes.aliases for alias_name in DEPRECATED_ROUTE_ALIASES)
    for alias_name in DEPRECATED_ROUTE_ALIASES:
        config.routes.aliases.pop(alias_name, None)
    should_seed_default_aliases = had_deprecated_alias or not config.routes.aliases
    if not should_seed_default_aliases:
        return
    for alias_name, alias_config in DEFAULT_ROUTE_ALIASES.items():
        if alias_name not in config.routes.aliases:
            config.routes.aliases[alias_name] = AliasRouteConfig.model_validate(alias_config)


def load_gateway_config(config_path: str | None = None, env: EnvSettings | None = None) -> GatewayConfig:
    env_settings = env or load_env_settings()
    path = Path(config_path or env_settings.app_config_path)
    try:
        raw = _read_yaml_with_env_expansion(path)
        config = GatewayConfig.model_validate(raw)
        _apply_route_alias_migrations(config)
    except Exception as exc:  # noqa: BLE001 - converted into domain error
        raise ConfigError(f"Failed to load config {path}: {exc}") from exc

    if not config.storage.sqlite_path:
        config.storage.sqlite_path = env_settings.app_db_path
    return config
