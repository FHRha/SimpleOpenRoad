from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from app.config.loader import load_gateway_config
from app.cli.app import cli_app
from app.cli.app import _ensure_env_master_admin_keys
from app.cli.app import _resolve_api_base_url
from app.cli.app import _service_mode
from app.cli.app import _service_unit_path


def _write_config(tmp_path: Path) -> Path:
    config = {
        "providers": {
            "github": {
                "enabled": True,
                "priority": 20,
                "endpoint": "https://example.invalid",
                "keys": [
                    {"id": "github-main", "key": "k1", "priority": 100},
                ],
            },
            "openrouter": {
                "enabled": True,
                "priority": 30,
                "endpoint": "https://example.invalid",
                "keys": [
                    {"id": "openrouter-main", "key": "k2", "priority": 90},
                ],
            },
        },
        "routes": {
            "aliases": {
                "auto/fast": {
                    "strategy": "strict_priority",
                    "candidates": [
                        {"provider": "github", "model": "gpt-4.1-mini"},
                        {"provider": "openrouter", "model": "gpt-4o-mini"},
                    ],
                }
            }
        },
        "storage": {"sqlite_path": str(tmp_path / "gateway.db")},
        "health": {"startup_check": False},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def test_cli_config_validate(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(cli_app, ["config", "validate", "--config-path", str(config_path)])
    assert result.exit_code == 0
    assert "Config OK" in result.stdout


def test_cli_without_args_opens_management_panel(monkeypatch) -> None:
    runner = CliRunner()
    called: dict[str, str] = {}

    def _fake_panel(config_path: str) -> None:
        called["config_path"] = config_path

    monkeypatch.setattr("app.cli.app._run_management_panel", _fake_panel)

    result = runner.invoke(cli_app, [])

    assert result.exit_code == 0
    assert called["config_path"] == "config/config.yaml"


def test_cli_menu_command_uses_management_panel(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    called: dict[str, str] = {}

    def _fake_panel(config_path: str) -> None:
        called["config_path"] = config_path

    monkeypatch.setattr("app.cli.app._run_management_panel", _fake_panel)

    result = runner.invoke(cli_app, ["menu", "--config-path", str(config_path)])

    assert result.exit_code == 0
    assert called["config_path"] == str(config_path)


def test_cli_routes_set_priority(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        [
            "routes",
            "set-priority",
            "--alias",
            "auto/fast",
            "--candidate",
            "openrouter/gpt-4o-mini",
            "--position",
            "1",
            "--config-path",
            str(config_path),
        ],
    )
    assert result.exit_code == 0

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    first = data["routes"]["aliases"]["auto/fast"]["candidates"][0]
    assert first["provider"] == "openrouter"
    assert first["model"] == "gpt-4o-mini"


def test_cli_keys_add_and_remove(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    add = runner.invoke(
        cli_app,
        [
            "keys",
            "add",
            "--provider",
            "github",
            "--key-id",
            "github-backup",
            "--secret",
            "test-secret",
            "--no-validate",
            "--config-path",
            str(config_path),
        ],
    )
    assert add.exit_code == 0

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    ids = [item["id"] for item in data["providers"]["github"]["keys"]]
    assert "github-backup" in ids

    remove = runner.invoke(
        cli_app,
        [
            "keys",
            "remove",
            "--key-id",
            "github-backup",
            "--config-path",
            str(config_path),
        ],
    )
    assert remove.exit_code == 0

    data_after = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    ids_after = [item["id"] for item in data_after["providers"]["github"]["keys"]]
    assert "github-backup" not in ids_after


def test_api_base_url_prefers_public_domain(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    cfg = load_gateway_config(str(config_path))

    monkeypatch.setenv("APP_PUBLIC_DOMAIN", "api.example.com")
    monkeypatch.delenv("APP_DOMAIN", raising=False)

    assert _resolve_api_base_url(cfg) == "https://api.example.com:12345"


def test_api_base_url_fallbacks_to_detected_ip(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    cfg = load_gateway_config(str(config_path))

    monkeypatch.delenv("APP_PUBLIC_DOMAIN", raising=False)
    monkeypatch.delenv("APP_DOMAIN", raising=False)
    monkeypatch.setattr("app.cli.app._detect_server_ip", lambda: "10.20.30.40")

    assert _resolve_api_base_url(cfg) == "http://10.20.30.40:12345"


def test_service_mode_validation() -> None:
    assert _service_mode("system") == "system"
    assert _service_mode("USER") == "user"


def test_service_unit_path_resolves_user_location() -> None:
    path = _service_unit_path("user")
    normalized = str(path).replace("\\", "/")
    assert normalized.endswith(".config/systemd/user/sor.service")


def test_cli_uninstall_removes_service_unit(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    unit_path = tmp_path / "sor.service"
    unit_path.write_text("[Unit]\nDescription=test\n", encoding="utf-8")

    monkeypatch.setattr("app.cli.app._ensure_systemd_available", lambda: None)
    monkeypatch.setattr("app.cli.app._check_system_mode_permissions", lambda mode: None)
    monkeypatch.setattr("app.cli.app._service_unit_path", lambda mode: unit_path)
    monkeypatch.setattr("app.cli.app._run_systemctl", lambda mode, *args, **kwargs: None)

    result = runner.invoke(
        cli_app,
        [
            "uninstall",
            "--mode",
            "system",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert "Uninstall complete." in result.stdout
    assert not unit_path.exists()


def test_cli_uninstall_purge_data(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    db_path = Path(cfg["storage"]["sqlite_path"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text("x", encoding="utf-8")
    Path(f"{db_path}-wal").write_text("x", encoding="utf-8")
    Path(f"{db_path}-shm").write_text("x", encoding="utf-8")

    monkeypatch.setattr("app.cli.app._ensure_systemd_available", lambda: None)
    monkeypatch.setattr("app.cli.app._check_system_mode_permissions", lambda mode: None)
    monkeypatch.setattr("app.cli.app._service_unit_path", lambda mode: tmp_path / "missing.service")
    monkeypatch.setattr("app.cli.app._run_systemctl", lambda mode, *args, **kwargs: None)

    result = runner.invoke(
        cli_app,
        [
            "uninstall",
            "--mode",
            "system",
            "--purge-data",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert not db_path.exists()
    assert not Path(f"{db_path}-wal").exists()
    assert not Path(f"{db_path}-shm").exists()


def test_first_run_env_key_generation(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MASTER_API_KEY=change-me-master-key\nADMIN_API_KEY=change-me-admin-key\n",
        encoding="utf-8",
    )

    created_env, generated = _ensure_env_master_admin_keys(env_path=env_path, env_example_path=tmp_path / "missing")
    assert created_env is False
    assert sorted(generated) == ["ADMIN_API_KEY", "MASTER_API_KEY"]

    parsed = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key] = value

    assert len(parsed["MASTER_API_KEY"]) == 40
    assert len(parsed["ADMIN_API_KEY"]) == 40
    assert parsed["MASTER_API_KEY"] != "change-me-master-key"
    assert parsed["ADMIN_API_KEY"] != "change-me-admin-key"


def test_keys_wizard_command_dispatch(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    called: dict[str, str] = {}

    def _fake_interactive(config_path: str) -> None:
        called["config_path"] = config_path

    monkeypatch.setattr("app.cli.app._interactive_add_provider_key", _fake_interactive)

    result = runner.invoke(
        cli_app,
        [
            "keys",
            "wizard",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert called["config_path"] == str(config_path)
