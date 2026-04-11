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

import httpx
import typer
import uvicorn
import yaml
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.config.loader import load_gateway_config
from app.config.models import GatewayConfig
from app.container import AppContainer
from app.core.errors import ConfigError
from app.core.security import is_configured_secret
from app.core.utils import mask_secret

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
_PLACEHOLDER_ENV_VALUES = {
    "change-me-master-key",
    "change-me-admin-key",
    "",
}


@cli_app.callback()
def cli_entrypoint(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _run_management_panel(config_path="config/config.yaml")


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


def _format_model_aliases(cfg: GatewayConfig) -> str:
    aliases = list(cfg.routes.aliases)
    return ", ".join(aliases) if aliases else "<no aliases configured>"


def _recommended_model_alias(cfg: GatewayConfig) -> str:
    aliases = cfg.routes.aliases
    if "auto/smart" in aliases:
        return "auto/smart"
    if "auto/fast" in aliases:
        return "auto/fast"
    return next(iter(aliases), "<no aliases configured>")


def _model_alias_help_rows(cfg: GatewayConfig) -> list[tuple[str, str]]:
    descriptions = {
        "auto/smart": "recommended default; local heuristic chooses fast/balanced/strong/code candidates",
        "auto/fast": "lightweight, cheap, low-latency tasks",
        "auto/balanced": "general chat and medium tasks with better quality",
        "auto/strong": "hard reasoning, long context, complex analysis",
        "auto/code": "coding, debugging, refactoring, repository work",
    }
    rows: list[tuple[str, str]] = []
    for alias in cfg.routes.aliases:
        rows.append((alias, descriptions.get(alias, "custom route alias from config.yaml")))
    return rows


def _print_alias_help_table(cfg: GatewayConfig) -> None:
    table = Table(title="Model Alias Guide", box=box.ASCII)
    table.add_column("Alias")
    table.add_column("Use for")
    for alias, description in _model_alias_help_rows(cfg):
        table.add_row(alias, description)
    console.print(table)


def _print_setup_summary(config_path: str, cfg: GatewayConfig) -> None:
    api_base = _resolve_api_base_url(cfg)
    openai_base = f"{api_base}/v1"
    console.print("Setup complete. Management and API endpoints:")
    console.print(f"- CLI: sor doctor --config-path {config_path}")
    console.print("- OpenAI-compatible plugin settings:")
    console.print(f"  Base URL: {openai_base}")
    console.print("  API key: MASTER_API_KEY from .env or Gateway -> API access token and test")
    console.print(f"  Models: {_format_model_aliases(cfg)}")
    console.print(f"  Recommended default: {_recommended_model_alias(cfg)}")
    console.print("  Direct model format: provider/model or exact model id")
    console.print("  Alias fallback: candidates are tried in order; providers without keys are skipped")
    console.print(f"- Chat endpoint: {openai_base}/chat/completions")
    console.print(f"- Responses endpoint: {openai_base}/responses")
    console.print(f"- Health: {api_base}/health")
    _print_alias_help_table(cfg)


def _resolve_local_api_base_url(cfg: GatewayConfig) -> str:
    host = str(cfg.server.host).strip().lower()
    if host in {"", "0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    return f"http://{host}:{cfg.server.port}"


def _current_master_api_key() -> str:
    created_env, generated_keys = _ensure_env_master_admin_keys()
    _print_env_setup_hint(created_env=created_env, generated_keys=generated_keys)
    return os.getenv("MASTER_API_KEY") or _load_env_file().get("MASTER_API_KEY", "")


def _print_api_access(config_path: str) -> None:
    cfg = load_gateway_config(config_path=config_path)
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
    table.add_row("Model aliases", _format_model_aliases(cfg))
    table.add_row("Direct model", "provider/model or exact model id")
    table.add_row("MASTER_API_KEY", token if cfg.security.require_master_key else "<not required>")
    table.add_row("Header", "x-api-key: <MASTER_API_KEY>")
    table.add_row("Alt header", "Authorization: Bearer <MASTER_API_KEY>")
    console.print(table)
    _print_alias_help_table(cfg)
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


def _test_api_request(config_path: str) -> None:
    cfg = load_gateway_config(config_path=config_path)
    token = _current_master_api_key()
    api_base = _resolve_local_api_base_url(cfg)
    url = f"{api_base}/v1/chat/completions"
    payload = {
        "model": "auto/fast",
        "messages": [{"role": "user", "content": "hello"}],
    }
    headers = {"Content-Type": "application/json"}
    if cfg.security.require_master_key:
        headers["x-api-key"] = token

    table = Table(title="Automatic API Test")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("URL", url)
    table.add_row("Model", "auto/fast")
    table.add_row("Auth", "x-api-key" if cfg.security.require_master_key else "disabled")
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        table.add_row("HTTP status", str(response.status_code))
        if response.status_code == 200:
            data = response.json()
            text = ""
            choices = data.get("choices", []) if isinstance(data, dict) else []
            if choices:
                text = str(choices[0].get("message", {}).get("content", ""))
            table.add_row("Result", "ok")
            table.add_row("Response", text[:300] or "<empty>")
        else:
            table.add_row("Result", "failed")
            table.add_row("Response", response.text[:500])
    except Exception as exc:  # noqa: BLE001
        table.add_row("Result", "failed")
        table.add_row("Error", str(exc))
    console.print(table)


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
    console.print("Key ID is a local name for this provider key. It is used in logs, stats, health checks and removal commands.")
    console.print("It is not sent to the provider. Example: openrouter-main or gemini-backup-1.")
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


def _run_gateway_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Gateway",
            config_path=config_path,
            lines=[
                "1) Setup summary (API URL)",
                "2) API access token and test",
                "3) Doctor report",
                "4) Show runtime stats",
                "0) Back",
            ],
        )
        choice = typer.prompt("Select option", default="1").strip()
        try:
            if choice == "1":
                cfg = load_gateway_config(config_path=config_path)
                _print_setup_summary(config_path=config_path, cfg=cfg)
                _pause()
            elif choice == "2":
                _run_api_access_panel(config_path=config_path)
            elif choice == "3":
                doctor(config_path=config_path)
                _pause()
            elif choice == "4":
                stats(config_path=config_path)
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
            title="SimpleOpenRoad / API Access",
            config_path=config_path,
            lines=[
                "1) Show API access token",
                "2) Regenerate API access token",
                "3) Test API request automatically",
                "0) Back",
            ],
        )
        choice = typer.prompt("Select option", default="1").strip()
        try:
            if choice == "1":
                _print_api_access(config_path=config_path)
                _pause()
            elif choice == "2":
                restart_now = typer.confirm("Restart system service after token regeneration", default=False)
                _regenerate_master_api_key(restart_service=restart_now)
                _pause()
            elif choice == "3":
                _test_api_request(config_path=config_path)
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_keys_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Providers and Keys",
            config_path=config_path,
            lines=[
                "1) List providers",
                "2) Add provider key (wizard)",
                "3) List keys",
                "4) List keys including placeholders",
                "5) Validate all keys",
                "6) Remove provider key",
                "7) Clean unconfigured placeholder keys",
                "0) Back",
            ],
        )
        choice = typer.prompt("Select option", default="1").strip()
        try:
            if choice == "1":
                providers_list(config_path=config_path)
                _pause()
            elif choice == "2":
                _interactive_add_provider_key(config_path=config_path)
                _pause()
            elif choice == "3":
                keys_list(config_path=config_path, all_keys=False)
                _pause()
            elif choice == "4":
                keys_list(config_path=config_path, all_keys=True)
                _pause()
            elif choice == "5":
                keys_validate(provider=None, key_id=None, config_path=config_path)
                _pause()
            elif choice == "6":
                keys_list(config_path=config_path, all_keys=False)
                key_id = typer.prompt("Key ID to remove").strip()
                if not key_id:
                    console.print("Key ID cannot be empty")
                elif typer.confirm(f"Remove key '{key_id}' from config", default=False):
                    keys_remove(key_id=key_id, config_path=config_path)
                _pause()
            elif choice == "7":
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


def _run_service_panel(config_path: str) -> None:
    while True:
        _print_menu(
            title="SimpleOpenRoad / Service",
            config_path=config_path,
            lines=[
                "1) Update latest release",
                "2) Update from main branch (dev/unreleased)",
                "3) Install diagnostics",
                "4) Install system service",
                "5) Start service",
                "6) Stop service",
                "7) Restart service",
                "8) Service status",
                "9) Show service logs",
                "0) Back",
            ],
        )
        choice = typer.prompt("Select option", default="1").strip()
        try:
            if choice == "1":
                release_channel = _prompt_release_channel(default="stable")
                _run_update(config_path=config_path, channel=release_channel, yes=False)
                _pause()
            elif choice == "2":
                _run_update(config_path=config_path, ref="main", yes=False)
                _pause()
            elif choice == "3":
                _print_install_diagnostics(config_path=config_path)
                _pause()
            elif choice == "4":
                service_install(config_path=config_path, mode="system", run_as=None, start=True)
                _pause()
            elif choice == "5":
                service_start(mode="system")
                _pause()
            elif choice == "6":
                service_stop(mode="system")
                _pause()
            elif choice == "7":
                service_restart(mode="system")
                _pause()
            elif choice == "8":
                service_status(mode="system")
                _pause()
            elif choice == "9":
                service_logs(mode="system", lines=100)
                _pause()
            elif choice == "0":
                return
            else:
                console.print("Unknown option")
                _pause()
        except Exception as exc:  # noqa: BLE001
            console.print(f"Operation failed: {exc}")
            _pause()


def _run_maintenance_panel(config_path: str) -> None:
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
        choice = typer.prompt("Select option", default="1").strip()
        try:
            if choice == "1":
                uninstall(config_path=config_path, mode="system", purge_data=False, remove_config=False)
                _pause()
            elif choice == "2":
                uninstall(config_path=config_path, mode="system", full=True, yes=False)
                _pause()
            elif choice == "0":
                return
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
                "1) Gateway",
                "2) Providers and keys",
                "3) Service",
                "4) Maintenance",
                "0) Exit",
            ],
        )
        choice = typer.prompt("Select section", default="1").strip()

        if choice == "1":
            _run_gateway_panel(config_path=config_path)
        elif choice == "2":
            _run_keys_panel(config_path=config_path)
        elif choice == "3":
            _run_service_panel(config_path=config_path)
        elif choice == "4":
            _run_maintenance_panel(config_path=config_path)
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
