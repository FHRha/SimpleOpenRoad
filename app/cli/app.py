"""Typer-based CLI for gateway administration."""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import shlex
import socket
import subprocess
import signal
import shutil
import string
import sys
import textwrap
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import typer
import uvicorn
import yaml
from click.exceptions import Abort
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.config.loader import load_gateway_config, load_raw_gateway_config
from app.config.models import GatewayConfig
from app.container import AppContainer
from app.core.errors import ConfigError
from app.core.security import is_configured_secret
from app.core.types import ChatMessage, RouteCandidate, UnifiedLLMRequest
from app.core.utils import mask_secret
from app.registry.keys import KeyRegistry
from app.router.context_limits import (
    context_skip_detail,
    filter_candidates_by_context,
    limits_from_snapshot_dict,
)
from app.router.model_planner import plan_candidates
from app.router.request_analyzer import RequestRouteAnalysis, analyze_request_route
from app.storage.db import SQLiteDB
from app.storage.repositories.keys_repo import KeysRuntimeRepository
from app.storage.repositories.model_runtime_repo import ModelRuntimeRepository
from app.storage.repositories.route_memory_repo import RouteModelMemoryRepository
from app.providers.metadata import (
    EXPERIMENTAL_PROVIDER_SET,
    FEATURED_PROVIDER_ORDER,
    FEATURED_PROVIDER_SET,
    OTHER_PROVIDER_DISPLAY_LIMIT,
    provider_category,
    provider_display_name,
    search_provider_names,
    sorted_provider_names,
)

cli_app = typer.Typer(
    help="SimpleOpenRoad AI gateway CLI",
    invoke_without_command=True,
    no_args_is_help=False,
)
providers_app = typer.Typer(help="Provider operations")
keys_app = typer.Typer(help="API key operations")
routes_app = typer.Typer(help="Routing operations")
config_app = typer.Typer(help="Config operations")
logs_app = typer.Typer(help="Log operations")
service_app = typer.Typer(help="Background service operations (systemd)")

cli_app.add_typer(providers_app, name="providers")
cli_app.add_typer(keys_app, name="keys")
cli_app.add_typer(routes_app, name="routes")
cli_app.add_typer(config_app, name="config")
cli_app.add_typer(logs_app, name="logs")
cli_app.add_typer(service_app, name="service")

console = Console()

SERVICE_NAME = "sor"
MIN_GEMINI_CLI_NODE_MAJOR = 20
_ROUTE_STRATEGY_OPTIONS = [
    "strict_priority",
    "least_errors",
    "weighted_round_robin",
    "random_by_weight",
    "least_recently_used",
]
_ALIAS_SELECTION_OPTIONS = ["ordered", "adaptive"]
_PLACEHOLDER_ENV_VALUES = {
    "change-me-master-key",
    "change-me-admin-key",
    "",
}
_GENERATED_ALIAS_PREFIX = "auto/"


@cli_app.callback()
def cli_entrypoint(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _run_management_panel(config_path="config/config.yaml")


def _config_path(value: str | None) -> Path:
    return Path(value or "config/config.yaml")


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = load_raw_gateway_config(path)
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not isinstance(data, dict):
        raise typer.BadParameter("Config root must be YAML mapping")
    return data


def _save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")


def _nested_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def _nested_set(data: dict[str, Any], value: Any, *keys: str) -> None:
    current = data
    for key in keys[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[keys[-1]] = value


def _parse_pattern_list(raw: str) -> list[str]:
    items = [item.strip() for item in raw.split(",")]
    return [item for item in items if item]


def _update_config_value(config_path: str, value: Any, *keys: str) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    _nested_set(data, value, *keys)
    _save_yaml(path, data)


def _show_settings_summary(config_path: str) -> None:
    cfg = load_gateway_config(config_path=config_path)
    table = Table(title="SimpleOpenRoad Settings", box=box.ASCII)
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("server.host", str(cfg.server.host))
    table.add_row("server.port", str(cfg.server.port))
    table.add_row("server.request_timeout_seconds", str(cfg.server.request_timeout_seconds))
    table.add_row("server.stream_timeout_seconds", str(cfg.server.stream_timeout_seconds))
    table.add_row("routing.retry.max_attempts_per_candidate", str(cfg.routing.retry.max_attempts_per_candidate))
    table.add_row("routing.model_quarantine.enabled", str(cfg.routing.model_quarantine.enabled))
    table.add_row("routing.model_quarantine.failure_threshold", str(cfg.routing.model_quarantine.failure_threshold))
    table.add_row("routing.model_quarantine.default_ttl_seconds", str(cfg.routing.model_quarantine.default_ttl_seconds))
    table.add_row("routing.model_quarantine.overrides", str(len(cfg.routing.model_quarantine.overrides)))
    table.add_row("health.startup_check", str(cfg.health.startup_check))
    table.add_row("health.check_interval_seconds", str(cfg.health.check_interval_seconds))
    table.add_row("observability.request_log", str(cfg.observability.request_log))
    table.add_row("observability.router_decision_log", str(cfg.observability.router_decision_log))
    table.add_row("model_capabilities.tool_capable", ", ".join(cfg.model_capabilities.tool_capable) or "<empty>")
    table.add_row("model_capabilities.tool_disabled", ", ".join(cfg.model_capabilities.tool_disabled) or "<empty>")
    table.add_row("inventory.refresh_time", cfg.inventory.refresh_time)
    table.add_row("inventory.refresh_timezone", cfg.inventory.refresh_timezone)
    table.add_row("inventory.refresh_interval_hours", str(cfg.inventory.refresh_interval_hours))
    table.add_row("inventory.overrides", str(len(cfg.inventory.overrides)))
    console.print(table)


def _print_numbered_items(title: str, items: list[str], empty_label: str = "<empty>") -> None:
    table = Table(title=title, box=box.ASCII)
    table.add_column("#")
    table.add_column("Value")
    if not items:
        table.add_row("-", empty_label)
    else:
        for index, item in enumerate(items, start=1):
            table.add_row(str(index), item)
    console.print(table)


def _prompt_numbered_choice(count: int, prompt: str, allow_zero: bool = False) -> int:
    default = "0" if allow_zero else "1"
    value = int(typer.prompt(prompt, default=default).strip())
    if allow_zero and value == 0:
        return 0
    if value < 1 or value > count:
        raise typer.BadParameter(f"Choose a number between 1 and {count}")
    return value


def _prompt_menu_choice(prompt: str = "Select option", default: str = "1") -> str:
    try:
        return typer.prompt(prompt, default=default).strip()
    except Abort:
        return "0"


def _print_key_validation_results(results: list[dict[str, Any]], title: str = "Key Validation") -> None:
    table = Table(title=title, box=box.ASCII)
    table.add_column("Provider")
    table.add_column("Key ID")
    table.add_column("Status")
    table.add_column("Latency ms")
    table.add_column("Models")
    table.add_column("Error", overflow="fold")
    if not results:
        table.add_row("-", "-", "<empty>", "-", "-", "-")
        console.print(table)
        return
    for row in results:
        latency = row.get("latency_ms")
        if latency is None:
            latency_text = "-"
        else:
            latency_text = f"{float(latency):.2f}"
        models = row.get("models") if isinstance(row, dict) else []
        model_count = len(models) if isinstance(models, list) else 0
        table.add_row(
            str(row.get("provider", "")),
            str(row.get("key_id", "")),
            str(row.get("status", "")),
            latency_text,
            str(model_count),
            str(row.get("error_code") or row.get("error_message") or "-")[:160],
        )
    console.print(table)


def _result_error_text(row: dict[str, Any], limit: int = 160) -> str:
    return str(row.get("error_code") or row.get("error_message") or "-")[:limit]


def _load_env_file(env_path: Path = Path(".env")) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _set_env_value(key_name: str, value: str, env_path: Path = Path(".env")) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    found = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        current_key, _ = stripped.split("=", 1)
        if current_key.strip() == key_name:
            lines[index] = f"{key_name}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key_name}={value}")
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    os.environ[key_name] = value


def _container(config_path: str | None) -> AppContainer:
    return AppContainer(config_path=config_path)


def _detect_server_ip() -> str:
    # Use a UDP socket to detect primary outbound interface IP without sending traffic.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip:
                return ip
    except OSError:
        pass

    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def _is_non_loopback_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
        return not ip.is_loopback
    except ValueError:
        return False


def _normalize_public_domain(value: str) -> tuple[str, str, bool]:
    raw = value.strip()
    if not raw:
        return "", "", False

    parsed = urlparse(raw)
    if parsed.scheme:
        host = parsed.netloc or parsed.path
        has_port = parsed.port is not None
        return parsed.scheme, host, has_port

    return "https", raw, ":" in raw


def _resolve_api_base_url(cfg: GatewayConfig) -> str:
    configured_domain = os.getenv("APP_PUBLIC_DOMAIN") or os.getenv("APP_DOMAIN") or ""
    if configured_domain.strip():
        scheme, host, has_port = _normalize_public_domain(configured_domain)
        if has_port:
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{cfg.server.port}"

    host = str(cfg.server.host).strip()
    wildcard_hosts = {"", "0.0.0.0", "::", "[::]", "localhost", "127.0.0.1"}
    if host.lower() not in wildcard_hosts and (_is_non_loopback_ip(host) or "." in host):
        return f"http://{host}:{cfg.server.port}"

    return f"http://{_detect_server_ip()}:{cfg.server.port}"


def _current_inventory_snapshot(config_path: str, refresh: bool = False) -> dict[str, Any] | None:
    import asyncio

    container = _container(config_path)
    if refresh:
        return asyncio.run(container.admin_service.refresh_inventory())
    return container.admin_service.current_inventory()


def _refresh_inventory_after_key_change(config_path: str) -> None:
    import asyncio

    try:
        container = _container(config_path)
        snapshot = asyncio.run(container.admin_service.refresh_inventory())
    except Exception as exc:  # noqa: BLE001 - key changes must not be rolled back by inventory refresh failures.
        console.print(f"Model alias refresh failed: {exc}")
        console.print("Run Providers and keys -> Validate keys, or restart/refresh inventory later.")
        return

    generated = snapshot.get("generated_aliases", []) if isinstance(snapshot, dict) else []
    alias_count = len(generated) if isinstance(generated, list) else 0
    console.print(f"Model aliases refreshed: {alias_count} generated aliases available.")
    if _reload_running_gateway(config_path=config_path, quiet=False):
        return
    console.print("If the gateway service is running, restart it before testing new keys.")


def _generated_alias_ids(snapshot: dict[str, Any] | None) -> list[str]:
    if not isinstance(snapshot, dict):
        return []
    aliases = snapshot.get("generated_aliases", [])
    if not isinstance(aliases, list):
        return []
    result: list[str] = []
    for item in aliases:
        if not isinstance(item, dict):
            continue
        alias_id = str(item.get("alias_id", "")).strip()
        if alias_id:
            result.append(alias_id)
    return result


def _generated_alias_map(snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(snapshot, dict):
        return result
    aliases = snapshot.get("generated_aliases", [])
    if not isinstance(aliases, list):
        return result
    for item in aliases:
        if not isinstance(item, dict):
            continue
        alias_id = str(item.get("alias_id", "")).strip()
        if alias_id:
            result[alias_id] = item
    return result


def _format_model_aliases(cfg: GatewayConfig, snapshot: dict[str, Any] | None = None) -> str:
    aliases = _generated_alias_ids(snapshot)
    if not aliases:
        aliases = list(cfg.routes.aliases)
    return ", ".join(aliases) if aliases else "<no aliases configured>"


def _recommended_model_alias(cfg: GatewayConfig, snapshot: dict[str, Any] | None = None) -> str:
    aliases = set(_generated_alias_ids(snapshot) or list(cfg.routes.aliases))
    if "auto/general" in aliases:
        return "auto/general"
    if "auto/fast" in aliases:
        return "auto/fast"
    if "auto/code" in aliases:
        return "auto/code"
    return next(iter(aliases), "")


def _model_alias_help_rows(cfg: GatewayConfig, snapshot: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    descriptions = {
        "auto/free": "free-capable routes only when available",
        "auto/free-cheap": "free models first, then lightweight paid fallback",
        "auto/fast": "lightweight, cheap, low-latency tasks",
        "auto/general": "recommended default for general chat and everyday use",
        "auto/reasoning": "hard reasoning, long context, complex analysis",
        "auto/code": "coding, debugging, refactoring, repository work",
        "auto/text/free": "canonical text alias for free-capable routes",
        "auto/text/free-cheap": "canonical text alias for free-first with cheap fallback",
        "auto/text/fast": "canonical text alias for lightweight tasks",
        "auto/text/general": "canonical text alias for general chat",
        "auto/text/reasoning": "canonical text alias for hard reasoning",
        "auto/text/code": "canonical text alias for coding tasks",
        "auto/image/default": "image-capable models discovered in provider inventory",
        "auto/video/default": "video-capable models discovered in provider inventory",
        "auto/audio/default": "audio-capable models discovered in provider inventory",
    }
    rows: list[tuple[str, str]] = []
    aliases = _generated_alias_ids(snapshot)
    if aliases:
        for alias in aliases:
            rows.append((alias, descriptions.get(alias, "generated from current provider inventory")))
    else:
        for alias in cfg.routes.aliases:
            rows.append((alias, descriptions.get(alias, "custom route alias from config.yaml")))
    return rows


def _print_alias_help_table(cfg: GatewayConfig, snapshot: dict[str, Any] | None = None) -> None:
    table = Table(title="Model Alias Guide", box=box.ASCII)
    table.add_column("Alias")
    table.add_column("Use for")
    for alias, description in _model_alias_help_rows(cfg, snapshot):
        table.add_row(alias, description)
    console.print(table)


def _select_test_alias(config_path: str) -> str | None:
    cfg = load_gateway_config(config_path=config_path)
    snapshot = _current_inventory_snapshot(config_path, refresh=False)
    if not _generated_alias_ids(snapshot):
        snapshot = _current_inventory_snapshot(config_path, refresh=True)
    generated_aliases = _generated_alias_ids(snapshot)
    alias_descriptions = dict(_model_alias_help_rows(cfg, snapshot))

    preferred_aliases = ("auto/fast", "auto/free", "auto/free-cheap", "auto/general", "auto/reasoning", "auto/code")
    alias_options: list[str] = []
    seen: set[str] = set()
    for alias in preferred_aliases:
        if alias in generated_aliases and alias not in seen:
            alias_options.append(alias)
            seen.add(alias)
    for alias in generated_aliases:
        if alias.startswith("auto/text/"):
            continue
        if alias not in seen and alias.startswith("auto/"):
            alias_options.append(alias)
            seen.add(alias)
    for alias in cfg.routes.aliases:
        if alias not in seen:
            alias_options.append(alias)
            seen.add(alias)

    if not alias_options:
        console.print("No generated or custom aliases are available. Add provider keys, validate them, then refresh inventory.")
        return None

    table = Table(title="Select Alias for Automatic API Test", box=box.ASCII)
    table.add_column("#")
    table.add_column("Alias")
    table.add_column("Use for")
    for index, alias in enumerate(alias_options, start=1):
        table.add_row(str(index), alias, alias_descriptions.get(alias, "generated from current provider inventory"))
    table.add_row("M", "Manual input", "enter custom alias or direct model")
    table.add_row("0", "Back", "cancel automatic test")
    console.print(table)

    choice = _prompt_menu_choice(prompt="Alias to test", default="1")
    if choice == "0":
        return None
    if choice.lower() == "m":
        default_model = _recommended_model_alias(cfg, snapshot) or "provider/model"
        manual_value = typer.prompt("Model or alias", default=default_model).strip()
        if manual_value.startswith(_GENERATED_ALIAS_PREFIX) and manual_value not in generated_aliases:
            raise typer.BadParameter(f"Generated alias is not available in current inventory: {manual_value}")
        return manual_value

    selected = int(choice)
    if selected < 1 or selected > len(alias_options):
        raise typer.BadParameter(f"Choose a number between 1 and {len(alias_options)}, M, or 0")
    return alias_options[selected - 1]


def _select_api_test_mode() -> str | None:
    modes = [
        ("simple", "simple chat", "fast non-streaming hello check"),
        ("stream", "streaming chat", "checks SSE streaming path"),
        ("tools", "tools request", "checks tool-capable OpenAI-compatible payload"),
        ("cline", "Cline-like", "streaming request with tools and Cline-style fields"),
    ]
    table = Table(title="Select Automatic API Test Mode", box=box.ASCII)
    table.add_column("#")
    table.add_column("Mode")
    table.add_column("Checks")
    for index, (_, label, description) in enumerate(modes, start=1):
        table.add_row(str(index), label, description)
    table.add_row("0", "Back", "cancel automatic test")
    console.print(table)

    choice = _prompt_menu_choice(prompt="Test mode", default="1")
    if choice == "0":
        return None
    selected = int(choice)
    if selected < 1 or selected > len(modes):
        raise typer.BadParameter(f"Choose a number between 1 and {len(modes)}, or 0")
    return modes[selected - 1][0]


def _print_generated_aliases_table(snapshot: dict[str, Any] | None) -> None:
    table = Table(title="Generated Aliases", box=box.ASCII)
    table.add_column("Alias")
    table.add_column("Modality")
    table.add_column("Scope")
    table.add_column("Category")
    table.add_column("Candidates")
    aliases = []
    if isinstance(snapshot, dict):
        raw_aliases = snapshot.get("generated_aliases", [])
        if isinstance(raw_aliases, list):
            aliases = [item for item in raw_aliases if isinstance(item, dict)]
    if not aliases:
        table.add_row("-", "-", "-", "-", "<empty>")
        console.print(table)
        return
    for item in aliases:
        candidate_labels = []
        for candidate in item.get("candidates", []):
            if not isinstance(candidate, dict):
                continue
            provider = str(candidate.get("provider", "")).strip()
            model_id = str(candidate.get("model_id", "")).strip()
            if provider and model_id:
                candidate_labels.append(f"{provider}/{model_id}")
        table.add_row(
            str(item.get("alias_id", "")),
            str(item.get("modality", "")),
            str(item.get("scope", "")),
            str(item.get("category", "")),
            " -> ".join(candidate_labels[:4]) or "<empty>",
        )
    console.print(table)


def _print_custom_aliases_table(cfg: GatewayConfig) -> None:
    table = Table(title="Custom Aliases (config.yaml)", box=box.ASCII)
    table.add_column("Alias")
    table.add_column("Strategy")
    table.add_column("Candidates")
    if not cfg.routes.aliases:
        table.add_row("-", "-", "<empty>")
        console.print(table)
        return
    for alias, route in cfg.routes.aliases.items():
        candidates = " -> ".join(f"{c.provider}/{c.model}" for c in route.candidates) or "<empty>"
        table.add_row(alias, route.strategy, candidates)
    console.print(table)


def _runtime_key_registry(cfg: GatewayConfig) -> KeyRegistry:
    db = SQLiteDB(cfg.storage.sqlite_path)
    schema_path = files("app.storage").joinpath("schema.sql")
    db.initialize(str(schema_path))
    registry = KeyRegistry(KeysRuntimeRepository(db))
    registry.sync_defaults(cfg)
    return registry


def _route_memory_repo(cfg: GatewayConfig) -> RouteModelMemoryRepository:
    db = SQLiteDB(cfg.storage.sqlite_path)
    schema_path = files("app.storage").joinpath("schema.sql")
    db.initialize(str(schema_path))
    return RouteModelMemoryRepository(db)


def _model_runtime_repo(cfg: GatewayConfig) -> ModelRuntimeRepository:
    db = SQLiteDB(cfg.storage.sqlite_path)
    schema_path = files("app.storage").joinpath("schema.sql")
    db.initialize(str(schema_path))
    return ModelRuntimeRepository(db)


def _alias_raw_candidates(
    cfg: GatewayConfig,
    model: str,
    snapshot: dict[str, Any] | None = None,
) -> list[RouteCandidate]:
    generated_alias = _generated_alias_map(snapshot).get(model)
    if generated_alias is not None:
        return [
            RouteCandidate(provider=str(candidate.get("provider", "")), model=str(candidate.get("model_id", "")))
            for candidate in generated_alias.get("candidates", [])
            if isinstance(candidate, dict)
            and str(candidate.get("provider", "")).strip()
            and str(candidate.get("model_id", "")).strip()
        ]
    if model in cfg.routes.aliases:
        return [RouteCandidate(provider=c.provider, model=c.model) for c in cfg.routes.aliases[model].candidates]
    if "/" in model:
        provider, model_name = model.split("/", 1)
        return [RouteCandidate(provider=provider, model=model_name)]
    return [RouteCandidate(provider=provider_name, model=model) for provider_name in cfg.providers]


def _generated_candidate_sources(snapshot: dict[str, Any] | None) -> dict[tuple[str, str], list[str]]:
    sources: dict[tuple[str, str], list[str]] = {}
    for alias_id, alias in _generated_alias_map(snapshot).items():
        candidates = alias.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            provider = str(candidate.get("provider", "")).strip()
            model_id = str(candidate.get("model_id", "")).strip()
            if not provider or not model_id:
                continue
            sources.setdefault((provider, model_id), []).append(alias_id)
    return sources


def _candidate_source_label(
    candidate: RouteCandidate,
    *,
    alias: str | None,
    generated_sources: dict[tuple[str, str], list[str]],
) -> str:
    sources = generated_sources.get((candidate.provider, candidate.model), [])
    if alias and alias in sources:
        return alias
    if sources:
        return sources[0]
    return alias or "direct model"


def _summarize_values(values: list[Any], empty: str = "-") -> str:
    compact = [str(value) for value in values if value not in (None, "")]
    if not compact:
        return empty
    counts: dict[str, int] = {}
    for value in compact:
        counts[value] = counts.get(value, 0) + 1
    return ", ".join(f"{value}:{count}" if count > 1 else value for value, count in counts.items())


def _candidate_runtime_details(
    cfg: GatewayConfig,
    registry: KeyRegistry,
    candidate: RouteCandidate,
    runtime_map: dict[str, dict],
) -> dict[str, str]:
    provider = cfg.providers.get(candidate.provider)
    if provider is None:
        return {
            "status": "skipped",
            "reason": "provider_not_configured",
            "config_keys": "0",
            "available_keys": "0",
            "runtime_active": "0",
            "runtime_status": "-",
            "cooldown": "-",
            "errors": "0",
            "last_error": "-",
        }
    if not provider.enabled:
        return {
            "status": "skipped",
            "reason": "provider_disabled",
            "config_keys": str(len(provider.keys)),
            "available_keys": "0",
            "runtime_active": "0",
            "runtime_status": "-",
            "cooldown": "-",
            "errors": "0",
            "last_error": "-",
        }

    configured_keys = [key for key in provider.keys if is_configured_secret(key.key)]
    active_configured_keys = [key for key in configured_keys if key.active]
    available_keys = registry.get_available_keys(cfg, candidate.provider)
    provider_states = [runtime_map.get(key.id, {}) for key in configured_keys]
    runtime_active = [
        key
        for key in active_configured_keys
        if bool(runtime_map.get(key.id, {}).get("active", 1))
    ]
    statuses = _summarize_values([state.get("status", "unknown") for state in provider_states])
    cooldowns = _summarize_values([state.get("cooldown_until") for state in provider_states])
    errors = max([int(state.get("consecutive_errors", 0) or 0) for state in provider_states] or [0])
    last_error = _summarize_values([state.get("last_error_code") for state in provider_states])
    details = {
        "config_keys": str(len(configured_keys)),
        "available_keys": str(len(available_keys)),
        "runtime_active": str(len(runtime_active)),
        "runtime_status": statuses,
        "cooldown": cooldowns,
        "errors": str(errors),
        "last_error": last_error,
    }
    if not available_keys:
        if active_configured_keys:
            return {"status": "skipped", "reason": "keys_unhealthy_or_cooling_down", **details}
        return {"status": "skipped", "reason": "no_active_configured_keys", **details}
    return {"status": "ready", "reason": "keys_available", **details}


def _analysis_value_rows(analysis: RequestRouteAnalysis) -> list[tuple[str, str]]:
    reasons = ", ".join(analysis.reasons) if analysis.reasons else "-"
    return [
        ("Intent", analysis.intent),
        ("Profile", analysis.profile),
        ("Complexity", str(analysis.complexity_score)),
        ("Context bucket", analysis.context_bucket),
        ("Token estimate", str(analysis.token_estimate)),
        ("Tools", "yes" if analysis.requires_tools else "no"),
        ("Reasons", reasons),
    ]


def _print_request_analysis(analysis: RequestRouteAnalysis, title: str = "Request Route Analysis") -> None:
    table = Table(title=title, box=box.ASCII)
    table.add_column("Field")
    table.add_column("Value")
    for key, value in _analysis_value_rows(analysis):
        table.add_row(key, value)
    console.print(table)


def _extract_route_analysis(response: httpx.Response) -> dict[str, Any]:
    detail = _extract_error_detail(response)
    details = detail.get("details")
    if not isinstance(details, dict):
        return {}
    analysis = details.get("analysis")
    return analysis if isinstance(analysis, dict) else {}


def _extract_route_memory(response: httpx.Response) -> dict[str, Any]:
    detail = _extract_error_detail(response)
    details = detail.get("details")
    if not isinstance(details, dict):
        return {}
    route_memory = details.get("route_memory")
    return route_memory if isinstance(route_memory, dict) else {}


def _print_route_analysis_dict(analysis: dict[str, Any]) -> None:
    if not analysis:
        return
    table = Table(title="Request Route Analysis", box=box.ASCII)
    table.add_column("Field")
    table.add_column("Value")
    for key in ("intent", "profile", "complexity_score", "context_bucket", "token_estimate", "requires_tools"):
        if key in analysis:
            table.add_row(key, str(analysis.get(key)))
    reasons = analysis.get("reasons")
    if isinstance(reasons, list):
        table.add_row("reasons", ", ".join(str(item) for item in reasons) or "-")
    console.print(table)


def _print_route_memory_dict(route_memory: dict[str, Any]) -> None:
    if not route_memory:
        return
    table = Table(title="Route Memory", box=box.ASCII)
    table.add_column("Field")
    table.add_column("Value")
    for key in (
        "status",
        "route_alias",
        "profile",
        "context_bucket",
        "remembered_provider",
        "remembered_model",
        "success_count",
        "avg_latency_ms",
        "updated_at",
        "position_before",
    ):
        if key in route_memory:
            table.add_row(key, str(route_memory.get(key)))
    console.print(table)


def _print_candidate_diagnostics(candidates: list[dict]) -> None:
    if not candidates:
        return
    table = Table(title="Route Candidate Diagnostics", box=box.ASCII)
    table.add_column("#")
    table.add_column("Provider")
    table.add_column("Model")
    table.add_column("Status")
    table.add_column("Reason")
    table.add_column("Keys")
    table.add_column("Context")
    for index, item in enumerate(candidates, start=1):
        table.add_row(
            str(index),
            str(item.get("provider", "")),
            str(item.get("model", "")),
            str(item.get("status", "")),
            str(item.get("reason", "")),
            str(item.get("available_keys", "")),
            (
                f"{item.get('token_estimate')}>{item.get('max_context_tokens')}"
                if item.get("token_estimate") and item.get("max_context_tokens")
                else ""
            ),
        )
    console.print(table)
    for index, item in enumerate(candidates, start=1):
        console.print(
            "Candidate diagnostic: "
            f"#{index} provider={item.get('provider', '')} "
            f"model={item.get('model', '')} "
            f"status={item.get('status', '')} "
            f"reason={item.get('reason', '')}"
        )


def _extract_error_detail(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    detail = payload.get("detail")
    if not isinstance(detail, dict):
        return {}
    return detail


def _extract_candidate_diagnostics(response: httpx.Response) -> list[dict]:
    detail = _extract_error_detail(response)
    if not detail:
        return []
    details = detail.get("details")
    if not isinstance(details, dict):
        return []
    candidates = details.get("candidates")
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, dict)]


def _generated_alias_category(snapshot: dict[str, Any] | None, alias_id: str | None) -> str | None:
    if not alias_id or not isinstance(snapshot, dict):
        return None
    raw_aliases = snapshot.get("generated_aliases", [])
    if not isinstance(raw_aliases, list):
        return None
    for item in raw_aliases:
        if isinstance(item, dict) and item.get("alias_id") == alias_id:
            return str(item.get("category") or "")
    return None


def _is_free_alias_id(snapshot: dict[str, Any] | None, alias_id: str | None) -> bool:
    if not alias_id:
        return False
    return (
        alias_id in {"auto/free", "auto/text/free"}
        or alias_id.endswith("/text/free")
        or _generated_alias_category(snapshot, alias_id) == "free"
    )


def _print_route_preview(config_path: str, model: str | None = None) -> None:
    cfg = load_gateway_config(config_path=config_path)
    snapshot = _current_inventory_snapshot(config_path, refresh=True)
    registry = _runtime_key_registry(cfg)
    runtime_map = {item["key_id"]: item for item in registry.runtime_repo.list_states()}
    aliases = _generated_alias_ids(snapshot) or list(cfg.routes.aliases)
    if model is None:
        if aliases:
            _print_numbered_items("Route aliases", aliases)
            selected = _prompt_numbered_choice(len(aliases), "Alias number")
            model = aliases[selected - 1]
        else:
            model = typer.prompt("Model or alias", default="auto/general").strip()

    request = UnifiedLLMRequest(
        model=model,
        messages=[ChatMessage(role="user", content="hello")],
        metadata={"sor_profile": "fast"},
    )
    analysis = analyze_request_route(request)
    memory_repo = _route_memory_repo(cfg)
    generated_aliases = []
    if isinstance(snapshot, dict):
        raw_generated = snapshot.get("generated_aliases", [])
        if isinstance(raw_generated, list):
            from app.inventory.models import GeneratedAlias, GeneratedAliasCandidate

            generated_aliases = [
                GeneratedAlias(
                    alias_id=str(item.get("alias_id", "")),
                    scope=str(item.get("scope", "global")),
                    modality=str(item.get("modality", "text")),
                    category=str(item.get("category", "")),
                    provider_scope=item.get("provider_scope"),
                    candidates=[
                        GeneratedAliasCandidate(
                            provider=str(candidate.get("provider", "")),
                            model_id=str(candidate.get("model_id", "")),
                            candidate_type=str(candidate.get("candidate_type", "model")),
                        )
                        for candidate in item.get("candidates", [])
                        if isinstance(candidate, dict)
                    ],
                    generation_reason=str(item.get("generation_reason", "")),
                )
                for item in raw_generated
                if isinstance(item, dict)
            ]
    planned, alias = plan_candidates(cfg, request, generated_aliases=generated_aliases)
    context_limits = limits_from_snapshot_dict(snapshot)
    planned, context_skipped = filter_candidates_by_context(planned, analysis.token_estimate, context_limits)
    raw_candidates = _alias_raw_candidates(cfg, model, snapshot)
    planned_keys = {(candidate.provider, candidate.model) for candidate in planned}
    generated_sources = _generated_candidate_sources(snapshot)
    route_memory = memory_repo.get(alias, analysis.profile, analysis.context_bucket) if alias else None
    remembered_marker = (
        route_memory.get("provider"),
        route_memory.get("model"),
    ) if route_memory else (None, None)
    route_memory_status = "ignored_direct"
    if alias and route_memory is None:
        route_memory_status = "miss"
    elif alias and remembered_marker in planned_keys:
        route_memory_status = "hit"
        planned = [
            candidate
            for candidate in planned
            if (candidate.provider, candidate.model) == remembered_marker
        ] + [
            candidate
            for candidate in planned
            if (candidate.provider, candidate.model) != remembered_marker
        ]
        planned_keys = {(candidate.provider, candidate.model) for candidate in planned}
    elif alias and route_memory is not None:
        route_memory_status = "stale"

    summary = Table(title="Route Preview", box=box.ASCII)
    summary.add_column("Field")
    summary.add_column("Value")
    summary.add_row("Requested model", model)
    summary.add_row("Resolved alias", alias or "<direct model>")
    summary.add_row(
        "Selected source",
        _candidate_source_label(planned[0], alias=alias, generated_sources=generated_sources) if planned else "<none>",
    )
    summary.add_row("Detected intent", analysis.intent)
    summary.add_row("Route profile", analysis.profile)
    summary.add_row("Complexity", str(analysis.complexity_score))
    summary.add_row("Context bucket", analysis.context_bucket)
    summary.add_row("Route memory", route_memory_status)
    if route_memory:
        summary.add_row("Remembered model", f"{route_memory.get('provider')}/{route_memory.get('model')}")
    if context_skipped:
        summary.add_row("Context filtered", str(len(context_skipped)))
    if _is_free_alias_id(snapshot, alias):
        summary.add_row("Free-only", "yes")
        summary.add_row("Paid fallback", "disabled")
        summary.add_row("Max free attempts", str(cfg.routing.free_alias.max_candidates_per_request))
        summary.add_row(
            "Stop on free-tier 429",
            "yes" if cfg.routing.free_alias.stop_on_provider_free_tier_rate_limit else "no",
        )
    summary.add_row("Planned candidates", str(len(planned)))
    console.print(summary)
    _print_request_analysis(analysis)
    if route_memory:
        _print_route_memory_dict(
            {
                "status": route_memory_status,
                "route_alias": alias,
                "profile": analysis.profile,
                "context_bucket": analysis.context_bucket,
                "remembered_provider": route_memory.get("provider"),
                "remembered_model": route_memory.get("model"),
                "success_count": route_memory.get("success_count"),
                "avg_latency_ms": route_memory.get("avg_latency_ms"),
                "updated_at": route_memory.get("updated_at"),
            }
        )

    effective_table = Table(title="Effective Candidate Order", box=box.ASCII)
    effective_table.add_column("#")
    effective_table.add_column("Provider")
    effective_table.add_column("Model")
    effective_table.add_column("Source")
    effective_table.add_column("Memory")
    effective_table.add_column("Context")
    for index, candidate in enumerate(planned, start=1):
        limit = context_limits.get((candidate.provider, candidate.model))
        context_label = (
            str(limit.max_context_tokens or limit.max_input_tokens)
            if limit and (limit.max_context_tokens or limit.max_input_tokens)
            else "unknown"
        )
        memory_label = "remembered" if route_memory_status == "hit" and index == 1 else "-"
        effective_table.add_row(
            str(index),
            candidate.provider,
            candidate.model,
            _candidate_source_label(candidate, alias=alias, generated_sources=generated_sources),
            memory_label,
            context_label,
        )
    if not planned:
        effective_table.add_row("-", "-", "-", "-", route_memory_status, "no candidates after filters")
    console.print(effective_table)

    table = Table(title="Candidates", box=box.ASCII)
    table.add_column("#")
    table.add_column("Provider")
    table.add_column("Model")
    table.add_column("Order")
    table.add_column("Status")
    table.add_column("Reason")
    table.add_column("Context")
    runtime_table = Table(title="Key Runtime Details", box=box.ASCII)
    runtime_table.add_column("#")
    runtime_table.add_column("Provider")
    runtime_table.add_column("Config")
    runtime_table.add_column("Available")
    runtime_table.add_column("Active")
    runtime_table.add_column("Runtime status")
    runtime_table.add_column("Cooldown")
    runtime_table.add_column("Errors")
    runtime_table.add_column("Last error")
    runtime_lines: list[str] = []
    for index, candidate in enumerate(raw_candidates, start=1):
        details = _candidate_runtime_details(cfg, registry, candidate, runtime_map)
        context_skip = context_skip_detail(candidate, analysis.token_estimate, context_limits)
        context_label = "-"
        if context_skip is not None:
            details["status"] = "skipped"
            details["reason"] = "context_too_large"
            context_label = f"{context_skip['token_estimate']}>{context_skip['max_context_tokens']}"
        if (candidate.provider, candidate.model) not in planned_keys and details["status"] == "ready":
            details["status"] = "filtered"
            details["reason"] = "not_selected_by_route_planner"
        order = "-"
        for planned_index, planned_candidate in enumerate(planned, start=1):
            if planned_candidate.provider == candidate.provider and planned_candidate.model == candidate.model:
                order = str(planned_index)
                break
        table.add_row(
            str(index),
            candidate.provider,
            candidate.model,
            order,
            details["status"],
            details["reason"],
            context_label,
        )
        runtime_table.add_row(
            str(index),
            candidate.provider,
            details["config_keys"],
            details["available_keys"],
            details["runtime_active"],
            details["runtime_status"],
            details["cooldown"],
            details["errors"],
            details["last_error"],
        )
        runtime_lines.append(
            "Runtime: "
            f"#{index} provider={candidate.provider} "
            f"status={details['runtime_status']} "
            f"cooldown={details['cooldown']} "
            f"errors={details['errors']} "
            f"last_error={details['last_error']}"
        )
    console.print(table)
    for index, candidate in enumerate(raw_candidates, start=1):
        details = _candidate_runtime_details(cfg, registry, candidate, runtime_map)
        context_skip = context_skip_detail(candidate, analysis.token_estimate, context_limits)
        if context_skip is not None:
            details["status"] = "skipped"
            details["reason"] = "context_too_large"
        if (candidate.provider, candidate.model) not in planned_keys and details["status"] == "ready":
            details["status"] = "filtered"
            details["reason"] = "not_selected_by_route_planner"
        console.print(
            "Candidate preview: "
            f"#{index} provider={candidate.provider} "
            f"model={candidate.model} "
            f"order={next((str(i) for i, item in enumerate(planned, start=1) if item.provider == candidate.provider and item.model == candidate.model), '-')} "
            f"source={_candidate_source_label(candidate, alias=alias, generated_sources=generated_sources)} "
            f"status={details['status']} "
            f"reason={details['reason']}"
        )
    console.print("Runtime status details")
    for line in runtime_lines:
        console.print(line)
    console.print(runtime_table)


def _print_troubleshooting_guide() -> None:
    table = Table(title="SimpleOpenRoad Troubleshooting", box=box.ASCII)
    table.add_column("Symptom")
    table.add_column("Meaning")
    table.add_column("Action")
    table.add_row(
        "401 Unauthorized",
        "Client is not sending the current MASTER_API_KEY.",
        "Open Gateway -> API access token and test, copy x-api-key or Bearer token, then retry.",
    )
    table.add_row(
        "422 Unprocessable Entity",
        "Client sent a payload outside the OpenAI-compatible shape accepted by SOR.",
        "Update SOR, check /v1 base URL, and retry with chat/completions compatible fields.",
    )
    table.add_row(
        "429 Too Many Requests",
        "Provider or key is rate limited.",
        "Wait for cooldown, add another key, or use Route preview to move to a less limited route.",
    )
    table.add_row(
        "503 No healthy route candidates",
        "All candidates were filtered, cooling down, disabled, invalid, or unsupported.",
        "Run Route preview and inspect Request Route Analysis, Effective Candidate Order, and Candidate preview lines.",
    )
    table.add_row(
        "context_too_large",
        "Known model context limit is smaller than the estimated request tokens.",
        "Use a larger-context alias/model, reduce history, or refresh inventory if limits changed.",
    )
    table.add_row(
        "Route memory hit/stale/miss",
        "SOR remembers the last successful model per alias/profile/context bucket.",
        "A hit only reorders candidates; stale is ignored; direct model requests show ignored_direct.",
    )
    table.add_row(
        "Invalid/empty API response",
        "Provider returned no assistant content/tool calls, malformed SSE, or an unusable final message.",
        "Use a stronger/tool-capable alias for agents, check runtime logs, and keep fallback candidates in the alias.",
    )
    table.add_row(
        "Client works in /v1/models but not chat",
        "Auth and base URL are OK, routing/provider execution is failing.",
        "Run automatic API test and Route preview; inspect provider/key status and candidate diagnostics.",
    )
    console.print(table)


def _print_openai_client_examples(config_path: str) -> None:
    cfg = load_gateway_config(config_path=config_path)
    snapshot = _current_inventory_snapshot(config_path, refresh=False)
    api_base = _resolve_api_base_url(cfg)
    openai_base = f"{api_base}/v1"
    model = _recommended_model_alias(cfg, snapshot)
    table = Table(title="OpenAI-Compatible Client Setup", box=box.ASCII)
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Base URL", openai_base)
    table.add_row("API key", "MASTER_API_KEY from .env")
    table.add_row("Auth header", "Authorization: Bearer <MASTER_API_KEY>")
    table.add_row("Alternative header", "x-api-key: <MASTER_API_KEY>")
    table.add_row("Recommended model", model)
    table.add_row("Other aliases", _format_model_aliases(cfg, snapshot))
    console.print(table)
    console.print("For Cline/OpenAI-compatible clients, use the Base URL with /v1 and one of the auto/... aliases.")


def _print_quick_status(config_path: str) -> None:
    cfg = load_gateway_config(config_path=config_path)
    snapshot = _current_inventory_snapshot(config_path, refresh=False)
    configured_keys = [
        key
        for provider in cfg.providers.values()
        for key in provider.keys
        if key.active and is_configured_secret(key.key)
    ]
    enabled_providers = [name for name, provider in cfg.providers.items() if provider.enabled]
    table = Table(title="SimpleOpenRoad Quick Status", box=box.ASCII)
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Config", config_path)
    table.add_row("Local gateway", _resolve_local_api_base_url(cfg))
    table.add_row("Public/OpenAI base", f"{_resolve_api_base_url(cfg)}/v1")
    table.add_row("Enabled providers", str(len(enabled_providers)))
    table.add_row("Active configured keys", str(len(configured_keys)))
    table.add_row("Aliases", _format_model_aliases(cfg, snapshot))
    table.add_row("Recommended model", _recommended_model_alias(cfg, snapshot))
    console.print(table)


def _run_setup_wizard(config_path: str) -> None:
    cfg = load_gateway_config(config_path=config_path)
    _print_setup_summary(config_path=config_path, cfg=cfg)
    if typer.confirm("Add provider key now", default=False):
        _interactive_add_provider_key(config_path=config_path)
    if typer.confirm("Restart system service now", default=False):
        service_restart(mode="system")
    if typer.confirm("Run automatic API test now", default=True):
        _test_api_request(config_path=config_path)


def _print_setup_summary(config_path: str, cfg: GatewayConfig) -> None:
    snapshot = _current_inventory_snapshot(config_path, refresh=False)
    api_base = _resolve_api_base_url(cfg)
    openai_base = f"{api_base}/v1"
    console.print("Setup complete. Management and API endpoints:")
    console.print(f"- CLI: sor doctor --config-path {config_path}")
    console.print("- OpenAI-compatible plugin settings:")
    console.print(f"  Base URL: {openai_base}")
    console.print("  API key: MASTER_API_KEY from .env or Gateway -> API access token and test")
    console.print(f"  Models: {_format_model_aliases(cfg, snapshot)}")
    console.print(f"  Recommended default: {_recommended_model_alias(cfg, snapshot)}")
    console.print("  Direct model format: provider/model or exact model id")
    console.print("  Generated aliases are built from current provider inventory; direct provider/model ids also work")
    console.print(f"- Chat endpoint: {openai_base}/chat/completions")
    console.print(f"- Responses endpoint: {openai_base}/responses")
    console.print(f"- Health: {api_base}/health")
    _print_alias_help_table(cfg, snapshot)


def _resolve_local_api_base_url(cfg: GatewayConfig) -> str:
    host = str(cfg.server.host).strip().lower()
    if host in {"", "0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    return f"http://{host}:{cfg.server.port}"


def _provider_category(provider_name: str) -> str:
    return provider_category(provider_name)


def _provider_display_name(provider_name: str) -> str:
    return provider_display_name(provider_name)


def _sorted_provider_names(provider_names: list[str]) -> list[str]:
    return sorted_provider_names(provider_names)


def _search_provider_names(provider_names: list[str], query: str) -> list[str]:
    if not query.strip():
        return []
    return search_provider_names(provider_names, query)


def _print_provider_choices(provider_names: list[str]) -> list[str]:
    ordered = _sorted_provider_names(provider_names)
    featured = [name for name in ordered if name in FEATURED_PROVIDER_SET]
    experimental = [name for name in ordered if name in EXPERIMENTAL_PROVIDER_SET]
    other = [
        name
        for name in ordered
        if name not in FEATURED_PROVIDER_SET and name not in EXPERIMENTAL_PROVIDER_SET
    ]
    hidden_other_count = max(0, len(other) - OTHER_PROVIDER_DISPLAY_LIMIT)
    displayed_other = other[:OTHER_PROVIDER_DISPLAY_LIMIT]
    groups = [
        ("Featured providers", featured),
        ("Experimental providers", experimental),
        ("Other providers", displayed_other),
    ]
    displayed: list[str] = []
    index = 1
    for title, items in groups:
        console.print(f"--- {title} ---")
        if not items:
            console.print("<none>")
            continue
        for provider in items:
            console.print(f"{index}) {provider} - {_provider_display_name(provider)}")
            displayed.append(provider)
            index += 1
    if hidden_other_count:
        console.print(f"... {hidden_other_count} more provider(s). Use S to search or M for manual provider id.")
    console.print("S) Search provider")
    console.print("M) Manual provider id")
    return displayed


def _select_provider_from_names(provider_names: list[str], prompt: str = "Select provider") -> str:
    if not provider_names:
        raise typer.BadParameter("No providers configured")
    provider_set = set(provider_names)
    displayed = _print_provider_choices(provider_names)
    raw_choice = typer.prompt(prompt, default="1").strip()
    normalized = raw_choice.lower()
    if normalized == "s":
        query = typer.prompt("Search provider").strip()
        matches = _search_provider_names(provider_names, query)
        if not matches:
            raise typer.BadParameter(f"No provider matches: {query}")
        displayed_matches = _print_provider_choices(matches)
        selected = _prompt_numbered_choice(len(displayed_matches), "Provider number")
        return displayed_matches[selected - 1]
    if normalized == "m":
        provider = typer.prompt("Provider id").strip()
        if provider not in provider_set:
            raise typer.BadParameter(f"Provider is not configured: {provider}")
        return provider
    if not raw_choice.isdigit():
        raise typer.BadParameter("Provider selection must be a number, S, or M")
    selected_index = int(raw_choice)
    if selected_index < 1 or selected_index > len(displayed):
        raise typer.BadParameter("Selected provider index is out of range. Use S to search hidden providers.")
    return displayed[selected_index - 1]


def _current_master_api_key() -> str:
    created_env, generated_keys = _ensure_env_master_admin_keys()
    _print_env_setup_hint(created_env=created_env, generated_keys=generated_keys)
    return os.getenv("MASTER_API_KEY") or _load_env_file().get("MASTER_API_KEY", "")


def _current_admin_api_key() -> str:
    created_env, generated_keys = _ensure_env_master_admin_keys()
    _print_env_setup_hint(created_env=created_env, generated_keys=generated_keys)
    return os.getenv("ADMIN_API_KEY") or _load_env_file().get("ADMIN_API_KEY", "")


def _reload_running_gateway(config_path: str, cfg: GatewayConfig | None = None, *, quiet: bool = False) -> bool:
    cfg = cfg or load_gateway_config(config_path=config_path)
    if not cfg.security.require_admin_key:
        headers: dict[str, str] = {}
    else:
        admin_key = _current_admin_api_key()
        if not admin_key:
            if not quiet:
                console.print("Running gateway reload skipped: ADMIN_API_KEY is not configured.")
            return False
        headers = {"x-admin-key": admin_key}

    api_base = _resolve_local_api_base_url(cfg)
    config_path_abs = str(_config_path(config_path))
    try:
        response = httpx.post(
            f"{api_base}/admin/reload-config",
            headers=headers,
            json={"config_path": config_path_abs},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        if not quiet:
            console.print(f"Running gateway reload skipped: {exc}")
        return False

    if response.status_code != 200:
        if not quiet:
            console.print(f"Running gateway reload failed: HTTP {response.status_code} {response.text[:300]}")
        return False

    if not quiet:
        try:
            generated_aliases = response.json().get("generated_aliases")
        except ValueError:
            generated_aliases = None
        suffix = f" ({generated_aliases} generated aliases)" if generated_aliases is not None else ""
        console.print(f"Running gateway reloaded{suffix}.")
    return True


def _print_api_access(config_path: str) -> None:
    cfg = load_gateway_config(config_path=config_path)
    snapshot = _current_inventory_snapshot(config_path, refresh=False)
    token = _current_master_api_key()
    api_base = _resolve_api_base_url(cfg)
    openai_base = f"{api_base}/v1"

    console.print(
        Panel.fit(
            "SimpleOpenRoad API Access",
            title="Access Token",
            border_style="green",
            box=box.ASCII,
        )
    )
    table = Table(title="User API Auth")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Protection", "enabled" if cfg.security.require_master_key else "disabled")
    table.add_row("OpenAI-compatible Base URL", openai_base)
    table.add_row("Chat endpoint", f"{openai_base}/chat/completions")
    table.add_row("Model aliases", _format_model_aliases(cfg, snapshot))
    table.add_row("Direct model", "provider/model or exact model id")
    table.add_row("MASTER_API_KEY", token if cfg.security.require_master_key else "<not required>")
    table.add_row("Header", "x-api-key: <MASTER_API_KEY>")
    table.add_row("Alt header", "Authorization: Bearer <MASTER_API_KEY>")
    console.print(table)
    _print_alias_help_table(cfg, snapshot)
    console.print("Use Gateway -> Test API request to run an automatic local check.")


def _regenerate_master_api_key(restart_service: bool = False) -> str:
    _ensure_env_master_admin_keys()
    new_token = _generate_api_key(40)
    _set_env_value("MASTER_API_KEY", new_token)
    console.print("Generated new MASTER_API_KEY in .env")
    console.print(f"MASTER_API_KEY: {new_token}")
    console.print("A running service must be restarted before it accepts the new token.")
    if restart_service:
        service_restart(mode="system")
    return new_token


def _api_test_payload(model: str, mode: str) -> dict:
    if mode == "cline":
        return {
            "model": model,
            "stream": True,
            "messages": [
                {"role": "system", "content": "You are a concise coding assistant."},
                {"role": "user", "content": "Reply with a short greeting."},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "noop",
                        "description": "No operation test tool.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    },
                }
            ],
            "tool_choice": "auto",
            "stream_options": {"include_usage": True},
        }
    if mode == "tools":
        return {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with a short greeting."}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "noop",
                        "description": "No operation test tool.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            "tool_choice": "auto",
        }
    if mode == "stream":
        return {
            "model": model,
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        }
    return {
        "model": model,
        "messages": [{"role": "user", "content": "hello"}],
    }


def _extract_stream_preview(text: str) -> str:
    fragments: list[str] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if not choices:
            continue
        delta = choices[0].get("delta", {}) if isinstance(choices[0], dict) else {}
        content = delta.get("content") if isinstance(delta, dict) else None
        if content:
            fragments.append(str(content))
    return "".join(fragments).strip()


def _test_api_request(config_path: str, model: str = "auto/fast", mode: str = "simple") -> None:
    cfg = load_gateway_config(config_path=config_path)
    _reload_running_gateway(config_path=config_path, cfg=cfg, quiet=True)
    token = _current_master_api_key()
    api_base = _resolve_local_api_base_url(cfg)
    url = f"{api_base}/v1/chat/completions"
    payload = _api_test_payload(model, mode)
    analysis = analyze_request_route(
        UnifiedLLMRequest(model=model, messages=[ChatMessage(role="user", content="hello")])
    )
    headers = {"Content-Type": "application/json"}
    if cfg.security.require_master_key:
        headers["x-api-key"] = token

    table = Table(title="Automatic API Test")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("URL", url)
    table.add_row("Model", model)
    table.add_row("Mode", mode)
    table.add_row("Auth", "x-api-key" if cfg.security.require_master_key else "disabled")
    table.add_row("Intent", analysis.intent)
    table.add_row("Profile", analysis.profile)
    table.add_row("Complexity", str(analysis.complexity_score))
    table.add_row("Context bucket", analysis.context_bucket)
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        table.add_row("HTTP status", str(response.status_code))
        if response.status_code == 200:
            text = ""
            if payload.get("stream"):
                text = _extract_stream_preview(response.text)
                data = {}
            else:
                data = response.json()
                choices = data.get("choices", []) if isinstance(data, dict) else []
                if choices:
                    text = str(choices[0].get("message", {}).get("content", ""))
            table.add_row("Result", "ok")
            selected_model = response.headers.get("x-sor-selected-model") or (
                str(data.get("model", "")) if isinstance(data, dict) else ""
            )
            if selected_model:
                table.add_row("Answered model", selected_model)
            failed_candidates = response.headers.get("x-sor-failed-candidates", "").strip()
            if failed_candidates:
                table.add_row("Failed candidates", failed_candidates)
            table.add_row("Response", text[:300] or "<empty>")
        else:
            table.add_row("Result", "failed")
            detail = _extract_error_detail(response)
            message = str(detail.get("message") or response.text[:500] or "<empty>")
            error_type = str(detail.get("type") or "<unknown>")
            table.add_row("Error type", error_type)
            table.add_row("Message", message[:500])
            if detail.get("provider") or detail.get("key_id"):
                table.add_row("Provider", str(detail.get("provider") or "<none>"))
                table.add_row("Key ID", str(detail.get("key_id") or "<none>"))
            details = detail.get("details")
            free_alias = details.get("free_alias") if isinstance(details, dict) else None
            if isinstance(free_alias, dict) and free_alias.get("free_only"):
                table.add_row("Free-only", "yes")
                table.add_row("Paid fallback", str(free_alias.get("paid_fallback") or "disabled"))
                if free_alias.get("max_candidates_per_request") is not None:
                    table.add_row("Max free attempts", str(free_alias.get("max_candidates_per_request")))
                if details.get("rate_limit_scope") == "provider_free_tier":
                    table.add_row("Reason", "provider free-tier rate limit")
            candidates = _extract_candidate_diagnostics(response)
            failed_candidates = ", ".join(
                f"{item.get('provider')}/{item.get('model')}"
                for item in candidates
                if item.get("provider") and item.get("model") and item.get("status") != "ready"
            )
            if failed_candidates:
                table.add_row("Failed candidates", failed_candidates[:500])
            if candidates:
                table.add_row("Diagnostics", "see Route Candidate Diagnostics below")
            elif response.text:
                table.add_row("Response", response.text[:500])
    except Exception as exc:  # noqa: BLE001
        table.add_row("Result", "failed")
        table.add_row("Error", str(exc))
    console.print(table)
    if "response" in locals() and response.status_code != 200:
        _print_route_analysis_dict(_extract_route_analysis(response))
        _print_route_memory_dict(_extract_route_memory(response))
        _print_candidate_diagnostics(_extract_candidate_diagnostics(response))


def _run_interactive_api_test(config_path: str) -> None:
    selected_model = _select_test_alias(config_path)
    if selected_model is None:
        return
    mode = _select_api_test_mode()
    if mode is None:
        return
    _test_api_request(config_path=config_path, model=selected_model, mode=mode)


def _generate_api_key(length: int = 40) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _ensure_env_master_admin_keys(
    env_path: Path = Path(".env"),
    env_example_path: Path = Path(".env.example"),
) -> tuple[bool, list[str]]:
    created_env = False
    if not env_path.exists() and env_example_path.exists():
        shutil.copyfile(env_example_path, env_path)
        created_env = True

    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    line_index: dict[str, int] = {}
    values: dict[str, str] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        normalized_key = key.strip()
        line_index[normalized_key] = index
        values[normalized_key] = value.strip()

    changed = False
    generated_keys: list[str] = []
    for key_name in ("MASTER_API_KEY", "ADMIN_API_KEY"):
        current = values.get(key_name, "")
        if current in _PLACEHOLDER_ENV_VALUES:
            new_value = _generate_api_key(40)
            generated_keys.append(key_name)
            values[key_name] = new_value
            if key_name in line_index:
                lines[line_index[key_name]] = f"{key_name}={new_value}"
            else:
                lines.append(f"{key_name}={new_value}")
            os.environ[key_name] = new_value
            changed = True
            continue

        if current and key_name not in os.environ:
            os.environ[key_name] = current

    if changed:
        env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    return created_env, generated_keys


def _print_env_setup_hint(created_env: bool, generated_keys: list[str], env_path: Path = Path(".env")) -> None:
    if created_env:
        console.print(f"Initialized env settings file: {env_path}")
    if generated_keys:
        names = ", ".join(generated_keys)
        console.print(f"Generated random API auth keys in settings ({names}).")
        console.print(f"Keys are stored in: {env_path}")


def _service_mode(value: str) -> str:
    mode = value.strip().lower()
    if mode not in {"system", "user"}:
        raise typer.BadParameter("mode must be either 'system' or 'user'")
    return mode


def _ensure_systemd_available() -> None:
    if not sys.platform.startswith("linux"):
        raise typer.BadParameter("service commands are supported on Linux only")
    if shutil.which("systemctl") is None:
        raise typer.BadParameter("systemctl not found; systemd is required for service commands")


def _systemctl_base(mode: str) -> list[str]:
    return ["systemctl", "--user"] if mode == "user" else ["systemctl"]


def _service_unit_path(mode: str) -> Path:
    if mode == "user":
        return Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME}.service"
    return Path("/etc/systemd/system") / f"{SERVICE_NAME}.service"


def _run_command(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(command, capture_output=True, text=True)
    if check and proc.returncode != 0:
        error_text = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        raise typer.BadParameter(f"command failed: {' '.join(command)}\n{error_text}")
    return proc


def _run_streaming_command(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(command, text=True)
    if check and proc.returncode != 0:
        raise typer.BadParameter(f"command failed: {' '.join(command)}")
    return proc


def _read_installed_version(install_root: Path) -> str:
    version_path = install_root / "VERSION"
    if version_path.exists():
        return version_path.read_text(encoding="utf-8", errors="replace").strip() or "<empty>"
    return "<source/no VERSION file>"


def _current_cli_file() -> Path:
    return Path(__file__).resolve()


def _print_install_diagnostics(config_path: str) -> None:
    config_install_root = _guess_install_root(config_path)
    wrapper_install_root = _detect_wrapper_install_root()
    install_root = wrapper_install_root or config_install_root
    sor_path = shutil.which("sor") or "<not found in PATH>"
    table = Table(title="SimpleOpenRoad Install Diagnostics", box=box.ASCII)
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Config path", str(Path(config_path).resolve()))
    table.add_row("Config install dir", str(config_install_root))
    table.add_row("Wrapper install dir", str(wrapper_install_root) if wrapper_install_root else "<not detected>")
    table.add_row("Effective install dir", str(install_root))
    table.add_row("Installed VERSION", _read_installed_version(install_root))
    table.add_row("CLI module file", str(_current_cli_file()))
    table.add_row("sor in PATH", sor_path)
    table.add_row("Python executable", sys.executable)
    console.print(table)

    cli_text = _current_cli_file().read_text(encoding="utf-8", errors="replace")
    has_alias_guide = "Model Alias Guide" in cli_text
    has_v1_setup = "openai_base = f\"{api_base}/v1\"" in cli_text
    console.print(f"Setup summary code has /v1 Base URL: {'yes' if has_v1_setup else 'no'}")
    console.print(f"Setup summary code has alias guide: {'yes' if has_alias_guide else 'no'}")


def _run_systemctl(mode: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [*_systemctl_base(mode), *args]
    return _run_command(command, check=check)


def _default_bin_dir() -> Path:
    if sys.platform.startswith("linux"):
        geteuid = getattr(os, "geteuid", None)
        if callable(geteuid) and geteuid() == 0 and Path("/usr/local/bin").is_dir():
            return Path("/usr/local/bin")
    return Path.home() / ".local" / "bin"


def _default_install_root() -> Path:
    if sys.platform.startswith("linux"):
        geteuid = getattr(os, "geteuid", None)
        if callable(geteuid) and geteuid() == 0:
            return Path("/usr/local/share/simple-open-road")
    return Path.home() / ".local" / "share" / "simple-open-road"


def _resolve_bin_dir(install_root: Path, explicit_bin_dir: str | None = None) -> Path:
    if explicit_bin_dir:
        return Path(explicit_bin_dir).expanduser().resolve()
    binaries = _candidate_sor_binaries(install_root)
    if binaries:
        return binaries[0].parent
    return _default_bin_dir()


def _extract_release_tag(payload: Any) -> str | None:
    if isinstance(payload, dict):
        tag = payload.get("tag_name")
        return tag.strip() if isinstance(tag, str) and tag.strip() else None
    if isinstance(payload, list):
        for item in payload:
            tag = _extract_release_tag(item)
            if tag:
                return tag
    return None


def _normalize_release_channel(channel: str) -> str:
    normalized = channel.strip().lower()
    if normalized not in {"stable", "prerelease"}:
        raise typer.BadParameter("channel must be either 'stable' or 'prerelease'")
    return normalized


def _resolve_latest_release_tag(repo: str, channel: str = "stable") -> str:
    normalized_repo = repo.strip().strip("/")
    if normalized_repo.count("/") != 1:
        raise typer.BadParameter("repo must use owner/repo format")
    selected_channel = _normalize_release_channel(channel)

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "SimpleOpenRoad CLI",
    }
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    urls = [f"https://api.github.com/repos/{normalized_repo}/releases?per_page=20"]
    if selected_channel == "stable":
        urls.insert(0, f"https://api.github.com/repos/{normalized_repo}/releases/latest")
    last_error = ""
    for url in urls:
        try:
            response = httpx.get(url, headers=headers, timeout=15.0)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_error = str(exc)
            continue
        if isinstance(payload, list):
            if selected_channel == "prerelease":
                tag = next(
                    (
                        str(item.get("tag_name")).strip()
                        for item in payload
                        if isinstance(item, dict) and item.get("prerelease") and item.get("tag_name")
                    ),
                    "",
                )
            else:
                tag = next(
                    (
                        str(item.get("tag_name")).strip()
                        for item in payload
                        if isinstance(item, dict) and not item.get("prerelease") and item.get("tag_name")
                    ),
                    "",
                )
        else:
            tag = _extract_release_tag(payload)
        if tag:
            return tag

    hint = f": {last_error}" if last_error else ""
    raise typer.BadParameter(
        f"Unable to resolve latest {selected_channel} release tag for {normalized_repo}{hint}. "
        "Pass --version <tag> explicitly."
    )


def _resolve_update_version(repo: str, requested_version: str | None, channel: str = "stable") -> str:
    if requested_version:
        return requested_version
    return _resolve_latest_release_tag(repo, channel=channel)


def _build_update_command(
    install_root: Path,
    bin_dir: Path,
    repo: str,
    version: str | None,
    ref: str | None,
    channel: str,
    arch: str | None,
    python_bin: str | None,
) -> list[str]:
    installer_path = install_root / "install.sh"
    if not installer_path.exists():
        raise typer.BadParameter(f"Installer script not found: {installer_path}")

    command = [
        "bash",
        str(installer_path),
        "--repo",
        repo,
        "--install-dir",
        str(install_root),
        "--bin-dir",
        str(bin_dir),
    ]
    if version:
        command.extend(["--version", version])
    if ref:
        command.extend(["--ref", ref])
    if channel != "stable":
        command.extend(["--channel", channel])
    if arch:
        command.extend(["--arch", arch])
    if python_bin:
        command.extend(["--python", python_bin])
    return command


def _service_exec_start(config_path: str) -> str:
    argv_executable = Path(sys.argv[0]).expanduser()
    sor_executable: Path | None = None
    if argv_executable.exists():
        sor_executable = argv_executable.resolve()
    else:
        discovered = shutil.which("sor")
        if discovered is not None:
            sor_executable = Path(discovered).resolve()

    if sor_executable is None:
        raise typer.BadParameter("sor executable was not found (argv[0] or PATH)")

    quoted_exec = shlex.quote(str(sor_executable))
    quoted_cfg = shlex.quote(str(Path(config_path).resolve()))
    return f"{quoted_exec} start --config-path {quoted_cfg}"


def _render_service_unit(mode: str, config_path: str, run_as_user: str | None = None) -> str:
    cfg_path = str(Path(config_path).resolve())
    working_dir = str(Path.cwd().resolve())
    exec_start = _service_exec_start(cfg_path)
    wanted_target = "default.target" if mode == "user" else "multi-user.target"
    user_line = f"User={run_as_user}\n" if mode == "system" and run_as_user else ""

    return textwrap.dedent(
        f"""
        [Unit]
        Description=SimpleOpenRoad AI Gateway
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        {user_line}WorkingDirectory={working_dir}
        Environment=APP_CONFIG_PATH={cfg_path}
        ExecStart={exec_start}
        Restart=always
        RestartSec=3
        LimitNOFILE=65535

        [Install]
        WantedBy={wanted_target}
        """
    ).strip() + "\n"


def _check_system_mode_permissions(mode: str) -> None:
    if mode != "system":
        return
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid) and geteuid() != 0:
        raise typer.BadParameter("system mode requires root privileges; run with sudo or use --mode user")


def _service_status_text(mode: str) -> str:
    proc = _run_systemctl(mode, "is-active", SERVICE_NAME, check=False)
    state = proc.stdout.strip() or "unknown"
    enabled_proc = _run_systemctl(mode, "is-enabled", SERVICE_NAME, check=False)
    enabled = enabled_proc.stdout.strip() or "unknown"
    return f"status={state}, enabled={enabled}"


def _restart_service_after_update(mode: str = "system") -> bool:
    if shutil.which("systemctl") is None:
        console.print("Service restart skipped: systemctl not found.")
        return False
    try:
        selected_mode = _service_mode(mode)
        _run_systemctl(selected_mode, "restart", SERVICE_NAME, check=False)
    except Exception as exc:  # noqa: BLE001
        console.print(f"Service restart skipped: {exc}")
        return False
    console.print("Service restarted.")
    return True


def _guess_install_root(config_path: str) -> Path:
    cfg_path = Path(config_path).resolve()
    if not cfg_path.exists():
        return _default_install_root()
    if cfg_path.parent.name == "config":
        return cfg_path.parent.parent
    return cfg_path.parent


def _install_root_from_wrapper(wrapper_path: Path) -> Path | None:
    if not wrapper_path.exists() or not wrapper_path.is_file():
        return None
    try:
        lines = wrapper_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("exec ") and "/.venv/bin/sor" in stripped:
            value = stripped.split("/.venv/bin/sor", 1)[0].removeprefix("exec ").strip().strip('"')
            path = Path(value)
            if path.exists():
                return path.resolve()
        if stripped.startswith("cd "):
            value = stripped.removeprefix("cd ").strip().strip('"')
            path = Path(value)
            if path.exists():
                return path.resolve()
    return None


def _detect_wrapper_install_root() -> Path | None:
    candidates: list[Path] = []
    discovered = shutil.which("sor")
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend([Path("/usr/local/bin/sor"), Path.home() / ".local" / "bin" / "sor"])
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        install_root = _install_root_from_wrapper(resolved)
        if install_root is not None:
            return install_root
    return None


def _stop_fallback_background_process(config_path: str) -> bool:
    pid_file = _guess_install_root(config_path) / "run" / "sor.pid"
    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
    except (ValueError, OSError):
        # Process may already be gone or pid file invalid; continue cleanup.
        pass

    pid_file.unlink(missing_ok=True)
    return True


def _remove_runtime_db(sqlite_path: str) -> list[Path]:
    db_path = Path(sqlite_path)
    removed: list[Path] = []
    for candidate in (db_path, Path(f"{db_path}-shm"), Path(f"{db_path}-wal")):
        if candidate.exists():
            candidate.unlink()
            removed.append(candidate)
    return removed


def _is_dangerous_remove_target(path: Path) -> bool:
    resolved = path.resolve()
    home = Path.home().resolve()
    anchors = {Path(anchor).resolve() for anchor in (Path.cwd().anchor, home.anchor) if anchor}
    return resolved in anchors or resolved == home or str(resolved) in {"", ".", "/"}


def _candidate_sor_binaries(install_root: Path) -> list[Path]:
    candidates: list[Path] = []
    discovered = shutil.which("sor")
    if discovered:
        candidates.append(Path(discovered))
    argv_path = Path(sys.argv[0])
    if argv_path.exists():
        candidates.append(argv_path)
    candidates.extend([Path("/usr/local/bin/sor"), Path.home() / ".local" / "bin" / "sor"])

    result: list[Path] = []
    seen: set[str] = set()
    install_text = str(install_root.resolve())
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen or not resolved.exists() or not resolved.is_file():
            continue
        seen.add(key)
        try:
            text = resolved.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        if install_text in text or install_root.resolve() in resolved.parents:
            result.append(resolved)
    return result


def _remove_install_tree(install_root: Path, yes: bool) -> list[Path]:
    resolved = install_root.resolve()
    if not resolved.exists():
        return []
    if _is_dangerous_remove_target(resolved):
        raise typer.BadParameter(f"Refusing to remove unsafe install directory: {resolved}")
    if (resolved / ".git").exists():
        raise typer.BadParameter(f"Refusing to remove git checkout: {resolved}")
    if not yes:
        confirmed = typer.confirm(f"Remove install directory and all package files: {resolved}", default=False)
        if not confirmed:
            raise typer.Exit(1)

    shutil.rmtree(resolved)
    return [resolved]


def _remove_unconfigured_provider_keys(config_path: str) -> int:
    path = _config_path(config_path)
    data = _load_yaml(path)
    providers = data.get("providers", {})
    if not isinstance(providers, dict):
        return 0

    removed = 0
    for provider_cfg in providers.values():
        if not isinstance(provider_cfg, dict):
            continue
        keys = provider_cfg.get("keys", [])
        if not isinstance(keys, list):
            continue
        configured_keys = [
            item
            for item in keys
            if isinstance(item, dict) and is_configured_secret(str(item.get("key", "")))
        ]
        removed += len(keys) - len(configured_keys)
        provider_cfg["keys"] = configured_keys

    if removed:
        _save_yaml(path, data)
    return removed


def _interactive_add_provider_key(config_path: str) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    providers = data.get("providers", {})
    if not isinstance(providers, dict) or not providers:
        raise typer.BadParameter("No providers configured. Add providers in config first.")

    provider = _select_provider_from_names([str(name) for name in providers.keys()])
    provider_cfg = providers.get(provider)
    if not isinstance(provider_cfg, dict):
        raise typer.BadParameter(f"Provider not found in config: {provider}")
    if provider_cfg.get("auth_required") is False:
        _interactive_configure_local_provider(
            config_path=config_path,
            data=data,
            providers=providers,
            provider=provider,
        )
        return
    if provider == "cloudflare":
        existing_account_id = str(providers.get(provider, {}).get("account_id", "") or "").strip()
        account_id = typer.prompt(
            "Cloudflare Account ID",
            default=existing_account_id,
        ).strip()
        if not account_id:
            raise typer.BadParameter("Cloudflare Account ID cannot be empty")
        providers[provider]["account_id"] = account_id
        _save_yaml(path, data)

    existing_keys = providers.get(provider, {}).get("keys", [])
    default_key_id = f"{provider}-key-{len(existing_keys) + 1}"
    console.print("Key ID is a local name for this provider key. It is used in logs, stats, health checks and removal commands.")
    console.print("It is not sent to the provider. Example: openrouter-main or gemini-backup-1.")
    while True:
        key_id = typer.prompt("Key ID", default=default_key_id).strip()
        if not key_id:
            raise typer.BadParameter("Key ID cannot be empty")
        existing_key_ids = _configured_key_ids_by_provider(providers)
        existing_provider = existing_key_ids.get(key_id)
        if existing_provider is None:
            break
        console.print(
            f"Key ID '{key_id}' already exists in provider '{existing_provider}'. "
            "Enter another unique local key ID."
        )
        default_key_id = f"{provider}-key-{len(existing_keys) + 2}"

    secret = typer.prompt("API key", hide_input=True, confirmation_prompt=True).strip()
    if not secret:
        raise typer.BadParameter("API key cannot be empty")

    priority_raw = typer.prompt("Priority", default="100").strip()
    if not priority_raw.isdigit():
        raise typer.BadParameter("Priority must be an integer")
    priority = int(priority_raw)

    validate_now = typer.confirm("Validate key now", default=True)
    keys_add(
        provider=provider,
        key_id=key_id,
        secret=secret,
        account_id=account_id if provider == "cloudflare" else None,
        priority=priority,
        config_path=config_path,
        validate=validate_now,
    )


def _prompt_unique_key_id(
    providers: dict[str, Any],
    provider: str,
    default_key_id: str,
    prompt_label: str = "Key ID",
) -> str:
    while True:
        key_id = typer.prompt(prompt_label, default=default_key_id).strip()
        if not key_id:
            raise typer.BadParameter(f"{prompt_label} cannot be empty")
        existing_key_ids = _configured_key_ids_by_provider(providers)
        existing_provider = existing_key_ids.get(key_id)
        if existing_provider is None or existing_provider == provider:
            return key_id
        console.print(
            f"Key ID '{key_id}' already exists in provider '{existing_provider}'. "
            "Enter another unique local key ID."
        )


def _interactive_configure_local_provider(
    config_path: str,
    data: dict[str, Any],
    providers: dict[str, Any],
    provider: str,
) -> None:
    path = _config_path(config_path)
    provider_cfg = providers.get(provider)
    if not isinstance(provider_cfg, dict):
        raise typer.BadParameter(f"Provider not found in config: {provider}")

    console.print(
        "Local/self-hosted preset selected. Configure the full upstream Base URL, "
        "for example http://127.0.0.1:11434/v1 or https://llm.example.com/v1."
    )
    endpoint_default = str(provider_cfg.get("endpoint", "") or "").strip()
    endpoint = typer.prompt("Base URL", default=endpoint_default).strip()
    if not endpoint:
        raise typer.BadParameter("Base URL cannot be empty")

    auth_required = typer.confirm(
        "Does this endpoint require an upstream API key or token",
        default=False,
    )
    existing_keys = [item for item in provider_cfg.get("keys", []) if isinstance(item, dict)]
    placeholder_key = next((item for item in existing_keys if str(item.get("key", "")).strip().lower() == "local"), None)
    base_key = placeholder_key or (existing_keys[0] if existing_keys else {"id": f"{provider}-local"})
    default_key_id = str(base_key.get("id", f"{provider}-local"))

    console.print(
        "Connection ID is a local name for this upstream endpoint. "
        "It is used in logs, stats, health checks and removal commands."
    )
    key_id = _prompt_unique_key_id(providers, provider, default_key_id, prompt_label="Connection ID")

    if auth_required:
        secret = typer.prompt("Upstream API key", hide_input=True, confirmation_prompt=True).strip()
        if not secret:
            raise typer.BadParameter("Upstream API key cannot be empty")
    else:
        secret = "local"

    priority_default = str(base_key.get("priority", 100))
    priority_raw = typer.prompt("Priority", default=priority_default).strip()
    if not priority_raw.isdigit():
        raise typer.BadParameter("Priority must be an integer")
    priority = int(priority_raw)

    key_data = {
        "id": key_id,
        "key": secret,
        "account_id": None,
        "active": True,
        "priority": priority,
        "weight": int(base_key.get("weight", 1) or 1),
        "tags": list(base_key.get("tags", [])),
        "limits": dict(base_key.get("limits", {"rpm": None})),
        "cooldown": dict(
            base_key.get(
                "cooldown",
                {"rate_limit_seconds": 30, "error_seconds": 15},
            )
        ),
        "max_retries": int(base_key.get("max_retries", 1) or 1),
        "max_consecutive_errors": int(base_key.get("max_consecutive_errors", 5) or 5),
    }

    replaced = False
    new_keys: list[dict[str, Any]] = []
    for item in existing_keys:
        if str(item.get("id", "")).strip() == key_id or item is placeholder_key:
            if not replaced:
                new_keys.append(key_data)
                replaced = True
            continue
        new_keys.append(item)
    if not replaced:
        new_keys.append(key_data)

    provider_cfg["enabled"] = True
    provider_cfg["endpoint"] = endpoint
    provider_cfg["auth_required"] = auth_required
    provider_cfg["keys"] = new_keys
    _save_yaml(path, data)
    console.print(
        f"Configured endpoint for provider {provider}: {endpoint} "
        f"(upstream auth: {'enabled' if auth_required else 'disabled'})"
    )

    validate_now = typer.confirm("Validate endpoint now", default=True)
    if validate_now:
        keys_validate(provider=provider, key_id=key_id, config_path=config_path)


def _configured_key_ids_by_provider(providers: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for provider_name, provider_cfg in providers.items():
        if not isinstance(provider_cfg, dict):
            continue
        keys = provider_cfg.get("keys", [])
        if not isinstance(keys, list):
            continue
        for item in keys:
            if not isinstance(item, dict):
                continue
            key_id = str(item.get("id", "")).strip()
            if key_id:
                result[key_id] = str(provider_name)
    return result


@cli_app.command("init")
def init(config_path: str = typer.Option("config/config.yaml", help="Path to target config.yaml")) -> None:
    target = Path(config_path)
    example = Path("config/config.example.yaml")
    created_env, generated_keys = _ensure_env_master_admin_keys()
    _print_env_setup_hint(created_env=created_env, generated_keys=generated_keys)
    if target.exists():
        console.print(f"Config already exists: {target}")
        cfg_existing = load_gateway_config(config_path=str(target))
        _print_setup_summary(config_path=str(target), cfg=cfg_existing)
        raise typer.Exit(0)
    if not example.exists():
        raise typer.BadParameter("Missing config/config.example.yaml")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(example, target)
    console.print(f"Initialized config: {target}")
    cfg = load_gateway_config(config_path=str(target))
    _print_setup_summary(config_path=str(target), cfg=cfg)


@cli_app.command("start")
def start(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    created_env, generated_keys = _ensure_env_master_admin_keys()
    _print_env_setup_hint(created_env=created_env, generated_keys=generated_keys)
    cfg = load_gateway_config(config_path=config_path)
    os.environ["APP_CONFIG_PATH"] = config_path
    uvicorn.run(
        "app.main:app",
        host=cfg.server.host,
        port=cfg.server.port,
        reload=False,
        log_level="info",
    )


@cli_app.command("doctor")
def doctor(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    try:
        container = _container(config_path)
        providers = container.admin_service.list_providers()
        keys = container.admin_service.list_keys()
        cfg = container.runtime_config.get()
        console.print("Doctor report: OK")
        console.print(f"Providers: {len(providers)}")
        console.print(f"Keys: {len(keys)}")
        console.print(f"SQLite: {cfg.storage.sqlite_path}")
        _print_setup_summary(config_path=config_path, cfg=cfg)
    except Exception as exc:  # noqa: BLE001
        console.print(f"Doctor report: FAILED - {exc}")
        raise typer.Exit(1) from exc


@providers_app.command("list")
def providers_list(
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
    all_providers: bool = typer.Option(False, "--all", help="Show the full provider catalog, including providers without configured keys"),
) -> None:
    show_all = all_providers if isinstance(all_providers, bool) else False
    container = _container(config_path)
    cfg = container.runtime_config.get()
    rows = sorted(
        container.admin_service.list_providers(),
        key=lambda row: (
            0 if str(row["name"]) in FEATURED_PROVIDER_SET else 1,
            FEATURED_PROVIDER_ORDER.index(str(row["name"])) if str(row["name"]) in FEATURED_PROVIDER_SET else 999,
            str(row["name"]),
        ),
    )
    for row in rows:
        provider_name = str(row["name"])
        provider_cfg = cfg.providers.get(provider_name)
        row["keys_count"] = _count_user_configured_keys(provider_cfg) if provider_cfg is not None else 0
    if not show_all:
        rows = [row for row in rows if int(row.get("keys_count", 0) or 0) > 0]
    table = Table(title="Providers" if show_all else "Providers With Configured Keys")
    table.add_column("Category")
    table.add_column("Name")
    table.add_column("Enabled")
    table.add_column("Priority")
    table.add_column("Endpoint")
    table.add_column("Keys")
    if not rows:
        table.add_row("-", "<empty>", "-", "-", "-", "0")
    for row in rows:
        table.add_row(
            _provider_category(str(row["name"])),
            str(row["name"]),
            str(row["enabled"]),
            str(row["priority"]),
            str(row["endpoint"]),
            str(row["keys_count"]),
        )
    console.print(table)


@providers_app.command("inventory")
def providers_inventory(
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
    refresh: bool = typer.Option(True, "--refresh/--cached", help="Refresh provider inventory before printing"),
) -> None:
    import asyncio

    container = _container(config_path)
    snapshot = (
        asyncio.run(container.admin_service.refresh_inventory())
        if refresh
        else container.admin_service.current_inventory()
    )
    if snapshot is None:
        console.print("Inventory snapshot is empty. Run with --refresh.")
        return

    summary = Table(title="Provider Inventory / Keys", box=box.ASCII)
    summary.add_column("Provider")
    summary.add_column("Key ID")
    summary.add_column("Status")
    summary.add_column("Models")
    summary.add_column("Error")
    key_results = snapshot.get("key_results", [])
    if not key_results:
        summary.add_row("-", "-", "<empty>", "0", "-")
    else:
        for item in key_results:
            summary.add_row(
                str(item.get("provider", "")),
                str(item.get("key_id", "")),
                str(item.get("status", "")),
                str(item.get("discovered_models", "")),
                _result_error_text(item),
            )
    console.print(summary)

    classifications = {
        (str(item.get("provider", "")), str(item.get("model_id", ""))): item
        for item in snapshot.get("classifications", [])
    }
    models_table = Table(title="Provider Inventory / Models", box=box.ASCII)
    models_table.add_column("Provider")
    models_table.add_column("Model")
    models_table.add_column("Modality")
    models_table.add_column("Keys")
    models_table.add_column("Free")
    models_table.add_column("Preview")
    models_table.add_column("Special")
    models_table.add_column("Text")
    models_table.add_column("Chat")
    models_table.add_column("Responses")
    models_table.add_column("Stream")
    models_table.add_column("Tools")
    models_table.add_column("Excluded")
    models_table.add_column("Tags")
    models_table.add_column("Scores")
    models = snapshot.get("models", [])
    if not models:
        models_table.add_row("-", "<empty>", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-")
    else:
        for item in models:
            classification = classifications.get((str(item.get("provider", "")), str(item.get("model_id", ""))), {})
            scores = "/".join(
                [
                    f"f{classification.get('free_score', 0)}",
                    f"fa{classification.get('fast_score', 0)}",
                    f"g{classification.get('general_score', 0)}",
                    f"r{classification.get('reasoning_score', 0)}",
                    f"c{classification.get('code_score', 0)}",
                ]
            )
            models_table.add_row(
                str(item.get("provider", "")),
                str(item.get("model_id", "")),
                str(item.get("modality", "")),
                ", ".join(str(value) for value in item.get("source_key_ids", [])) or "-",
                "yes" if item.get("is_free") else "no",
                "yes" if item.get("is_preview") else "no",
                "yes" if item.get("is_special") else "no",
                "yes" if item.get("is_text_candidate") else "no",
                str(item.get("chat_state", "-")),
                str(item.get("responses_state", "-")),
                str(item.get("stream_state", "-")),
                str(item.get("tools_state", "-")),
                str(item.get("excluded_reason", "") or "-"),
                ", ".join(str(value) for value in classification.get("classification_tags", [])) or "-",
                scores,
            )
    console.print(models_table)

    special_routes = snapshot.get("special_routes", [])
    special_routes_table = Table(title="Provider Inventory / Special Routes", box=box.ASCII)
    special_routes_table.add_column("Provider")
    special_routes_table.add_column("Route")
    special_routes_table.add_column("Modality")
    special_routes_table.add_column("Tools")
    special_routes_table.add_column("Hints")
    if not special_routes:
        special_routes_table.add_row("-", "<empty>", "-", "-", "-")
    else:
        for item in special_routes:
            special_routes_table.add_row(
                str(item.get("provider", "")),
                str(item.get("route_id", "")),
                str(item.get("modality", "")),
                "yes" if item.get("supports_tools") else "no",
                ", ".join(str(value) for value in item.get("category_hints", [])) or "-",
            )
    console.print(special_routes_table)

    generated_aliases = snapshot.get("generated_aliases", [])
    aliases_table = Table(title="Provider Inventory / Generated Aliases", box=box.ASCII)
    aliases_table.add_column("Alias")
    aliases_table.add_column("Modality")
    aliases_table.add_column("Scope")
    aliases_table.add_column("Category")
    aliases_table.add_column("Candidates")
    aliases_table.add_column("Preview")
    if not generated_aliases:
        aliases_table.add_row("-", "-", "-", "-", "0", "<empty>")
    else:
        for item in generated_aliases:
            candidates = item.get("candidates", [])
            preview = ", ".join(
                f"{candidate.get('provider')}/{candidate.get('model_id')}" for candidate in candidates[:3]
            ) or "-"
            aliases_table.add_row(
                str(item.get("alias_id", "")),
                str(item.get("modality", "")),
                str(item.get("scope", "")),
                str(item.get("category", "")),
                str(len(candidates)),
                preview,
            )
    console.print(aliases_table)


@providers_app.command("connect")
def providers_connect(
    provider: str = typer.Argument(..., help="Provider to connect. Currently supported: google"),
    profile: str = typer.Option("main", help="Local credential profile name"),
    key_id: str = typer.Option("google-ai-pro-main", help="Key id to write into config"),
    gemini_cli_credentials_path: str | None = typer.Option(
        None,
        help="Path to Gemini CLI oauth_creds.json or gemini-credentials.json. Defaults to the official Gemini CLI location.",
    ),
    force_gemini_login: bool = typer.Option(False, help="Run Gemini CLI sign-in even if profile credentials already exist"),
    google_cloud_project: str | None = typer.Option(None, help="Optional Google Cloud project id"),
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
    validate: bool = typer.Option(True, help="Validate provider after connecting"),
) -> None:
    if provider.strip().lower() not in {"google", "google_code_assist", "code_assist"}:
        raise typer.BadParameter("Only google is supported by providers connect right now")

    from app.credentials.google_code_assist import import_gemini_cli_credentials

    cfg = load_gateway_config(config_path=config_path)
    credentials_base = Path(cfg.storage.sqlite_path).parent / "credentials"
    auth_home = _gemini_cli_profile_home(credentials_base, profile) if gemini_cli_credentials_path is None else None
    if gemini_cli_credentials_path is not None:
        source_path = gemini_cli_credentials_path
    elif auth_home is not None:
        source_path = str(_gemini_cli_profile_source_path(auth_home))
    else:
        source_path = None
    console.print("\nImporting credentials from the official Gemini CLI.")
    _run_gemini_cli_auth_if_needed(source_path, auth_home=auth_home, force=force_gemini_login)
    path, credentials = import_gemini_cli_credentials(
        profile=profile,
        source_path=source_path,
        project_id=google_cloud_project,
        base_dir=credentials_base,
    )

    _configure_google_code_assist_provider(
        config_path=config_path,
        path=path,
        credentials=credentials,
        key_id=key_id,
        validate=validate,
    )


def _configure_google_code_assist_provider(
    *,
    config_path: str,
    path: Path,
    credentials: dict[str, Any],
    key_id: str,
    validate: bool,
) -> None:
    config_file = _config_path(config_path)
    data = _load_yaml(config_file)
    providers = data.setdefault("providers", {})
    provider_cfg = providers.setdefault(
        "google_code_assist",
        {
            "enabled": True,
            "priority": 15,
            "endpoint": "https://cloudcode-pa.googleapis.com",
            "timeout_seconds": 120,
            "keys": [],
        },
    )
    provider_cfg["enabled"] = True
    provider_cfg.setdefault("priority", 15)
    provider_cfg.setdefault("endpoint", "https://cloudcode-pa.googleapis.com")
    provider_cfg.setdefault("timeout_seconds", 120)
    keys = provider_cfg.setdefault("keys", [])
    key_value = f"oauth-file:{path.resolve()}"
    key_data = {
        "id": key_id,
        "key": key_value,
        "account_id": credentials.get("account_email"),
        "active": True,
        "priority": 100,
        "weight": 1,
        "tags": ["oauth", "experimental"],
        "limits": {"rpm": None},
        "cooldown": {"rate_limit_seconds": 30, "error_seconds": 15},
        "max_retries": 1,
        "max_consecutive_errors": 5,
    }
    replaced = False
    for index, item in enumerate(keys):
        if isinstance(item, dict) and str(item.get("id")) == key_id:
            keys[index] = key_data
            replaced = True
            break
    if not replaced:
        existing_key_ids = _configured_key_ids_by_provider(providers)
        existing_provider = existing_key_ids.get(key_id)
        if existing_provider is not None and existing_provider != "google_code_assist":
            raise typer.BadParameter(
                f"Key id must be globally unique. '{key_id}' already exists in provider '{existing_provider}'."
            )
        keys.append(key_data)

    _save_yaml(config_file, data)
    console.print(f"Connected Gemini CLI OAuth account: {credentials.get('account_email') or '<unknown>'}")
    console.print(f"Credentials saved: {path}")
    console.print(f"Provider key configured: google_code_assist/{key_id}")

    if validate:
        keys_validate(provider="google_code_assist", key_id=key_id, config_path=str(config_file))


def _gemini_cli_profile_home(credentials_base: Path, profile: str) -> Path:
    safe_profile = "".join(ch for ch in profile if ch.isalnum() or ch in {"-", "_"}).strip() or "main"
    return credentials_base / "google_code_assist" / "gemini-cli-homes" / safe_profile


def _gemini_cli_profile_source_path(auth_home: Path | None) -> Path | None:
    if auth_home is None:
        return None
    from app.credentials.google_code_assist import gemini_cli_credentials_path, gemini_cli_keychain_path

    legacy = gemini_cli_credentials_path(auth_home)
    if legacy.exists():
        return legacy
    return gemini_cli_keychain_path(auth_home)


def _gemini_cli_credentials_exist(source_path: str | Path | None = None, auth_home: Path | None = None) -> bool:
    from app.credentials.google_code_assist import gemini_cli_credentials_path, gemini_cli_keychain_path

    if source_path:
        return Path(source_path).expanduser().exists()
    if auth_home is not None:
        return gemini_cli_credentials_path(auth_home).exists() or gemini_cli_keychain_path(auth_home).exists()
    return gemini_cli_credentials_path().exists() or gemini_cli_keychain_path().exists()


def _gemini_cli_auth_command() -> list[str]:
    node = _find_compatible_node()
    gemini_bin = shutil.which("gemini")
    if gemini_bin:
        return [gemini_bin]
    npx_command = _npx_command_for_node(node)
    if npx_command:
        return [*npx_command, "-y", "@google/gemini-cli"]
    raise typer.BadParameter(
        "Gemini CLI/npm was not found for a compatible Node.js installation. "
        "Install Node.js 20+ with npm, then run this wizard again."
    )


def _find_compatible_node() -> Path:
    candidates = _node_binary_candidates()
    versions: list[str] = []
    for candidate in candidates:
        version_text = _node_version(candidate)
        if version_text:
            versions.append(f"{candidate}={version_text}")
        major = _parse_node_major_version(version_text or "")
        if major is not None and major >= MIN_GEMINI_CLI_NODE_MAJOR:
            return candidate

    installed = ", ".join(versions) if versions else "<none found>"
    raise typer.BadParameter(
        "Gemini CLI requires Node.js 20 or newer. "
        f"Found Node.js versions: {installed}. "
        "Install or activate Node.js 20+ on the VPS, then run this wizard again. "
        "For Ubuntu, one common path is NodeSource Node.js 22: "
        "curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && "
        "sudo apt-get install -y nodejs"
    )


def _node_binary_candidates() -> list[Path]:
    candidates: list[Path] = []
    for name in ("node", "nodejs"):
        discovered = shutil.which(name)
        if discovered:
            candidates.append(Path(discovered))

    home = Path.home()
    candidates.extend(home.glob(".nvm/versions/node/v*/bin/node"))
    candidates.extend(Path("/usr/local/bin").glob("node*"))
    candidates.extend(Path("/opt").glob("node*/bin/node"))

    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _node_version(node_bin: Path) -> str | None:
    try:
        proc = subprocess.run([str(node_bin), "--version"], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return (proc.stdout or proc.stderr).strip() or None


def _npx_command_for_node(node_bin: Path) -> list[str] | None:
    node_dir = node_bin.parent
    local_npx = node_dir / ("npx.cmd" if os.name == "nt" else "npx")
    if local_npx.exists():
        return [str(local_npx)]

    local_npm_cli = node_dir / "node_modules" / "npm" / "bin" / "npx-cli.js"
    if local_npm_cli.exists():
        return [str(node_bin), str(local_npm_cli)]

    for npm_bin_name in ("npm", "npm.cmd"):
        npm_bin = node_dir / npm_bin_name
        if npm_bin.exists():
            npm_prefix = _npm_prefix(npm_bin)
            if npm_prefix:
                npm_cli = npm_prefix / "lib" / "node_modules" / "npm" / "bin" / "npx-cli.js"
                if npm_cli.exists():
                    return [str(node_bin), str(npm_cli)]

    npx_bin = shutil.which("npx")
    if npx_bin:
        return [npx_bin]
    return None


def _npm_prefix(npm_bin: Path) -> Path | None:
    try:
        proc = subprocess.run([str(npm_bin), "prefix", "-g"], capture_output=True, text=True, check=False)
    except OSError:
        return None
    value = proc.stdout.strip()
    return Path(value) if proc.returncode == 0 and value else None


def _parse_node_major_version(version_text: str) -> int | None:
    normalized = version_text.strip().lstrip("v")
    major_text = normalized.split(".", 1)[0]
    if not major_text.isdigit():
        return None
    return int(major_text)


def _run_gemini_cli_auth_if_needed(
    source_path: str | Path | None = None,
    auth_home: Path | None = None,
    force: bool = False,
) -> None:
    if not force and _gemini_cli_credentials_exist(source_path, auth_home=auth_home):
        console.print("Gemini CLI credentials found. Continuing with import.")
        return
    if force:
        _clear_gemini_cli_auth_credentials(source_path, auth_home=auth_home)

    console.print("Gemini CLI credentials were not found. Starting official Gemini CLI sign-in now.")
    console.print("Open the URL/code shown by Gemini CLI in your browser and finish Google sign-in.")
    console.print("SimpleOpenRoad will continue automatically after Gemini CLI exits.\n")

    env = os.environ.copy()
    env["GEMINI_FORCE_FILE_STORAGE"] = "true"
    env["NO_BROWSER"] = "true"
    compatible_node = _find_compatible_node()
    env["PATH"] = f"{compatible_node.parent}{os.pathsep}{env.get('PATH', '')}"
    if auth_home is not None:
        auth_home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(auth_home)
        env["USERPROFILE"] = str(auth_home)
    proc = subprocess.run(_gemini_cli_auth_command(), env=env)
    if proc.returncode != 0:
        raise typer.BadParameter("Gemini CLI sign-in did not complete successfully")
    if not _gemini_cli_credentials_exist(source_path, auth_home=auth_home):
        raise typer.BadParameter(
            "Gemini CLI finished, but credentials were still not found. "
            "Run `GEMINI_FORCE_FILE_STORAGE=true gemini` manually and try again."
        )
    console.print("\nGemini CLI credentials created. Continuing with SimpleOpenRoad import.")


def _clear_gemini_cli_auth_credentials(source_path: str | Path | None, auth_home: Path | None = None) -> None:
    from app.credentials.google_code_assist import gemini_cli_credentials_path, gemini_cli_keychain_path

    paths: list[Path] = []
    if source_path:
        paths.append(Path(source_path).expanduser())
    if auth_home is not None:
        paths.extend([gemini_cli_credentials_path(auth_home), gemini_cli_keychain_path(auth_home)])
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            raise typer.BadParameter(f"Could not clear existing Gemini CLI credentials at {path}: {exc}") from exc


@providers_app.command("test")
def providers_test(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    import asyncio

    container = _container(config_path)
    results = asyncio.run(container.admin_service.validate_all_keys())
    table = Table(title="Provider Key Checks")
    table.add_column("Provider")
    table.add_column("Key")
    table.add_column("Status")
    table.add_column("Latency ms")
    table.add_column("Models")
    table.add_column("Error")
    for row in results:
        models = row.get("models") if isinstance(row, dict) else []
        model_count = len(models) if isinstance(models, list) else 0
        table.add_row(
            str(row.get("provider")),
            str(row.get("key_id")),
            str(row.get("status")),
            f"{float(row.get('latency_ms', 0.0)):.2f}",
            str(model_count),
            _result_error_text(row),
        )
    console.print(table)


@providers_app.command("consistency")
def providers_consistency(
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
    refresh: bool = typer.Option(True, "--refresh/--cached", help="Refresh inventory before comparing"),
) -> None:
    import asyncio

    container = _container(config_path)
    cfg = container.runtime_config.get()
    if refresh:
        snapshot = asyncio.run(container.admin_service.refresh_inventory())
    else:
        snapshot = container.admin_service.current_inventory()
    snapshot = snapshot or {}

    runtime_by_key = {str(item.get("key_id")): item for item in container.key_registry.runtime_repo.list_states()}
    latest_health = {str(item.get("key_id")): item for item in container.admin_service.latest_health()}
    inventory_results = {
        str(item.get("key_id")): item
        for item in snapshot.get("key_results", [])
        if isinstance(item, dict)
    }

    table = Table(title="Provider Key Consistency", box=box.ASCII)
    table.add_column("Provider")
    table.add_column("Key")
    table.add_column("Config")
    table.add_column("Runtime")
    table.add_column("Health")
    table.add_column("Inventory")
    table.add_column("Models H/I")
    table.add_column("Last error", overflow="fold")

    rows = container.key_registry.list_configured_keys(cfg, include_unconfigured=True)
    if not rows:
        table.add_row("-", "-", "<empty>", "-", "-", "-", "0", "-")
    diagnostic_lines: list[str] = []
    for row in rows:
        key_id = str(row.get("id", ""))
        runtime = runtime_by_key.get(key_id, {})
        health = latest_health.get(key_id, {})
        inventory = inventory_results.get(key_id, {})
        health_models = _health_models_count(health)
        inventory_models = int(inventory.get("discovered_models", 0) or 0) if inventory else 0
        last_error = _first_non_empty(
            runtime.get("last_error_code"),
            health.get("error_code"),
            health.get("error_message"),
            inventory.get("error_code"),
            inventory.get("error_message"),
            "-",
        )
        table.add_row(
            str(row.get("provider", "")),
            key_id,
            "configured" if row.get("configured") else "placeholder",
            str(runtime.get("status", row.get("status", "unknown"))),
            str(health.get("status", "-")),
            str(inventory.get("status", "-")),
            f"{health_models}/{inventory_models}",
            last_error[:160],
        )
        diagnostic_lines.append(
            "Key consistency: "
            f"provider={row.get('provider', '')} key={key_id} "
            f"config={'configured' if row.get('configured') else 'placeholder'} "
            f"runtime={runtime.get('status', row.get('status', 'unknown'))} "
            f"health={health.get('status', '-')} inventory={inventory.get('status', '-')} "
            f"models={health_models}/{inventory_models} last_error={last_error}"
        )
    console.print(table)
    for line in diagnostic_lines:
        console.print(line)


def _health_models_count(row: dict[str, Any]) -> int:
    raw = row.get("models_json")
    if not raw:
        return 0
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return 0
    return len(parsed) if isinstance(parsed, list) else 0


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value)
        if text:
            return text
    return ""


@keys_app.command("list")
def keys_list(
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
    all_keys: bool = typer.Option(False, "--all", help="Show unconfigured placeholder keys too"),
) -> None:
    container = _container(config_path)
    rows = container.key_registry.list_configured_keys(
        container.runtime_config.get(),
        include_unconfigured=all_keys,
    )
    table = Table(title="Keys")
    table.add_column("Provider")
    table.add_column("ID")
    table.add_column("Configured")
    table.add_column("Active")
    table.add_column("Status")
    table.add_column("Priority")
    table.add_column("Errors")
    table.add_column("Last Error")
    for row in rows:
        table.add_row(
            str(row["provider"]),
            str(row["id"]),
            "yes" if row.get("configured") else "no",
            str(row["active"]),
            str(row["status"]),
            str(row["priority"]),
            str(row["consecutive_errors"]),
            str(row["last_error_code"] or ""),
        )
    console.print(table)


@keys_app.command("add")
def keys_add(
    provider: str = typer.Option(..., help="Provider name"),
    key_id: str = typer.Option(..., help="Unique key id"),
    secret: str = typer.Option(..., help="API key value"),
    account_id: str | None = typer.Option(None, help="Optional account id override for providers that need it"),
    priority: int = typer.Option(100, help="Priority (higher is better)"),
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
    validate: bool = typer.Option(True, help="Validate key after add"),
) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    providers = data.setdefault("providers", {})
    provider_cfg = providers.get(provider)
    if provider_cfg is None:
        raise typer.BadParameter(f"Provider not found in config: {provider}")

    keys = provider_cfg.setdefault("keys", [])
    if any(str(item.get("id")) == key_id for item in keys):
        raise typer.BadParameter(f"Key already exists: {key_id}")
    existing_key_ids = _configured_key_ids_by_provider(providers)
    existing_provider = existing_key_ids.get(key_id)
    if existing_provider is not None and existing_provider != provider:
        raise typer.BadParameter(
            f"Key id must be globally unique. '{key_id}' already exists in provider '{existing_provider}'."
        )

    keys.append(
        {
            "id": key_id,
            "key": secret,
            "account_id": account_id,
            "active": True,
            "priority": priority,
            "weight": 1,
            "tags": [],
            "limits": {"rpm": None},
            "cooldown": {"rate_limit_seconds": 30, "error_seconds": 15},
            "max_retries": 1,
            "max_consecutive_errors": 5,
        }
    )
    _save_yaml(path, data)
    console.print(f"Added key {key_id} to provider {provider}: {mask_secret(secret)}")

    if validate:
        import asyncio

        container = _container(str(path))
        result = asyncio.run(container.admin_service.validate_key(provider=provider, key_id=key_id))
        _print_key_validation_results([result], title="Key Validation")
        _refresh_inventory_after_key_change(str(path))


@keys_app.command("wizard")
def keys_wizard(
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
) -> None:
    _interactive_add_provider_key(config_path=config_path)


@keys_app.command("remove")
def keys_remove(
    key_id: str = typer.Option(..., help="Key id to remove"),
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    providers = data.get("providers", {})
    removed = False
    for provider_cfg in providers.values():
        keys = provider_cfg.get("keys", [])
        initial = len(keys)
        provider_cfg["keys"] = [item for item in keys if str(item.get("id")) != key_id]
        if len(provider_cfg["keys"]) != initial:
            removed = True
    if not removed:
        raise typer.BadParameter(f"Key not found: {key_id}")
    _save_yaml(path, data)
    console.print(f"Removed key: {key_id}")


@keys_app.command("validate")
def keys_validate(
    provider: str | None = typer.Option(None, help="Provider for targeted validation"),
    key_id: str | None = typer.Option(None, help="Key id for targeted validation"),
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
) -> None:
    import asyncio

    container = _container(config_path)
    if provider and key_id:
        result = asyncio.run(container.admin_service.validate_key(provider=provider, key_id=key_id))
        _print_key_validation_results([result], title="Key Validation")
        _refresh_inventory_after_key_change(config_path)
        return

    results = asyncio.run(container.admin_service.validate_all_keys())
    _print_key_validation_results(results, title="Key Validation")
    _refresh_inventory_after_key_change(config_path)


@keys_app.command("enable")
def keys_enable(
    key_id: str = typer.Option(..., help="Key id"),
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
) -> None:
    container = _container(config_path)
    container.key_registry.set_active(key_id, True)
    console.print(f"Enabled key runtime state: {key_id}")


@keys_app.command("disable")
def keys_disable(
    key_id: str = typer.Option(..., help="Key id"),
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
) -> None:
    container = _container(config_path)
    container.key_registry.set_active(key_id, False)
    console.print(f"Disabled key runtime state: {key_id}")


@routes_app.command("list")
def routes_list(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    cfg = load_gateway_config(config_path=config_path)
    snapshot = _current_inventory_snapshot(config_path=config_path, refresh=False)
    _print_generated_aliases_table(snapshot)
    _print_custom_aliases_table(cfg)


@routes_app.command("preview")
def routes_preview(
    model: str | None = typer.Option(None, help="Alias or direct model to preview"),
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
) -> None:
    _print_route_preview(config_path=config_path, model=model)


@routes_app.command("set-priority")
def routes_set_priority(
    alias: str = typer.Option(..., help="Alias to edit"),
    candidate: str = typer.Option(..., help="Candidate as provider/model"),
    position: int = typer.Option(1, help="1-based position in chain"),
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    aliases = data.setdefault("routes", {}).setdefault("aliases", {})
    route_cfg = aliases.get(alias)
    if route_cfg is None:
        raise typer.BadParameter(f"Alias not found: {alias}")

    if "/" not in candidate:
        raise typer.BadParameter("candidate must be provider/model")
    provider, model = candidate.split("/", 1)
    entry = {"provider": provider, "model": model}

    candidates = route_cfg.setdefault("candidates", [])
    candidates = [item for item in candidates if not (item.get("provider") == provider and item.get("model") == model)]
    index = max(0, min(len(candidates), position - 1))
    candidates.insert(index, entry)
    route_cfg["candidates"] = candidates
    _save_yaml(path, data)
    console.print(f"Updated route {alias}: moved {candidate} to position {position}")


@config_app.command("validate")
def config_validate(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    try:
        cfg = load_gateway_config(config_path=config_path)
        console.print(
            f"Config OK. Providers={len(cfg.providers)} Aliases={len(cfg.routes.aliases)} DB={cfg.storage.sqlite_path}"
        )
    except ConfigError as exc:
        console.print(f"Config invalid: {exc}")
        raise typer.Exit(1) from exc


@config_app.command("reload")
def config_reload(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    container = _container(config_path)
    result = container.admin_service.reload_config()
    console.print(result)


@logs_app.command("tail")
def logs_tail(
    file_path: str = typer.Option("gateway.log", help="Log file path"),
    lines: int = typer.Option(50, help="How many trailing lines"),
) -> None:
    path = Path(file_path)
    if not path.exists():
        console.print(f"Log file does not exist: {path}")
        raise typer.Exit(1)
    text_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in text_lines[-lines:]:
        console.print(line)


@cli_app.command("stats")
def stats(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    container = _container(config_path)
    console.print(container.admin_service.stats())


@cli_app.command("health")
def health(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    import asyncio

    container = _container(config_path)
    results = asyncio.run(container.admin_service.validate_all_keys())
    for row in results:
        console.print(row)


@cli_app.command("version")
def version(config_path: str = typer.Option("config/config.yaml", help="Path to current config.yaml")) -> None:
    _print_install_diagnostics(config_path=config_path)


def _run_update(
    config_path: str,
    repo: str = "FHRha/SimpleOpenRoad",
    version: str | None = None,
    ref: str | None = None,
    channel: str = "stable",
    arch: str | None = None,
    python_bin: str | None = None,
    install_dir: str | None = None,
    bin_dir: str | None = None,
    yes: bool = False,
    restart_service: bool = True,
) -> None:
    if version and ref:
        raise typer.BadParameter("Use either --version or --ref, not both")
    selected_channel = _normalize_release_channel(channel)

    if install_dir:
        install_root = Path(install_dir).expanduser().resolve()
    else:
        install_root = _detect_wrapper_install_root() or _guess_install_root(config_path)
    resolved_bin_dir = _resolve_bin_dir(install_root=install_root, explicit_bin_dir=bin_dir)
    resolved_version = None if ref else _resolve_update_version(
        repo=repo,
        requested_version=version,
        channel=selected_channel,
    )
    current_version = _read_installed_version(install_root)
    normalized_current_version = current_version.lstrip("v")
    normalized_target_version = resolved_version.lstrip("v") if resolved_version else None

    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Install dir: {install_root}",
                    f"Binary dir: {resolved_bin_dir}",
                    f"Repo: {repo}",
                    f"Source: Git ref {ref}" if ref else f"Version to install: {resolved_version}",
                    f"Release channel: {selected_channel}" if not ref else "Release channel: <not used for git ref>",
                    "Preserved: .env, config/config.yaml, data/",
                ]
            ),
            title="SimpleOpenRoad Update",
            border_style="green",
            box=box.ASCII,
        )
    )
    if normalized_target_version and normalized_current_version == normalized_target_version:
        console.print("Installed version is already the latest available for this channel. You can still reinstall it.")
    if not yes and not typer.confirm("Update SimpleOpenRoad now", default=True):
        raise typer.Exit(0)

    command = _build_update_command(
        install_root=install_root,
        bin_dir=resolved_bin_dir,
        repo=repo,
        version=resolved_version,
        ref=ref,
        channel=selected_channel,
        arch=arch,
        python_bin=python_bin,
    )
    _run_streaming_command(command)
    console.print("Update complete. User settings were preserved.")
    if restart_service:
        _restart_service_after_update(mode="system")


@cli_app.command("update")
def update(
    config_path: str = typer.Option("config/config.yaml", help="Path to current config.yaml"),
    repo: str = typer.Option("FHRha/SimpleOpenRoad", help="GitHub repository in owner/repo format"),
    version: str | None = typer.Option(None, help="Release tag to install; defaults to latest"),
    ref: str | None = typer.Option(None, help="Git ref/branch to install from source instead of a release"),
    channel: str = typer.Option("stable", help="Release channel: stable or prerelease"),
    arch: str | None = typer.Option(None, help="Target archive architecture; defaults to auto-detect"),
    python_bin: str | None = typer.Option(None, "--python", help="Python binary for venv creation"),
    install_dir: str | None = typer.Option(None, help="Installed package directory"),
    bin_dir: str | None = typer.Option(None, help="Directory containing sor wrapper"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not prompt for confirmation"),
    no_restart: bool = typer.Option(False, "--no-restart", help="Do not restart the system service after update"),
) -> None:
    _run_update(
        config_path=config_path,
        repo=repo,
        version=version,
        ref=ref,
        channel=channel,
        arch=arch,
        python_bin=python_bin,
        install_dir=install_dir,
        bin_dir=bin_dir,
        yes=yes,
        restart_service=not no_restart,
    )


@cli_app.command("uninstall")
def uninstall(
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
    mode: str = typer.Option("system", help="Service mode: system or user"),
    purge_data: bool = typer.Option(False, help="Remove SQLite runtime database files"),
    remove_config: bool = typer.Option(False, help="Remove config file"),
    full: bool = typer.Option(False, help="Remove service, runtime data, config, wrapper binary and install directory"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not prompt for full uninstall confirmation"),
) -> None:
    selected_mode = _service_mode(mode)
    if full:
        purge_data = True
        remove_config = True

    cfg = load_gateway_config(config_path=config_path)
    install_root = _guess_install_root(config_path)

    service_cleaned = False
    try:
        _ensure_systemd_available()
    except typer.BadParameter:
        if _stop_fallback_background_process(config_path=config_path):
            console.print("Stopped fallback background process.")
            service_cleaned = True
        else:
            console.print("Service cleanup skipped: systemd not available and no fallback PID found.")
    else:
        _check_system_mode_permissions(selected_mode)
        _run_systemctl(selected_mode, "disable", "--now", SERVICE_NAME, check=False)
        unit_path = _service_unit_path(selected_mode)
        if unit_path.exists():
            unit_path.unlink()
        _run_systemctl(selected_mode, "daemon-reload", check=False)
        console.print(f"Removed service unit: {unit_path}")
        service_cleaned = True

    if purge_data:
        removed = _remove_runtime_db(cfg.storage.sqlite_path)
        if removed:
            console.print("Removed runtime DB files:")
            for item in removed:
                console.print(f"- {item}")
        else:
            console.print("No runtime DB files found to remove.")

    cfg_path = Path(config_path)
    if remove_config:
        if cfg_path.exists():
            cfg_path.unlink()
            console.print(f"Removed config file: {cfg_path}")
        else:
            console.print("Config file is already missing.")

    removed_binaries: list[Path] = []
    removed_install_dirs: list[Path] = []
    if full:
        for binary_path in _candidate_sor_binaries(install_root):
            try:
                binary_path.unlink()
                removed_binaries.append(binary_path)
            except OSError as exc:
                console.print(f"Could not remove binary {binary_path}: {exc}")
        removed_install_dirs = _remove_install_tree(install_root, yes=yes)
        if removed_binaries:
            console.print("Removed wrapper binaries:")
            for item in removed_binaries:
                console.print(f"- {item}")
        if removed_install_dirs:
            console.print("Removed install directories:")
            for item in removed_install_dirs:
                console.print(f"- {item}")

    if not service_cleaned and not purge_data and not remove_config and not full:
        console.print("Nothing to remove.")
        return

    console.print("Uninstall complete.")


@service_app.command("install")
def service_install(
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
    mode: str = typer.Option("system", help="Install mode: system or user"),
    run_as: str | None = typer.Option(None, help="Linux user for system mode service"),
    start: bool = typer.Option(True, help="Start service right after install"),
    summary: bool = typer.Option(True, "--summary/--no-summary", help="Print setup summary after install", hidden=True),
) -> None:
    selected_mode = _service_mode(mode)
    _ensure_systemd_available()
    _check_system_mode_permissions(selected_mode)

    cfg = load_gateway_config(config_path=config_path)
    unit_path = _service_unit_path(selected_mode)
    unit_path.parent.mkdir(parents=True, exist_ok=True)

    effective_user = run_as
    if selected_mode == "system" and not effective_user:
        effective_user = os.getenv("SUDO_USER") or os.getenv("USER")

    unit_contents = _render_service_unit(selected_mode, config_path=config_path, run_as_user=effective_user)
    unit_path.write_text(unit_contents, encoding="utf-8")

    _run_systemctl(selected_mode, "daemon-reload")
    _run_systemctl(selected_mode, "enable", SERVICE_NAME)
    if start:
        _run_systemctl(selected_mode, "restart", SERVICE_NAME)

    console.print(f"Installed service unit: {unit_path}")
    console.print(f"Service {SERVICE_NAME}: {_service_status_text(selected_mode)}")
    if selected_mode == "user":
        current_user = os.getenv("USER") or "<user>"
        console.print(f"To keep user service alive without SSH session: sudo loginctl enable-linger {current_user}")
    if summary:
        _print_setup_summary(config_path=config_path, cfg=cfg)


@service_app.command("uninstall")
def service_uninstall(
    mode: str = typer.Option("system", help="Mode: system or user"),
) -> None:
    selected_mode = _service_mode(mode)
    _ensure_systemd_available()
    _check_system_mode_permissions(selected_mode)

    _run_systemctl(selected_mode, "disable", "--now", SERVICE_NAME, check=False)
    unit_path = _service_unit_path(selected_mode)
    if unit_path.exists():
        unit_path.unlink()
    _run_systemctl(selected_mode, "daemon-reload")
    console.print(f"Uninstalled service unit: {unit_path}")


@service_app.command("start")
def service_start(mode: str = typer.Option("system", help="Mode: system or user")) -> None:
    selected_mode = _service_mode(mode)
    _ensure_systemd_available()
    _check_system_mode_permissions(selected_mode)
    _run_systemctl(selected_mode, "start", SERVICE_NAME)
    console.print(f"Service {SERVICE_NAME}: {_service_status_text(selected_mode)}")


@service_app.command("stop")
def service_stop(mode: str = typer.Option("system", help="Mode: system or user")) -> None:
    selected_mode = _service_mode(mode)
    _ensure_systemd_available()
    _check_system_mode_permissions(selected_mode)
    _run_systemctl(selected_mode, "stop", SERVICE_NAME)
    console.print(f"Service {SERVICE_NAME}: {_service_status_text(selected_mode)}")


@service_app.command("restart")
def service_restart(mode: str = typer.Option("system", help="Mode: system or user")) -> None:
    selected_mode = _service_mode(mode)
    _ensure_systemd_available()
    _check_system_mode_permissions(selected_mode)
    _run_systemctl(selected_mode, "restart", SERVICE_NAME)
    console.print(f"Service {SERVICE_NAME}: {_service_status_text(selected_mode)}")


@service_app.command("status")
def service_status(mode: str = typer.Option("system", help="Mode: system or user")) -> None:
    selected_mode = _service_mode(mode)
    _ensure_systemd_available()
    _check_system_mode_permissions(selected_mode)
    status_proc = _run_systemctl(selected_mode, "status", "--no-pager", SERVICE_NAME, check=False)
    output = status_proc.stdout.strip() or status_proc.stderr.strip() or "no status output"
    console.print(output)


@service_app.command("logs")
def service_logs(
    mode: str = typer.Option("system", help="Mode: system or user"),
    lines: int = typer.Option(100, help="Number of log lines"),
) -> None:
    selected_mode = _service_mode(mode)
    _ensure_systemd_available()
    _check_system_mode_permissions(selected_mode)
    command = ["journalctl", "-u", f"{SERVICE_NAME}.service", "-n", str(lines), "--no-pager"]
    if selected_mode == "user":
        command.insert(1, "--user")
    proc = _run_command(command, check=False)
    text = proc.stdout.strip() or proc.stderr.strip() or "no log output"
    console.print(text)


def _pause() -> None:
    typer.prompt("Press Enter to return", default="", show_default=False)


def _prompt_release_channel(default: str = "stable") -> str:
    choice = typer.prompt(
        "Release channel [stable/prerelease]",
        default=default,
        show_default=True,
    ).strip()
    return _normalize_release_channel(choice)


def _print_menu(title: str, lines: list[str], config_path: str) -> None:
    console.print(
        Panel.fit(
            "\n".join(lines),
            title=title,
            subtitle=f"Config: {config_path}",
            border_style="cyan",
            box=box.ASCII,
        )
    )


def _run_capabilities_panel(config_path: str) -> None:
    def _edit_patterns(key_name: str, title: str) -> None:
        while True:
            cfg = load_gateway_config(config_path=config_path)
            values = list(getattr(cfg.model_capabilities, key_name))
            _print_menu(
                title=title,
                config_path=config_path,
                lines=[
                    "1) Show patterns",
                    "2) Add pattern",
                    "3) Remove pattern by number",
                    "0) Back",
                ],
            )
            sub_choice = _prompt_menu_choice()
            if sub_choice == "1":
                _print_numbered_items(title, values)
                _pause()
            elif sub_choice == "2":
                value = typer.prompt("Pattern").strip()
                if not value:
                    console.print("Pattern cannot be empty")
                elif value in values:
                    console.print("Pattern already exists")
                else:
                    values.append(value)
                    _update_config_value(config_path, values, "model_capabilities", key_name)
                    console.print(f"Added {key_name} pattern: {value}")
                _pause()
            elif sub_choice == "3":
                if not values:
                    console.print("No patterns to remove")
                    _pause()
                    continue
                _print_numbered_items(title, values)
                selected = _prompt_numbered_choice(len(values), "Pattern number to remove")
                removed = values.pop(selected - 1)
                _update_config_value(config_path, values, "model_capabilities", key_name)
                console.print(f"Removed {key_name} pattern: {removed}")
                _pause()
            elif sub_choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()

    while True:
        _print_menu(
            title="SimpleOpenRoad / Settings / Model Capabilities",
            config_path=config_path,
            lines=[
                "1) Show capability settings",
                "2) Edit tool_capable patterns",
                "3) Edit tool_disabled patterns",
                "4) Reset capability patterns to defaults",
                "5) Inventory overrides",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                _show_settings_summary(config_path)
                _pause()
            elif choice == "2":
                _edit_patterns("tool_capable", "tool_capable patterns")
            elif choice == "3":
                _edit_patterns("tool_disabled", "tool_disabled patterns")
            elif choice == "4":
                defaults = GatewayConfig().model_capabilities
                _update_config_value(
                    config_path,
                    defaults.model_dump(),
                    "model_capabilities",
                )
                console.print("Reset model_capabilities to defaults")
                _pause()
            elif choice == "5":
                _run_inventory_overrides_panel(config_path=config_path)
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_inventory_schedule_panel(config_path: str) -> None:
    while True:
        cfg = load_gateway_config(config_path=config_path)
        _print_menu(
            title="SimpleOpenRoad / Settings / Inventory Refresh",
            config_path=config_path,
            lines=[
                f"1) Set refresh time (current: {cfg.inventory.refresh_time})",
                f"2) Set refresh timezone (current: {cfg.inventory.refresh_timezone})",
                f"3) Set refresh interval hours (current: {cfg.inventory.refresh_interval_hours})",
                "4) Reset schedule to defaults",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                value = typer.prompt("inventory.refresh_time (HH:MM)", default=cfg.inventory.refresh_time).strip()
                _update_config_value(config_path, value, "inventory", "refresh_time")
                load_gateway_config(config_path=config_path)
                console.print(f"Updated inventory.refresh_time: {value}")
                _pause()
            elif choice == "2":
                value = typer.prompt(
                    "inventory.refresh_timezone",
                    default=cfg.inventory.refresh_timezone,
                ).strip()
                _update_config_value(config_path, value, "inventory", "refresh_timezone")
                console.print(f"Updated inventory.refresh_timezone: {value}")
                _pause()
            elif choice == "3":
                value = typer.prompt(
                    "inventory.refresh_interval_hours",
                    default=str(cfg.inventory.refresh_interval_hours),
                ).strip()
                _update_config_value(config_path, int(value), "inventory", "refresh_interval_hours")
                load_gateway_config(config_path=config_path)
                console.print(f"Updated inventory.refresh_interval_hours: {value}")
                _pause()
            elif choice == "4":
                defaults = GatewayConfig().inventory
                _update_config_value(config_path, defaults.refresh_time, "inventory", "refresh_time")
                _update_config_value(config_path, defaults.refresh_timezone, "inventory", "refresh_timezone")
                _update_config_value(
                    config_path,
                    defaults.refresh_interval_hours,
                    "inventory",
                    "refresh_interval_hours",
                )
                console.print("Reset inventory refresh schedule to defaults")
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _select_alias_name(config_path: str) -> str | None:
    cfg = load_gateway_config(config_path=config_path)
    aliases = list(cfg.routes.aliases)
    if not aliases:
        console.print("No custom aliases configured")
        return None
    _print_numbered_items("Custom Aliases", aliases)
    selected = _prompt_numbered_choice(len(aliases), "Alias number")
    return aliases[selected - 1]


def _show_alias_candidates(config_path: str, alias_name: str) -> list[dict[str, str]]:
    data = _load_yaml(_config_path(config_path))
    rows = _nested_get(data, "routes", "aliases", alias_name, "candidates", default=[])
    candidates = [item for item in rows if isinstance(item, dict)]
    table = Table(title=f"Alias Chain: {alias_name}", box=box.ASCII)
    table.add_column("#")
    table.add_column("Provider")
    table.add_column("Model")
    if not candidates:
        table.add_row("-", "<empty>", "<empty>")
    else:
        for index, item in enumerate(candidates, start=1):
            table.add_row(str(index), str(item.get("provider", "")), str(item.get("model", "")))
    console.print(table)
    return candidates


def _create_custom_alias(config_path: str) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    aliases = data.setdefault("routes", {}).setdefault("aliases", {})
    alias_name = typer.prompt("New custom alias", default="custom/my-route").strip()
    if not alias_name:
        raise typer.BadParameter("Alias cannot be empty")
    if alias_name in aliases:
        raise typer.BadParameter(f"Alias already exists: {alias_name}")
    aliases[alias_name] = {
        "strategy": "strict_priority",
        "selection": "ordered",
        "candidates": [],
    }
    _save_yaml(path, data)
    console.print(f"Created custom alias: {alias_name}")


def _remove_custom_alias(config_path: str) -> None:
    alias_name = _select_alias_name(config_path)
    if alias_name is None:
        return
    path = _config_path(config_path)
    data = _load_yaml(path)
    aliases = data.setdefault("routes", {}).setdefault("aliases", {})
    aliases.pop(alias_name, None)
    _save_yaml(path, data)
    console.print(f"Removed custom alias: {alias_name}")


def _select_provider_name(config_path: str) -> str:
    cfg = load_gateway_config(config_path=config_path)
    return _select_provider_from_names(list(cfg.providers), prompt="Provider number")


def _count_user_configured_keys(provider_cfg: Any) -> int:
    configured_keys = [key for key in provider_cfg.keys if is_configured_secret(key.key)]
    if provider_cfg.auth_required:
        return len(configured_keys)
    return sum(1 for key in configured_keys if str(key.key).strip().lower() != "local")


def _has_user_configured_keys(provider_cfg: Any) -> bool:
    return _count_user_configured_keys(provider_cfg) > 0


def _select_provider_name_with_configured_keys(config_path: str) -> str | None:
    cfg = load_gateway_config(config_path=config_path)
    provider_names = [
        provider_name
        for provider_name, provider_cfg in cfg.providers.items()
        if _has_user_configured_keys(provider_cfg)
    ]
    if not provider_names:
        console.print("No providers with configured keys are available")
        return None
    return _select_provider_from_names(provider_names, prompt="Provider number")


def _select_option_from_list(title: str, options: list[str], prompt: str) -> str:
    _print_numbered_items(title, options)
    selected = _prompt_numbered_choice(len(options), prompt)
    return options[selected - 1]


def _parse_optional_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"", "skip", "none"}:
        return None
    if normalized in {"true", "yes", "y", "1"}:
        return True
    if normalized in {"false", "no", "n", "0"}:
        return False
    raise typer.BadParameter("Use true, false, or skip")


def _show_inventory_overrides(config_path: str) -> list[dict[str, Any]]:
    cfg = load_gateway_config(config_path=config_path)
    table = Table(title="Inventory Overrides", box=box.ASCII)
    table.add_column("#")
    table.add_column("Provider")
    table.add_column("Pattern")
    table.add_column("Mode")
    table.add_column("Categories")
    table.add_column("Tools")
    table.add_column("Reason")
    rows = [item.model_dump(exclude_none=True) for item in cfg.inventory.overrides]
    if not rows:
        table.add_row("-", "*", "<empty>", "-", "-", "-", "-")
    else:
        for index, item in enumerate(rows, start=1):
            mode_parts: list[str] = []
            if item.get("force_include"):
                mode_parts.append("include")
            if item.get("force_exclude"):
                mode_parts.append("exclude")
            if item.get("force_modality"):
                mode_parts.append(f"modality={item['force_modality']}")
            tool_parts: list[str] = []
            if "force_tool_capable" in item:
                tool_parts.append(f"capable={item['force_tool_capable']}")
            if "force_tool_disabled" in item:
                tool_parts.append(f"disabled={item['force_tool_disabled']}")
            table.add_row(
                str(index),
                str(item.get("provider") or "*"),
                str(item.get("model_pattern", "")),
                ", ".join(mode_parts) or "-",
                ", ".join(item.get("force_categories", [])) or "-",
                ", ".join(tool_parts) or "-",
                str(item.get("reason", "") or "-"),
            )
    console.print(table)
    return rows


def _add_inventory_override(config_path: str) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    provider = typer.prompt("Provider pattern", default="*").strip()
    model_pattern = typer.prompt("Model pattern", default="*").strip()
    if not model_pattern:
        raise typer.BadParameter("Model pattern cannot be empty")
    force_include = typer.confirm("Force include matching models", default=False)
    force_exclude = typer.confirm("Force exclude matching models", default=False)
    force_modality_raw = typer.prompt(
        "Force modality [text/image/video/audio/embedding/other/skip]",
        default="skip",
    ).strip().lower()
    force_modality = None if force_modality_raw in {"", "skip", "none"} else force_modality_raw
    categories_raw = typer.prompt(
        "Force categories (comma-separated: free,fast,general,reasoning,code)",
        default="",
    ).strip()
    force_categories = [item for item in _parse_pattern_list(categories_raw) if item in {"free", "fast", "general", "reasoning", "code"}]
    force_tool_capable = _parse_optional_bool(
        typer.prompt("Force tool_capable [true/false/skip]", default="skip")
    )
    force_tool_disabled = _parse_optional_bool(
        typer.prompt("Force tool_disabled [true/false/skip]", default="skip")
    )
    reason = typer.prompt("Reason", default="").strip()

    override: dict[str, Any] = {"model_pattern": model_pattern}
    if provider != "*":
        override["provider"] = provider
    if force_include:
        override["force_include"] = True
    if force_exclude:
        override["force_exclude"] = True
    if force_modality:
        override["force_modality"] = force_modality
    if force_categories:
        override["force_categories"] = force_categories
    if force_tool_capable is not None:
        override["force_tool_capable"] = force_tool_capable
    if force_tool_disabled is not None:
        override["force_tool_disabled"] = force_tool_disabled
    if reason:
        override["reason"] = reason

    overrides = _nested_get(data, "inventory", "overrides", default=[])
    if not isinstance(overrides, list):
        overrides = []
    overrides.append(override)
    _nested_set(data, overrides, "inventory", "overrides")
    _save_yaml(path, data)
    console.print(f"Added inventory override for pattern: {model_pattern}")


def _remove_inventory_override(config_path: str) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    overrides = _nested_get(data, "inventory", "overrides", default=[])
    rows = [item for item in overrides if isinstance(item, dict)]
    if not rows:
        console.print("No inventory overrides configured")
        return
    _show_inventory_overrides(config_path)
    selected = _prompt_numbered_choice(len(rows), "Override number to remove")
    removed = rows.pop(selected - 1)
    _nested_set(data, rows, "inventory", "overrides")
    _save_yaml(path, data)
    console.print(f"Removed inventory override: {removed.get('model_pattern', '<unknown>')}")


def _run_inventory_overrides_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Settings / Inventory Overrides",
            config_path=config_path,
            lines=[
                "1) Show overrides",
                "2) Add override",
                "3) Remove override by number",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                _show_inventory_overrides(config_path)
                _pause()
            elif choice == "2":
                _add_inventory_override(config_path)
                _pause()
            elif choice == "3":
                _remove_inventory_override(config_path)
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _show_provider_summary(config_path: str, provider_name: str) -> None:
    cfg = load_gateway_config(config_path=config_path)
    provider = cfg.providers[provider_name]
    table = Table(title=f"Provider Settings: {provider_name}", box=box.ASCII)
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("category", _provider_category(provider_name))
    table.add_row("enabled", str(provider.enabled))
    table.add_row("priority", str(provider.priority))
    if provider.account_id:
        table.add_row("account_id", str(provider.account_id))
    table.add_row("timeout_seconds", str(provider.timeout_seconds))
    table.add_row("keys", str(len(provider.keys)))
    console.print(table)


def _select_provider_key(config_path: str, provider_name: str) -> tuple[int, dict[str, Any]] | tuple[None, None]:
    path = _config_path(config_path)
    data = _load_yaml(path)
    keys = _nested_get(data, "providers", provider_name, "keys", default=[])
    key_rows = [item for item in keys if isinstance(item, dict)]
    if not key_rows:
        console.print("No keys configured for this provider")
        return None, None
    labels = [f"{item.get('id', '<no-id>')} | priority={item.get('priority', 100)}" for item in key_rows]
    _print_numbered_items(f"Provider Keys: {provider_name}", labels)
    selected = _prompt_numbered_choice(len(key_rows), "Key number")
    return selected - 1, key_rows[selected - 1]


def _update_provider_key(config_path: str, provider_name: str, key_index: int, key_data: dict[str, Any]) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    keys = _nested_get(data, "providers", provider_name, "keys", default=[])
    if not isinstance(keys, list) or key_index < 0 or key_index >= len(keys):
        raise typer.BadParameter("Key index is out of range")
    keys[key_index] = key_data
    _nested_set(data, keys, "providers", provider_name, "keys")
    _save_yaml(path, data)


def _select_provider_and_key(config_path: str) -> tuple[str | None, int | None, dict[str, Any] | None]:
    provider_name = _select_provider_name_with_configured_keys(config_path)
    if provider_name is None:
        return None, None, None
    key_index, key_data = _select_provider_key(config_path, provider_name)
    return provider_name, key_index, key_data


def _run_provider_key_settings_panel(config_path: str, provider_name: str) -> None:
    try:
        key_index, key_data = _select_provider_key(config_path, provider_name)
    except Exception as exc:  # noqa: BLE001
        console.print(f"Operation failed: {exc}")
        _pause()
        return
    if key_data is None:
        _pause()
        return

    _run_provider_key_settings_for_selected(config_path, provider_name, key_index, key_data)


def _run_provider_key_settings_for_selected(
    config_path: str,
    provider_name: str,
    key_index: int,
    key_data: dict[str, Any],
) -> None:
    key_id = str(key_data.get("id", "<no-id>"))
    while True:
        _print_menu(
            title=f"SimpleOpenRoad / Settings / Provider Key / {provider_name} / {key_id}",
            config_path=config_path,
            lines=[
                "1) Set key priority",
                "2) Set key max_retries",
                "3) Set key max_consecutive_errors",
                "4) Set key rate_limit cooldown",
                "5) Set key error cooldown",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                value = int(typer.prompt("Key priority", default=str(key_data.get("priority", 100))).strip())
                key_data["priority"] = value
                label = "priority"
            elif choice == "2":
                value = int(typer.prompt("Key max_retries", default=str(key_data.get("max_retries", 1))).strip())
                key_data["max_retries"] = value
                label = "max_retries"
            elif choice == "3":
                value = int(
                    typer.prompt(
                        "Key max_consecutive_errors",
                        default=str(key_data.get("max_consecutive_errors", 5)),
                    ).strip()
                )
                key_data["max_consecutive_errors"] = value
                label = "max_consecutive_errors"
            elif choice == "4":
                cooldown = key_data.setdefault("cooldown", {})
                value = int(
                    typer.prompt(
                        "Key cooldown.rate_limit_seconds",
                        default=str(cooldown.get("rate_limit_seconds", 30)),
                    ).strip()
                )
                cooldown["rate_limit_seconds"] = value
                label = "cooldown.rate_limit_seconds"
            elif choice == "5":
                cooldown = key_data.setdefault("cooldown", {})
                value = int(
                    typer.prompt(
                        "Key cooldown.error_seconds",
                        default=str(cooldown.get("error_seconds", 15)),
                    ).strip()
                )
                cooldown["error_seconds"] = value
                label = "cooldown.error_seconds"
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
                continue
            _update_provider_key(config_path, provider_name, key_index, key_data)
            console.print(f"Updated key {key_data.get('id')}: {label}={value}")
            _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_provider_settings_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Settings / Providers",
            config_path=config_path,
            lines=[
                "1) Show provider settings",
                "2) Set provider priority",
                "3) Set provider timeout",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                provider_name = _select_provider_name(config_path)
                _show_provider_summary(config_path, provider_name)
                _pause()
            elif choice == "2":
                provider_name = _select_provider_name(config_path)
                cfg = load_gateway_config(config_path=config_path)
                value = int(typer.prompt("Provider priority", default=str(cfg.providers[provider_name].priority)).strip())
                _update_config_value(config_path, value, "providers", provider_name, "priority")
                console.print(f"Updated provider {provider_name}: priority={value}")
                _pause()
            elif choice == "3":
                provider_name = _select_provider_name(config_path)
                cfg = load_gateway_config(config_path=config_path)
                value = int(
                    typer.prompt("Provider timeout_seconds", default=str(cfg.providers[provider_name].timeout_seconds)).strip()
                )
                _update_config_value(config_path, value, "providers", provider_name, "timeout_seconds")
                console.print(f"Updated provider {provider_name}: timeout_seconds={value}")
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _remove_provider_key_by_number(config_path: str) -> None:
    provider_name, key_index, key_data = _select_provider_and_key(config_path)
    if key_data is None or key_index is None or provider_name is None:
        console.print("No key selected")
        return
    _remove_selected_provider_key(config_path, provider_name, key_index, key_data)


def _remove_selected_provider_key(
    config_path: str,
    provider_name: str,
    key_index: int,
    key_data: dict[str, Any],
) -> None:
    if not typer.confirm(f"Remove key '{key_data.get('id')}' from config", default=False):
        console.print("Removal cancelled")
        return
    path = _config_path(config_path)
    data = _load_yaml(path)
    keys = _nested_get(data, "providers", provider_name, "keys", default=[])
    if not isinstance(keys, list) or key_index < 0 or key_index >= len(keys):
        raise typer.BadParameter("Key index is out of range")
    keys.pop(key_index)
    _nested_set(data, keys, "providers", provider_name, "keys")
    _save_yaml(path, data)
    console.print(f"Removed key: {key_data.get('id')}")


def _toggle_provider_key_active(config_path: str) -> None:
    provider_name, key_index, key_data = _select_provider_and_key(config_path)
    if key_data is None or key_index is None or provider_name is None:
        console.print("No key selected")
        return
    _toggle_selected_provider_key_active(config_path, provider_name, key_index, key_data)


def _toggle_selected_provider_key_active(
    config_path: str,
    provider_name: str,
    key_index: int,
    key_data: dict[str, Any],
) -> None:
    current = bool(key_data.get("active", True))
    key_data["active"] = not current
    _update_provider_key(config_path, provider_name, key_index, key_data)
    console.print(f"Updated key {key_data.get('id')}: active={key_data['active']}")


def _rename_provider_key_id(config_path: str) -> None:
    provider_name, key_index, key_data = _select_provider_and_key(config_path)
    if key_data is None or key_index is None or provider_name is None:
        console.print("No key selected")
        return
    _rename_selected_provider_key_id(config_path, provider_name, key_index, key_data)


def _rename_selected_provider_key_id(
    config_path: str,
    provider_name: str,
    key_index: int,
    key_data: dict[str, Any],
) -> None:
    current_id = str(key_data.get("id", ""))
    new_id = typer.prompt("New key ID", default=current_id).strip()
    if not new_id:
        raise typer.BadParameter("Key ID cannot be empty")
    cfg = load_gateway_config(config_path=config_path)
    existing_ids = {key.id for provider in cfg.providers.values() for key in provider.keys}
    if new_id != current_id and new_id in existing_ids:
        raise typer.BadParameter(f"Key ID already exists: {new_id}")
    key_data["id"] = new_id
    _update_provider_key(config_path, provider_name, key_index, key_data)
    console.print(f"Renamed key: {current_id} -> {new_id}")


def _replace_selected_provider_key_value(
    config_path: str,
    provider_name: str,
    key_index: int,
    key_data: dict[str, Any],
) -> None:
    secret = typer.prompt("New API key", hide_input=True, confirmation_prompt=True).strip()
    if not secret:
        raise typer.BadParameter("API key cannot be empty")
    key_data["key"] = secret
    key_data["active"] = True
    _update_provider_key(config_path, provider_name, key_index, key_data)
    console.print(f"Replaced API key value for {key_data.get('id')}: {mask_secret(secret)}")
    if typer.confirm("Validate key now", default=True):
        keys_validate(provider=provider_name, key_id=str(key_data.get("id")), config_path=config_path)


def _reset_selected_provider_key_runtime_state(
    config_path: str,
    provider_name: str,
    key_data: dict[str, Any],
) -> None:
    key_id = str(key_data.get("id", ""))
    if not key_id:
        raise typer.BadParameter("Key ID cannot be empty")
    registry = _runtime_key_registry(load_gateway_config(config_path=config_path))
    registry.reset_state(provider=provider_name, key_id=key_id, active=bool(key_data.get("active", True)))
    console.print(f"Reset runtime state for key: {key_id}")


def _show_selected_provider_key(provider_name: str, key_data: dict[str, Any]) -> None:
    table = Table(title=f"Provider Key: {provider_name}/{key_data.get('id', '<no-id>')}", box=box.ASCII)
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("id", str(key_data.get("id", "")))
    if provider_name == "cloudflare" and key_data.get("account_id"):
        table.add_row("account_id", str(key_data.get("account_id", "")))
    table.add_row("configured", "yes" if is_configured_secret(str(key_data.get("key", ""))) else "no")
    table.add_row("active", str(key_data.get("active", True)))
    table.add_row("priority", str(key_data.get("priority", 100)))
    table.add_row("max_retries", str(key_data.get("max_retries", 1)))
    table.add_row("max_consecutive_errors", str(key_data.get("max_consecutive_errors", 5)))
    cooldown = key_data.get("cooldown", {})
    if isinstance(cooldown, dict):
        table.add_row("cooldown.rate_limit_seconds", str(cooldown.get("rate_limit_seconds", 30)))
        table.add_row("cooldown.error_seconds", str(cooldown.get("error_seconds", 15)))
    console.print(table)


def _run_selected_key_management_panel(
    config_path: str,
    provider_name: str,
    key_index: int,
    key_data: dict[str, Any],
) -> None:
    while True:
        current_id = str(key_data.get("id", "<no-id>"))
        _print_menu(
            title=f"SimpleOpenRoad / Providers and Keys / {provider_name} / {current_id}",
            config_path=config_path,
            lines=[
                "1) Show selected key",
                "2) Replace API key value",
                "3) Edit retry, priority and cooldown",
                "4) Toggle key active",
                "5) Rename key ID",
                "6) Remove key",
                "7) Reset runtime state",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                _show_selected_provider_key(provider_name, key_data)
                _pause()
            elif choice == "2":
                _replace_selected_provider_key_value(config_path, provider_name, key_index, key_data)
                _pause()
            elif choice == "3":
                _run_provider_key_settings_for_selected(config_path, provider_name, key_index, key_data)
                return
            elif choice == "4":
                _toggle_selected_provider_key_active(config_path, provider_name, key_index, key_data)
                _pause()
            elif choice == "5":
                _rename_selected_provider_key_id(config_path, provider_name, key_index, key_data)
                key_data = _load_yaml(_config_path(config_path))["providers"][provider_name]["keys"][key_index]
                _pause()
            elif choice == "6":
                _remove_selected_provider_key(config_path, provider_name, key_index, key_data)
                _pause()
                return
            elif choice == "7":
                _reset_selected_provider_key_runtime_state(config_path, provider_name, key_data)
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_manage_existing_key_panel(config_path: str) -> None:
    provider_name, key_index, key_data = _select_provider_and_key(config_path)
    if key_data is None or key_index is None or provider_name is None:
        console.print("No key selected")
        return
    _run_selected_key_management_panel(config_path, provider_name, key_index, key_data)


def _add_alias_candidate(config_path: str, alias_name: str) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    candidates = _nested_get(data, "routes", "aliases", alias_name, "candidates", default=[])
    if not isinstance(candidates, list):
        candidates = []
    provider_name = _select_provider_name(config_path)
    model_name = typer.prompt("Model id").strip()
    if not model_name:
        raise typer.BadParameter("Model id cannot be empty")
    position = int(typer.prompt("Insert position", default=str(len(candidates) + 1)).strip())
    position = max(1, min(len(candidates) + 1, position))
    candidates.insert(position - 1, {"provider": provider_name, "model": model_name})
    _nested_set(data, candidates, "routes", "aliases", alias_name, "candidates")
    _save_yaml(path, data)
    console.print(f"Added candidate to {alias_name}: {provider_name}/{model_name}")


def _remove_alias_candidate(config_path: str, alias_name: str) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    candidates = _show_alias_candidates(config_path, alias_name)
    if not candidates:
        console.print("No candidates to remove")
        return
    selected = _prompt_numbered_choice(len(candidates), "Candidate number to remove")
    removed = candidates.pop(selected - 1)
    _nested_set(data, candidates, "routes", "aliases", alias_name, "candidates")
    _save_yaml(path, data)
    console.print(f"Removed candidate: {removed.get('provider')}/{removed.get('model')}")


def _move_alias_candidate(config_path: str, alias_name: str) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    candidates = _show_alias_candidates(config_path, alias_name)
    if len(candidates) < 2:
        console.print("Need at least two candidates to reorder")
        return
    selected = _prompt_numbered_choice(len(candidates), "Candidate number to move")
    target = _prompt_numbered_choice(len(candidates), "New position")
    item = candidates.pop(selected - 1)
    candidates.insert(target - 1, item)
    _nested_set(data, candidates, "routes", "aliases", alias_name, "candidates")
    _save_yaml(path, data)
    console.print(f"Moved candidate to position {target}: {item.get('provider')}/{item.get('model')}")


def _run_alias_chain_editor(config_path: str, alias_name: str) -> None:
    while True:
        _print_menu(
            title=f"SimpleOpenRoad / Settings / Alias Chain / {alias_name}",
            config_path=config_path,
            lines=[
                "1) Show chain",
                "2) Add candidate",
                "3) Remove candidate by number",
                "4) Move candidate by number",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                _show_alias_candidates(config_path, alias_name)
                _pause()
            elif choice == "2":
                _add_alias_candidate(config_path, alias_name)
                _pause()
            elif choice == "3":
                _remove_alias_candidate(config_path, alias_name)
                _pause()
            elif choice == "4":
                _move_alias_candidate(config_path, alias_name)
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_alias_settings_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Settings / Alias Chains",
            config_path=config_path,
            lines=[
                "1) Show generated and custom aliases",
                "2) Edit custom alias chain by number",
                "3) Set custom alias strategy",
                "4) Set custom alias selection mode",
                "5) Create custom alias",
                "6) Remove custom alias",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                cfg = load_gateway_config(config_path=config_path)
                snapshot = _current_inventory_snapshot(config_path=config_path, refresh=False)
                _print_generated_aliases_table(snapshot)
                _print_custom_aliases_table(cfg)
                _pause()
            elif choice == "2":
                alias_name = _select_alias_name(config_path)
                if alias_name is not None:
                    _run_alias_chain_editor(config_path, alias_name)
            elif choice == "3":
                alias_name = _select_alias_name(config_path)
                if alias_name is not None:
                    value = _select_option_from_list("Route Strategies", _ROUTE_STRATEGY_OPTIONS, "Strategy number")
                    _update_config_value(config_path, value, "routes", "aliases", alias_name, "strategy")
                    console.print(f"Updated alias {alias_name}: strategy={value}")
                    _pause()
            elif choice == "4":
                alias_name = _select_alias_name(config_path)
                if alias_name is not None:
                    value = _select_option_from_list("Alias Selection Modes", _ALIAS_SELECTION_OPTIONS, "Selection number")
                    _update_config_value(config_path, value, "routes", "aliases", alias_name, "selection")
                    console.print(f"Updated alias {alias_name}: selection={value}")
                    _pause()
            elif choice == "5":
                _create_custom_alias(config_path)
                _pause()
            elif choice == "6":
                _remove_custom_alias(config_path)
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _show_model_quarantine_settings(config_path: str) -> None:
    cfg = load_gateway_config(config_path=config_path)
    quarantine = cfg.routing.model_quarantine
    table = Table(title="Model Quarantine Settings", box=box.ASCII)
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("enabled", str(quarantine.enabled))
    table.add_row("failure_threshold", str(quarantine.failure_threshold))
    table.add_row("default_ttl_seconds", str(quarantine.default_ttl_seconds))
    for error_class, ttl in sorted(quarantine.error_ttl_seconds.items()):
        table.add_row(f"error_ttl_seconds.{error_class}", str(ttl))
    console.print(table)

    overrides = Table(title="Model Quarantine Overrides", box=box.ASCII)
    overrides.add_column("#")
    overrides.add_column("Provider")
    overrides.add_column("Model pattern")
    overrides.add_column("Threshold")
    overrides.add_column("TTL seconds")
    if not quarantine.overrides:
        overrides.add_row("-", "-", "<empty>", "-", "-")
    else:
        for index, item in enumerate(quarantine.overrides, start=1):
            overrides.add_row(
                str(index),
                item.provider or "*",
                item.model_pattern,
                str(item.failure_threshold if item.failure_threshold is not None else "<default>"),
                str(item.ttl_seconds if item.ttl_seconds is not None else "<default>"),
            )
    console.print(overrides)


def _run_model_quarantine_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Settings / Model Quarantine",
            config_path=config_path,
            lines=[
                "1) Show model quarantine settings",
                "2) Toggle model quarantine",
                "3) Set default failure threshold",
                "4) Set default TTL",
                "5) Set TTL for error class",
                "6) Add provider/model override",
                "7) Remove override",
                "8) Reset model quarantine state",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                _show_model_quarantine_settings(config_path)
                _pause()
            elif choice == "2":
                cfg = load_gateway_config(config_path=config_path)
                value = typer.confirm(
                    "Enable model quarantine",
                    default=cfg.routing.model_quarantine.enabled,
                )
                _update_config_value(config_path, value, "routing", "model_quarantine", "enabled")
                console.print(f"Updated routing.model_quarantine.enabled: {value}")
                _pause()
            elif choice == "3":
                cfg = load_gateway_config(config_path=config_path)
                value = typer.prompt(
                    "routing.model_quarantine.failure_threshold",
                    default=str(cfg.routing.model_quarantine.failure_threshold),
                ).strip()
                _update_config_value(
                    config_path,
                    max(1, int(value)),
                    "routing",
                    "model_quarantine",
                    "failure_threshold",
                )
                console.print(f"Updated routing.model_quarantine.failure_threshold: {value}")
                _pause()
            elif choice == "4":
                cfg = load_gateway_config(config_path=config_path)
                value = typer.prompt(
                    "routing.model_quarantine.default_ttl_seconds",
                    default=str(cfg.routing.model_quarantine.default_ttl_seconds),
                ).strip()
                _update_config_value(
                    config_path,
                    max(0, int(value)),
                    "routing",
                    "model_quarantine",
                    "default_ttl_seconds",
                )
                console.print(f"Updated routing.model_quarantine.default_ttl_seconds: {value}")
                _pause()
            elif choice == "5":
                cfg = load_gateway_config(config_path=config_path)
                error_class = typer.prompt(
                    "Error class",
                    default="unsupported_model",
                ).strip()
                current = cfg.routing.model_quarantine.error_ttl_seconds.get(
                    error_class,
                    cfg.routing.model_quarantine.default_ttl_seconds,
                )
                ttl = typer.prompt("TTL seconds", default=str(current)).strip()
                path = _config_path(config_path)
                data = _load_yaml(path)
                ttl_map = data.setdefault("routing", {}).setdefault("model_quarantine", {}).setdefault(
                    "error_ttl_seconds",
                    {},
                )
                ttl_map[error_class] = max(0, int(ttl))
                _save_yaml(path, data)
                console.print(f"Updated routing.model_quarantine.error_ttl_seconds.{error_class}: {ttl}")
                _pause()
            elif choice == "6":
                provider = typer.prompt("Provider (* for any)", default="*").strip()
                model_pattern = typer.prompt("Model pattern", default="*").strip()
                threshold_raw = typer.prompt("Failure threshold (blank for default)", default="").strip()
                ttl_raw = typer.prompt("TTL seconds (blank for default)", default="").strip()
                override = {
                    "provider": None if provider in {"", "*"} else provider,
                    "model_pattern": model_pattern or "*",
                    "failure_threshold": int(threshold_raw) if threshold_raw else None,
                    "ttl_seconds": int(ttl_raw) if ttl_raw else None,
                }
                path = _config_path(config_path)
                data = _load_yaml(path)
                overrides = data.setdefault("routing", {}).setdefault("model_quarantine", {}).setdefault(
                    "overrides",
                    [],
                )
                if not isinstance(overrides, list):
                    raise typer.BadParameter("routing.model_quarantine.overrides must be a list")
                overrides.append(override)
                _save_yaml(path, data)
                console.print("Added model quarantine override")
                _pause()
            elif choice == "7":
                cfg = load_gateway_config(config_path=config_path)
                _show_model_quarantine_settings(config_path)
                if not cfg.routing.model_quarantine.overrides:
                    _pause()
                    continue
                index = _prompt_numbered_choice(len(cfg.routing.model_quarantine.overrides), "Override number")
                path = _config_path(config_path)
                data = _load_yaml(path)
                overrides = data.setdefault("routing", {}).setdefault("model_quarantine", {}).setdefault(
                    "overrides",
                    [],
                )
                if not isinstance(overrides, list):
                    raise typer.BadParameter("routing.model_quarantine.overrides must be a list")
                removed = overrides.pop(index - 1)
                _save_yaml(path, data)
                console.print(f"Removed override: {removed}")
                _pause()
            elif choice == "8":
                cfg = load_gateway_config(config_path=config_path)
                provider = typer.prompt("Provider (blank for all)", default="").strip() or None
                model = typer.prompt("Model id (blank for all)", default="").strip() or None
                count = _model_runtime_repo(cfg).reset(provider=provider, model=model)
                console.print(f"Reset model quarantine rows: {count}")
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_settings_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Settings",
            config_path=config_path,
            lines=[
                "1) Show current settings",
                "2) Set server host",
                "3) Set server port",
                "4) Set request timeout",
                "5) Set stream timeout",
                "6) Set max attempts per candidate",
                "7) Toggle startup health check",
                "8) Toggle request logging",
                "9) Toggle router decision logging",
                "10) Model capability settings",
                "11) Alias chain settings",
                "12) Provider settings",
                "13) Inventory refresh schedule",
                "14) Model quarantine settings",
                "15) Reload config in running app",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                _show_settings_summary(config_path)
                _pause()
            elif choice == "2":
                cfg = load_gateway_config(config_path=config_path)
                value = typer.prompt("server.host", default=str(cfg.server.host)).strip()
                _update_config_value(config_path, value, "server", "host")
                console.print(f"Updated server.host: {value}")
                _pause()
            elif choice == "3":
                cfg = load_gateway_config(config_path=config_path)
                value = typer.prompt("server.port", default=str(cfg.server.port)).strip()
                _update_config_value(config_path, int(value), "server", "port")
                console.print(f"Updated server.port: {value}")
                _pause()
            elif choice == "4":
                cfg = load_gateway_config(config_path=config_path)
                value = typer.prompt("server.request_timeout_seconds", default=str(cfg.server.request_timeout_seconds)).strip()
                _update_config_value(config_path, int(value), "server", "request_timeout_seconds")
                console.print(f"Updated server.request_timeout_seconds: {value}")
                _pause()
            elif choice == "5":
                cfg = load_gateway_config(config_path=config_path)
                value = typer.prompt("server.stream_timeout_seconds", default=str(cfg.server.stream_timeout_seconds)).strip()
                _update_config_value(config_path, int(value), "server", "stream_timeout_seconds")
                console.print(f"Updated server.stream_timeout_seconds: {value}")
                _pause()
            elif choice == "6":
                cfg = load_gateway_config(config_path=config_path)
                value = typer.prompt(
                    "routing.retry.max_attempts_per_candidate",
                    default=str(cfg.routing.retry.max_attempts_per_candidate),
                ).strip()
                _update_config_value(config_path, int(value), "routing", "retry", "max_attempts_per_candidate")
                console.print(f"Updated routing.retry.max_attempts_per_candidate: {value}")
                _pause()
            elif choice == "7":
                cfg = load_gateway_config(config_path=config_path)
                value = typer.confirm("Enable startup health check", default=cfg.health.startup_check)
                _update_config_value(config_path, value, "health", "startup_check")
                console.print(f"Updated health.startup_check: {value}")
                _pause()
            elif choice == "8":
                cfg = load_gateway_config(config_path=config_path)
                value = typer.confirm("Enable request logging", default=cfg.observability.request_log)
                _update_config_value(config_path, value, "observability", "request_log")
                console.print(f"Updated observability.request_log: {value}")
                _pause()
            elif choice == "9":
                cfg = load_gateway_config(config_path=config_path)
                value = typer.confirm("Enable router decision logging", default=cfg.observability.router_decision_log)
                _update_config_value(config_path, value, "observability", "router_decision_log")
                console.print(f"Updated observability.router_decision_log: {value}")
                _pause()
            elif choice == "10":
                _run_capabilities_panel(config_path=config_path)
            elif choice == "11":
                _run_alias_settings_panel(config_path=config_path)
            elif choice == "12":
                _run_provider_settings_panel(config_path=config_path)
            elif choice == "13":
                _run_inventory_schedule_panel(config_path=config_path)
            elif choice == "14":
                _run_model_quarantine_panel(config_path=config_path)
            elif choice == "15":
                config_reload(config_path=config_path)
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_gateway_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Gateway",
            config_path=config_path,
            lines=[
                "1) Setup summary (API URL)",
                "2) API access token and test",
                "3) Route preview",
                "4) Doctor report",
                "5) Show runtime stats",
                "6) Troubleshooting guide",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                cfg = load_gateway_config(config_path=config_path)
                _print_setup_summary(config_path=config_path, cfg=cfg)
                _pause()
            elif choice == "2":
                _run_api_access_panel(config_path=config_path)
            elif choice == "3":
                _print_route_preview(config_path=config_path)
                _pause()
            elif choice == "4":
                doctor(config_path=config_path)
                _pause()
            elif choice == "5":
                stats(config_path=config_path)
                _pause()
            elif choice == "6":
                _print_troubleshooting_guide()
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_api_access_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Gateway Access",
            config_path=config_path,
            lines=[
                "1) Show connection details",
                "2) Regenerate API access token",
                "3) Test API request automatically",
                "4) Show OpenAI-compatible examples",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                _print_api_access(config_path=config_path)
                _pause()
            elif choice == "2":
                restart_now = typer.confirm("Restart system service after token regeneration", default=False)
                _regenerate_master_api_key(restart_service=restart_now)
                _pause()
            elif choice == "3":
                _run_interactive_api_test(config_path=config_path)
                _pause()
            elif choice == "4":
                _print_openai_client_examples(config_path=config_path)
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_quick_setup_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Quick Setup",
            config_path=config_path,
            lines=[
                "1) Show connection guide",
                "2) Run setup wizard",
                "3) Test gateway now",
                "4) Show current status",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                cfg = load_gateway_config(config_path=config_path)
                _print_setup_summary(config_path=config_path, cfg=cfg)
                _pause()
            elif choice == "2":
                _run_setup_wizard(config_path=config_path)
                _pause()
            elif choice == "3":
                _run_interactive_api_test(config_path=config_path)
                _pause()
            elif choice == "4":
                _print_quick_status(config_path=config_path)
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_route_preview_panel(config_path: str) -> None:
    cfg = load_gateway_config(config_path=config_path)
    snapshot = _current_inventory_snapshot(config_path, refresh=False)
    preferred_aliases = ("auto/fast", "auto/general", "auto/reasoning", "auto/code", "auto/free")
    available_aliases = set(_generated_alias_ids(snapshot) or list(cfg.routes.aliases))
    alias_options = [alias for alias in preferred_aliases if alias in available_aliases]
    while True:
        lines = [f"{index}) Preview {alias}" for index, alias in enumerate(alias_options, start=1)]
        custom_option = len(alias_options) + 1
        lines.extend([f"{custom_option}) Preview custom model or alias", "0) Back"])
        _print_menu(
            title="SimpleOpenRoad / Routing and Models / Route Preview",
            config_path=config_path,
            lines=lines,
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "0":
                return
            selected = int(choice)
            if 1 <= selected <= len(alias_options):
                _print_route_preview(config_path=config_path, model=alias_options[selected - 1])
                _pause()
            elif selected == custom_option:
                model = typer.prompt("Model or alias", default=_recommended_model_alias(cfg, snapshot)).strip()
                _print_route_preview(config_path=config_path, model=model)
                _pause()
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_routing_models_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Routing and Models",
            config_path=config_path,
            lines=[
                "1) Route preview",
                "2) Show model aliases",
                "3) Edit alias chains",
                "4) Edit model capabilities",
                "5) Test selected route",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                _run_route_preview_panel(config_path=config_path)
            elif choice == "2":
                cfg = load_gateway_config(config_path=config_path)
                snapshot = _current_inventory_snapshot(config_path, refresh=False)
                _print_alias_help_table(cfg, snapshot)
                routes_list(config_path=config_path)
                _pause()
            elif choice == "3":
                _run_alias_settings_panel(config_path=config_path)
            elif choice == "4":
                _run_capabilities_panel(config_path=config_path)
            elif choice == "5":
                _run_interactive_api_test(config_path=config_path)
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_diagnostics_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Diagnostics",
            config_path=config_path,
            lines=[
                "1) Doctor report",
                "2) Automatic API test",
                "3) Route preview",
                "4) Show runtime stats",
                "5) Show service logs",
                "6) Key consistency",
                "7) Troubleshooting guide",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                doctor(config_path=config_path)
                _pause()
            elif choice == "2":
                _run_interactive_api_test(config_path=config_path)
                _pause()
            elif choice == "3":
                _run_route_preview_panel(config_path=config_path)
            elif choice == "4":
                stats(config_path=config_path)
                _pause()
            elif choice == "5":
                service_logs(mode="system", lines=100)
                _pause()
            elif choice == "6":
                providers_consistency(config_path=config_path)
                _pause()
            elif choice == "7":
                _print_troubleshooting_guide()
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_keys_view_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Providers and Keys / View",
            config_path=config_path,
            lines=[
                "1) List providers with configured keys",
                "2) List configured keys",
                "3) List all keys including placeholders",
                "4) List full provider catalog",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                providers_list(config_path=config_path, all_providers=False)
                _pause()
            elif choice == "2":
                keys_list(config_path=config_path, all_keys=False)
                _pause()
            elif choice == "3":
                keys_list(config_path=config_path, all_keys=True)
                _pause()
            elif choice == "4":
                providers_list(config_path=config_path, all_providers=True)
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_gemini_cli_oauth_wizard(config_path: str) -> None:
    config_file = _config_path(config_path)
    data = _load_yaml(config_file)
    providers = data.setdefault("providers", {})
    google_provider = providers.get("google_code_assist", {})
    existing_keys = google_provider.get("keys", []) if isinstance(google_provider, dict) else []
    existing_count = len(existing_keys) if isinstance(existing_keys, list) else 0

    default_profile = "main" if existing_count == 0 else f"account-{existing_count + 1}"
    console.print("Gemini CLI OAuth supports multiple Google accounts by using separate local profiles.")
    console.print("Each profile creates a separate provider key under google_code_assist.")
    console.print("Local profile is only a local SimpleOpenRoad slot name, not your Google email or password.")
    console.print("Examples: main, personal, work, team-1.")
    profile = typer.prompt("Local profile", default=default_profile).strip()
    if not profile:
        raise typer.BadParameter("Local profile cannot be empty")

    default_key_id = "google-ai-pro-main" if profile == "main" else f"google-ai-pro-{profile}"
    console.print("Key ID is the local provider key name shown in logs, validation, routing, and key management.")
    console.print("Use a unique readable value. Examples: google-ai-pro-main, google-ai-pro-work.")
    key_id = _prompt_unique_key_id(providers, "google_code_assist", default_key_id, prompt_label="Key ID")

    cfg = load_gateway_config(config_path=config_path)
    credentials_base = Path(cfg.storage.sqlite_path).parent / "credentials"
    auth_home = _gemini_cli_profile_home(credentials_base, profile)
    source_path = _gemini_cli_profile_source_path(auth_home)
    existing_profile_credentials = _gemini_cli_credentials_exist(source_path, auth_home=auth_home)
    console.print(f"Credentials for this profile are stored under: {auth_home}")
    console.print("The Google sign-in opens in the official Gemini CLI flow; SimpleOpenRoad does not ask for your Google password.")
    force_login = typer.confirm(
        "Start Google sign-in for this profile now" if not existing_profile_credentials else "Replace existing Google sign-in for this profile",
        default=not existing_profile_credentials,
    )

    providers_connect(
        provider="google",
        profile=profile,
        key_id=key_id,
        gemini_cli_credentials_path=None,
        force_gemini_login=force_login,
        google_cloud_project=None,
        config_path=config_path,
        validate=True,
    )


def _run_keys_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Providers and Keys",
            config_path=config_path,
            lines=[
                "1) Add provider key (wizard)",
                "2) Connect Gemini CLI OAuth",
                "3) View providers and keys",
                "4) Validate keys",
                "5) Manage existing key",
                "6) Clean unconfigured placeholder keys",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                _interactive_add_provider_key(config_path=config_path)
                _pause()
            elif choice == "2":
                _run_gemini_cli_oauth_wizard(config_path=config_path)
                _pause()
            elif choice == "3":
                _run_keys_view_panel(config_path=config_path)
            elif choice == "4":
                keys_validate(provider=None, key_id=None, config_path=config_path)
                _pause()
            elif choice == "5":
                _run_manage_existing_key_panel(config_path=config_path)
            elif choice == "6":
                removed = _remove_unconfigured_provider_keys(config_path=config_path)
                console.print(f"Removed unconfigured placeholder keys: {removed}")
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_service_panel(config_path: str) -> bool:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Service and Updates",
            config_path=config_path,
            lines=[
                "1) Service status",
                "2) Start service",
                "3) Restart service",
                "4) Stop service",
                "5) Update SimpleOpenRoad",
                "6) Install or repair service",
                "7) Install diagnostics",
                "8) Uninstall",
                "9) Advanced settings",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                service_status(mode="system")
                _pause()
            elif choice == "2":
                service_start(mode="system")
                _pause()
            elif choice == "3":
                service_restart(mode="system")
                _pause()
            elif choice == "4":
                service_stop(mode="system")
                _pause()
            elif choice == "5":
                if _run_update_panel(config_path=config_path):
                    return True
            elif choice == "6":
                service_install(config_path=config_path, mode="system", run_as=None, start=True)
                _pause()
            elif choice == "7":
                _print_install_diagnostics(config_path=config_path)
                _pause()
            elif choice == "8":
                if _run_uninstall_panel(config_path=config_path):
                    return True
            elif choice == "9":
                _run_settings_panel(config_path=config_path)
            elif choice == "0":
                return False
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_update_panel(config_path: str) -> bool:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Service and Updates / Update",
            config_path=config_path,
            lines=[
                "1) Update to latest stable",
                "2) Update to latest prerelease",
                "3) Reinstall current version",
                "4) Update from main branch",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                _run_update(config_path=config_path, channel="stable", yes=False)
                console.print("Current panel is closing. Start a fresh panel with: sor")
                return True
            elif choice == "2":
                _run_update(config_path=config_path, channel="prerelease", yes=False)
                console.print("Current panel is closing. Start a fresh panel with: sor")
                return True
            elif choice == "3":
                install_root = _detect_wrapper_install_root() or _guess_install_root(config_path)
                current_version = _read_installed_version(install_root)
                if current_version == "unknown":
                    console.print("Current installed version is unknown. Use latest stable or prerelease instead.")
                    _pause()
                else:
                    _run_update(
                        config_path=config_path,
                        version=f"v{current_version.lstrip('v')}",
                        install_dir=str(install_root),
                        yes=False,
                    )
                    console.print("Current panel is closing. Start a fresh panel with: sor")
                    return True
            elif choice == "4":
                _run_update(config_path=config_path, ref="main", yes=False)
                console.print("Current panel is closing. Start a fresh panel with: sor")
                return True
            elif choice == "0":
                return False
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_uninstall_panel(config_path: str) -> bool:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Service and Updates / Uninstall",
            config_path=config_path,
            lines=[
                "1) Remove service only",
                "2) Full uninstall package",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                uninstall(config_path=config_path, mode="system", purge_data=False, remove_config=False)
                _pause()
            elif choice == "2":
                uninstall(config_path=config_path, mode="system", full=True, yes=False)
                return True
            elif choice == "0":
                return False
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_maintenance_panel(config_path: str) -> bool:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Maintenance",
            config_path=config_path,
            lines=[
                "1) Uninstall service only",
                "2) Full uninstall package",
                "0) Back",
            ],
        )
        choice = _prompt_menu_choice()
        try:
            if choice == "1":
                uninstall(config_path=config_path, mode="system", purge_data=False, remove_config=False)
                _pause()
            elif choice == "2":
                uninstall(config_path=config_path, mode="system", full=True, yes=False)
                return True
            elif choice == "0":
                return False
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_management_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad Management Terminal",
            config_path=config_path,
            lines=[
                "1) Quick setup",
                "2) Providers and keys",
                "3) Gateway access",
                "4) Routing and models",
                "5) Diagnostics",
                "6) Service and updates",
                "0) Exit",
            ],
        )
        choice = _prompt_menu_choice("Select section")

        if choice == "1":
            _run_quick_setup_panel(config_path=config_path)
        elif choice == "2":
            _run_keys_panel(config_path=config_path)
        elif choice == "3":
            _run_api_access_panel(config_path=config_path)
        elif choice == "4":
            _run_routing_models_panel(config_path=config_path)
        elif choice == "5":
            _run_diagnostics_panel(config_path=config_path)
        elif choice == "6":
            if _run_service_panel(config_path=config_path):
                return
        elif choice == "0":
            return
        else:
            console.print("Unknown section")
            _pause()


@cli_app.command("panel")
def panel(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    _run_management_panel(config_path=config_path)


@cli_app.command("menu")
def menu(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    _run_management_panel(config_path=config_path)
