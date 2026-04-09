"""Typer-based CLI for gateway administration."""

from __future__ import annotations

import ipaddress
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
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import typer
import uvicorn
import yaml
from rich.console import Console
from rich.table import Table

from app.config.loader import load_gateway_config
from app.config.models import GatewayConfig
from app.container import AppContainer
from app.core.errors import ConfigError
from app.core.utils import mask_secret

cli_app = typer.Typer(help="SimpleOpenRoad AI gateway CLI")
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
_PLACEHOLDER_ENV_VALUES = {
    "change-me-master-key",
    "change-me-admin-key",
    "",
}


def _config_path(value: str | None) -> Path:
    return Path(value or "config/config.yaml")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise typer.BadParameter(f"Config file does not exist: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise typer.BadParameter("Config root must be YAML mapping")
    return data


def _save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")


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


def _print_setup_summary(config_path: str, cfg: GatewayConfig) -> None:
    api_base = _resolve_api_base_url(cfg)
    console.print("Setup complete. Management and API endpoints:")
    console.print(f"- CLI: sor doctor --config-path {config_path}")
    console.print(f"- API base: {api_base}")
    console.print(f"- Chat: {api_base}/v1/chat/completions")
    console.print(f"- Health: {api_base}/health")


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


def _run_systemctl(mode: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [*_systemctl_base(mode), *args]
    return _run_command(command, check=check)


def _service_exec_start(config_path: str) -> str:
    sor_executable = shutil.which("sor")
    if sor_executable is None:
        raise typer.BadParameter("sor executable was not found in PATH")
    quoted_exec = shlex.quote(str(Path(sor_executable).resolve()))
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


def _guess_install_root(config_path: str) -> Path:
    cfg_path = Path(config_path).resolve()
    if cfg_path.parent.name == "config":
        return cfg_path.parent.parent
    return cfg_path.parent


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


def _interactive_add_provider_key(config_path: str) -> None:
    path = _config_path(config_path)
    data = _load_yaml(path)
    providers = data.get("providers", {})
    if not isinstance(providers, dict) or not providers:
        raise typer.BadParameter("No providers configured. Add providers in config first.")

    provider_names = sorted(str(name) for name in providers.keys())
    console.print("Available providers:")
    for idx, provider in enumerate(provider_names, start=1):
        console.print(f"{idx}) {provider}")

    raw_choice = typer.prompt("Select provider", default="1").strip()
    if not raw_choice.isdigit():
        raise typer.BadParameter("Provider selection must be a number")
    selected_index = int(raw_choice)
    if selected_index < 1 or selected_index > len(provider_names):
        raise typer.BadParameter("Selected provider index is out of range")
    provider = provider_names[selected_index - 1]

    existing_keys = providers.get(provider, {}).get("keys", [])
    default_key_id = f"{provider}-key-{len(existing_keys) + 1}"
    key_id = typer.prompt("Key ID", default=default_key_id).strip()
    if not key_id:
        raise typer.BadParameter("Key ID cannot be empty")

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
        priority=priority,
        config_path=config_path,
        validate=validate_now,
    )


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
def providers_list(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    container = _container(config_path)
    rows = container.admin_service.list_providers()
    table = Table(title="Providers")
    table.add_column("Name")
    table.add_column("Enabled")
    table.add_column("Priority")
    table.add_column("Endpoint")
    table.add_column("Keys")
    for row in rows:
        table.add_row(
            str(row["name"]),
            str(row["enabled"]),
            str(row["priority"]),
            str(row["endpoint"]),
            str(row["keys_count"]),
        )
    console.print(table)


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
    table.add_column("Error")
    for row in results:
        table.add_row(
            str(row.get("provider")),
            str(row.get("key_id")),
            str(row.get("status")),
            f"{float(row.get('latency_ms', 0.0)):.2f}",
            str(row.get("error_code") or ""),
        )
    console.print(table)


@keys_app.command("list")
def keys_list(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    container = _container(config_path)
    rows = container.admin_service.list_keys()
    table = Table(title="Keys")
    table.add_column("Provider")
    table.add_column("ID")
    table.add_column("Active")
    table.add_column("Status")
    table.add_column("Priority")
    table.add_column("Errors")
    table.add_column("Last Error")
    for row in rows:
        table.add_row(
            str(row["provider"]),
            str(row["id"]),
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

    keys.append(
        {
            "id": key_id,
            "key": secret,
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
        console.print(result)


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
        console.print(result)
        return

    results = asyncio.run(container.admin_service.validate_all_keys())
    for row in results:
        console.print(row)


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
    table = Table(title="Route Aliases")
    table.add_column("Alias")
    table.add_column("Strategy")
    table.add_column("Candidates")
    for alias, route in cfg.routes.aliases.items():
        candidates = " -> ".join(f"{c.provider}/{c.model}" for c in route.candidates)
        table.add_row(alias, route.strategy, candidates)
    console.print(table)


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


@cli_app.command("uninstall")
def uninstall(
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
    mode: str = typer.Option("system", help="Service mode: system or user"),
    purge_data: bool = typer.Option(False, help="Remove SQLite runtime database files"),
    remove_config: bool = typer.Option(False, help="Remove config file"),
) -> None:
    selected_mode = _service_mode(mode)
    cfg = load_gateway_config(config_path=config_path)

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

    if not service_cleaned and not purge_data and not remove_config:
        console.print("Nothing to remove.")
        return

    console.print("Uninstall complete.")


@service_app.command("install")
def service_install(
    config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml"),
    mode: str = typer.Option("system", help="Install mode: system or user"),
    run_as: str | None = typer.Option(None, help="Linux user for system mode service"),
    start: bool = typer.Option(True, help="Start service right after install"),
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


@cli_app.command("panel")
def panel(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    console.print("SimpleOpenRoad Service Panel")
    while True:
        console.print("1) Install system service")
        console.print("2) Start service")
        console.print("3) Stop service")
        console.print("4) Restart service")
        console.print("5) Service status")
        console.print("6) Show service logs")
        console.print("7) Setup summary (API URL)")
        console.print("8) Uninstall service")
        console.print("9) Exit")
        choice = typer.prompt("Select option", default="5").strip()

        try:
            if choice == "1":
                service_install(config_path=config_path, mode="system", run_as=None, start=True)
            elif choice == "2":
                service_start(mode="system")
            elif choice == "3":
                service_stop(mode="system")
            elif choice == "4":
                service_restart(mode="system")
            elif choice == "5":
                service_status(mode="system")
            elif choice == "6":
                service_logs(mode="system", lines=100)
            elif choice == "7":
                cfg = load_gateway_config(config_path=config_path)
                _print_setup_summary(config_path=config_path, cfg=cfg)
            elif choice == "8":
                uninstall(config_path=config_path, mode="system", purge_data=False, remove_config=False)
            elif choice == "9":
                return
            else:
                console.print("Unknown option")
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")


@cli_app.command("menu")
def menu(config_path: str = typer.Option("config/config.yaml", help="Path to config.yaml")) -> None:
    console.print("Interactive menu")
    console.print("1) Add provider key (wizard)")
    console.print("2) Validate all keys")
    console.print("3) List keys")
    choice = typer.prompt("Select option", default="3")

    if choice == "1":
        _interactive_add_provider_key(config_path=config_path)
        return

    if choice == "2":
        keys_validate(provider=None, key_id=None, config_path=config_path)
        return

    keys_list(config_path=config_path)
