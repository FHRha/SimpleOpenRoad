from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from app.config.loader import load_gateway_config
from app.cli.app import cli_app
from app.cli.app import _default_install_root
from app.cli.app import _ensure_env_master_admin_keys
from app.cli.app import _interactive_add_provider_key
from app.cli.app import _model_alias_help_rows
from app.cli.app import _print_setup_summary
from app.cli.app import _resolve_api_base_url
from app.cli.app import _select_test_alias
from app.cli.app import _service_mode
from app.cli.app import _service_unit_path
from app.cli.app import _test_api_request
from app.storage.db import SQLiteDB


def _init_key_state(config_path: Path, key_id: str, provider: str) -> None:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    db = SQLiteDB(data["storage"]["sqlite_path"])
    schema_path = Path(__file__).resolve().parents[2] / "app" / "storage" / "schema.sql"
    db.initialize(str(schema_path))
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO key_runtime_state (
              key_id, provider, active, status, consecutive_errors,
              cooldown_until, last_error_code, last_error_message,
              success_count, failure_count, switch_count, avg_latency_ms
            )
            VALUES (?, ?, 0, 'blocked', 7, '2099-01-01T00:00:00+00:00', 'rate_limit', 'too many', 3, 4, 5, 123.0)
            ON CONFLICT(key_id) DO UPDATE SET
              active = 0,
              status = 'blocked',
              consecutive_errors = 7,
              cooldown_until = '2099-01-01T00:00:00+00:00',
              last_error_code = 'rate_limit',
              last_error_message = 'too many',
              success_count = 3,
              failure_count = 4,
              switch_count = 5,
              avg_latency_ms = 123.0
            """,
            (key_id, provider),
        )


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
                "custom/fast": {
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


def test_install_script_reexecs_from_temp_during_in_place_update() -> None:
    install_script = (Path(__file__).resolve().parents[2] / "install.sh").read_text(
        encoding="utf-8"
    )

    assert "SOR_INSTALL_SELF_REEXEC_DONE" in install_script
    assert "maybe_reexec_from_temp_copy" in install_script
    assert "try_install_supported_python_with_apt" in install_script
    assert "confirm_apt_install" in install_script
    assert "ASSUME_YES=0" in install_script
    assert "--yes|-y)" in install_script
    assert "Install Python and venv packages with apt now?" in install_script
    assert "Install python${version}-venv with apt now?" in install_script
    assert 'apt-get install -y python3 python3-venv' in install_script
    assert 'for candidate in python3.13 python3.12 python3.11' in install_script
    assert "ensure_python_venv_available" in install_script
    assert 'apt-get install -y "python${version}-venv"' in install_script
    assert '"${PYTHON_BIN}" -c' in install_script
    assert "import pip" in install_script
    assert "Existing virtual environment is incomplete or unsupported; recreating" in install_script
    assert "PIP_NO_INPUT=1" in install_script
    assert "Installing package from bundled wheelhouse" in install_script
    assert "--no-index" in install_script
    assert "--find-links" in install_script
    assert "wheelhouse_can_install" in install_script
    assert "--dry-run" in install_script
    assert "Bundled wheelhouse is incomplete or incompatible; installing with PyPI fallback" in install_script
    assert "Bundled wheelhouse not found; installing dependencies from PyPI" in install_script
    assert "--prefer-binary -e" in install_script
    assert 'exec env SOR_INSTALL_SELF_REEXEC_DONE=1 bash "${temp_script}" "${ORIGINAL_ARGS[@]}"' in install_script


def test_release_build_script_bundles_wheelhouse() -> None:
    build_script = (Path(__file__).resolve().parents[2] / "scripts" / "build_linux_release.sh").read_text(
        encoding="utf-8"
    )

    assert "Building offline wheelhouse" in build_script
    assert 'pip wheel --wheel-dir "${STAGE_DIR}/wheelhouse" "${ROOT_DIR}"' in build_script
    assert "Verifying offline wheelhouse" in build_script
    assert "--no-index" in build_script


def test_package_includes_storage_schema() -> None:
    pyproject = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.setuptools.package-data]" in pyproject
    assert '"app.storage" = ["schema.sql"]' in pyproject


def test_built_wheel_contains_runtime_files(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    wheel_dir = tmp_path / "wheelhouse"
    wheel_dir.mkdir()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
            str(root),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(wheel_dir.glob("simple_open_road-*.whl"))
    assert wheels

    with ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())

    for required in [
        "app/cli/app.py",
        "app/container.py",
        "app/storage/schema.sql",
        "app/storage/repositories/keys_repo.py",
        "app/registry/keys.py",
        "app/router/engine.py",
        "app/providers/gemini.py",
        "app/providers/openai_compatible.py",
    ]:
        assert required in names


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


def test_cli_providers_inventory_uses_cached_snapshot(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    class _FakeAdminService:
        def current_inventory(self) -> dict:
            return {
                "refreshed_at": "2026-04-14T00:00:00+00:00",
                "key_results": [
                    {
                        "provider": "gemini",
                        "key_id": "gemini-main",
                        "status": "valid",
                        "discovered_models": 2,
                        "error_code": None,
                    }
                ],
                "special_routes": [
                    {
                        "provider": "openrouter",
                        "route_id": "openrouter/free",
                        "modality": "text",
                        "supports_tools": False,
                        "category_hints": ["free"],
                    }
                ],
                "classifications": [
                    {
                        "provider": "gemini",
                        "model_id": "gemini-2.5-flash",
                        "classification_tags": ["fast", "general"],
                        "free_score": 0,
                        "fast_score": 30,
                        "general_score": 35,
                        "reasoning_score": 0,
                        "code_score": 0,
                    }
                ],
                "generated_aliases": [
                    {
                        "alias_id": "gemini/text/fast",
                        "modality": "text",
                        "scope": "provider",
                        "category": "fast",
                        "candidates": [
                            {
                                "provider": "gemini",
                                "model_id": "gemini-2.5-flash",
                                "candidate_type": "model",
                            }
                        ],
                    },
                    {
                        "alias_id": "auto/text/fast",
                        "modality": "text",
                        "scope": "global",
                        "category": "fast",
                        "candidates": [
                            {
                                "provider": "gemini",
                                "model_id": "gemini-2.5-flash",
                                "candidate_type": "model",
                            }
                        ],
                    },
                    {
                        "alias_id": "auto/image/default",
                        "modality": "image",
                        "scope": "global",
                        "category": "default",
                        "candidates": [
                            {
                                "provider": "gemini",
                                "model_id": "imagen-4.0-generate-001",
                                "candidate_type": "model",
                            }
                        ],
                    },
                ],
                "models": [
                    {
                        "provider": "gemini",
                        "model_id": "gemini-2.5-flash",
                        "modality": "text",
                        "source_key_ids": ["gemini-main"],
                        "is_free": False,
                        "is_preview": False,
                        "is_special": False,
                        "is_text_candidate": True,
                        "chat_state": "supported",
                        "responses_state": "supported",
                        "stream_state": "supported",
                        "tools_state": "unknown",
                        "excluded_reason": None,
                    }
                ],
            }

    class _FakeContainer:
        admin_service = _FakeAdminService()

    monkeypatch.setattr("app.cli.app._container", lambda config_path: _FakeContainer())

    result = runner.invoke(cli_app, ["providers", "inventory", "--config-path", str(config_path), "--cached"])

    assert result.exit_code == 0
    assert "Provider Inventory / Keys" in result.stdout
    assert "Provider Inventory / Models" in result.stdout
    assert "Provider Inventory / Special Routes" in result.stdout
    assert "Provider Inventory / Generated Aliases" in result.stdout
    assert "gemini-main" in result.stdout
    assert "openrouter/free" in result.stdout
    assert "text" in result.stdout
    assert "image" in result.stdout
    assert "fast" in result.stdout or "general" in result.stdout


def test_cli_panel_accepts_zero_exit() -> None:
    runner = CliRunner()

    result = runner.invoke(cli_app, ["panel"], input="0\n")

    assert result.exit_code == 0
    assert "SimpleOpenRoad Management Terminal" in result.stdout


def test_cli_settings_section_updates_tool_capabilities(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="6\n9\n10\n2\n2\ncustomtools\n\n3\n1\n\n0\n3\n2\nflash-lite\n\n3\n1\n\n0\n0\n0\n0\n",
    )

    assert result.exit_code == 0
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert "customtools" in data["model_capabilities"]["tool_capable"]
    assert "codex" not in data["model_capabilities"]["tool_capable"]
    assert "flash-lite" in data["model_capabilities"]["tool_disabled"]
    assert "gemini-2.5-flash" not in data["model_capabilities"]["tool_disabled"]


def test_cli_settings_section_can_add_and_remove_inventory_override(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="6\n9\n10\n5\n2\nopenrouter\nopenai/*codex*\ny\nn\nskip\ncode\ntrue\nskip\npromote codex\n\n3\n1\n\n0\n0\n0\n0\n",
    )

    assert result.exit_code == 0
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data.get("inventory", {}).get("overrides", []) == []


def test_cli_settings_section_updates_inventory_refresh_schedule(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="6\n9\n13\n1\n04:30\n\n2\nUTC\n\n3\n12\n\n0\n0\n0\n",
    )

    assert result.exit_code == 0
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["inventory"]["refresh_time"] == "04:30"
    assert data["inventory"]["refresh_timezone"] == "UTC"
    assert data["inventory"]["refresh_interval_hours"] == 12


def test_cli_settings_alias_editor_adds_candidate_by_numbers(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="4\n3\n2\n1\n2\n2\ngpt-5.4-mini\n1\n\n0\n0\n0\n",
    )

    assert result.exit_code == 0
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    first = data["routes"]["aliases"]["custom/fast"]["candidates"][0]
    assert first["provider"] == "openrouter"
    assert first["model"] == "gpt-5.4-mini"


def test_cli_settings_alias_editor_updates_strategy_and_selection(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="4\n3\n3\n1\n2\n\n4\n1\n2\n\n0\n0\n",
    )

    assert result.exit_code == 0
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    alias_cfg = data["routes"]["aliases"]["custom/fast"]
    assert alias_cfg["strategy"] == "least_errors"
    assert alias_cfg["selection"] == "adaptive"


def test_cli_settings_provider_editor_updates_provider_values(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="6\n9\n12\n2\n2\n55\n\n3\n2\n88\n\n0\n0\n0\n",
    )

    assert result.exit_code == 0
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["providers"]["openrouter"]["priority"] == 55
    assert data["providers"]["openrouter"]["timeout_seconds"] == 88


def test_cli_keys_panel_updates_key_values(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="2\n4\n2\n1\n3\n4\n90\n\n0\n0\n0\n",
    )

    assert result.exit_code == 0
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    key_cfg = data["providers"]["openrouter"]["keys"][0]
    assert key_cfg["cooldown"]["rate_limit_seconds"] == 90


def test_cli_keys_panel_can_toggle_rename_and_remove_key(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="2\n4\n2\n1\n4\n\n5\nopenrouter-renamed\n\n6\ny\n\n0\n0\n",
    )

    assert result.exit_code == 0
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    openrouter_keys = data["providers"]["openrouter"]["keys"]
    assert openrouter_keys == []


def test_cli_keys_panel_can_replace_key_value(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    monkeypatch.setattr("app.cli.app.keys_validate", lambda provider, key_id, config_path: None)

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="2\n4\n2\n1\n2\nnew-secret\nnew-secret\nn\n\n0\n0\n",
    )

    assert result.exit_code == 0
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    key_cfg = data["providers"]["openrouter"]["keys"][0]
    assert key_cfg["key"] == "new-secret"
    assert key_cfg["active"] is True


def test_cli_keys_panel_can_reset_runtime_state(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    _init_key_state(config_path, key_id="openrouter-main", provider="openrouter")

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="2\n4\n2\n1\n7\n\n0\n0\n",
    )

    assert result.exit_code == 0
    assert "Reset runtime state for key: openrouter-main" in result.stdout
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    db = SQLiteDB(data["storage"]["sqlite_path"])
    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM key_runtime_state WHERE key_id = ?",
            ("openrouter-main",),
        ).fetchone()
    assert row["status"] == "unknown"
    assert row["active"] == 1
    assert row["consecutive_errors"] == 0
    assert row["cooldown_until"] is None
    assert row["last_error_code"] is None
    assert row["failure_count"] == 0


def test_cli_api_access_section_waits_before_back(monkeypatch) -> None:
    runner = CliRunner()
    called: dict[str, bool] = {}

    def _fake_print_api_access(config_path: str) -> None:
        called["printed"] = True

    monkeypatch.setattr("app.cli.app._print_api_access", _fake_print_api_access)

    result = runner.invoke(cli_app, ["panel"], input="3\n1\n\n0\n0\n")

    assert result.exit_code == 0
    assert called["printed"] is True
    assert "Press Enter to return" in result.stdout


def test_test_api_request_shows_selected_and_failed_candidates(monkeypatch, tmp_path: Path, capsys) -> None:
    config_path = _write_config(tmp_path)

    def _fake_post(url: str, headers: dict[str, str], json: dict, timeout: float) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "x-sor-selected-model": "openrouter/gpt-5.4-mini",
                "x-sor-failed-candidates": "github/gpt-4.1-mini, gemini/gemini-2.5-flash",
            },
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-5.4-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hello"},
                        "finish_reason": "stop",
                    }
                ],
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.cli.app._current_master_api_key", lambda: "master-key")
    monkeypatch.setattr("app.cli.app._resolve_local_api_base_url", lambda cfg: "http://127.0.0.1:12345")
    monkeypatch.setattr("app.cli.app.httpx.post", _fake_post)

    _test_api_request(str(config_path))

    output = capsys.readouterr().out
    assert "Intent" in output
    assert "Profile" in output
    assert "Answered model" in output
    assert "openrouter/gpt-5.4-mini" in output
    assert "Failed candidates" in output
    assert "github/gpt-4.1-mini, gemini/gemini-2.5-flash" in output


def test_test_api_request_shows_failed_candidates_from_error_diagnostics(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    config_path = _write_config(tmp_path)

    def _fake_post(url: str, headers: dict[str, str], json: dict, timeout: float) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "detail": {
                    "message": "No healthy route candidates available",
                    "type": "provider_unavailable",
                    "details": {
                        "analysis": {
                            "intent": "trivial",
                            "profile": "fast",
                            "complexity_score": 0,
                            "context_bucket": "small",
                            "token_estimate": 1,
                            "requires_tools": False,
                            "reasons": ["trivial:hello"],
                        },
                        "route_memory": {
                            "status": "miss",
                            "route_alias": "auto/fast",
                            "profile": "fast",
                            "context_bucket": "small",
                        },
                        "candidates": [
                            {
                                "provider": "github",
                                "model": "gpt-4.1-mini",
                                "status": "skipped",
                                "reason": "keys_unhealthy_or_cooling_down",
                                "available_keys": "0",
                            },
                            {
                                "provider": "openrouter",
                                "model": "gpt-5.4-mini",
                                "status": "skipped",
                                "reason": "no_available_keys",
                                "available_keys": "0",
                            },
                        ]
                    },
                }
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.cli.app._current_master_api_key", lambda: "master-key")
    monkeypatch.setattr("app.cli.app._resolve_local_api_base_url", lambda cfg: "http://127.0.0.1:12345")
    monkeypatch.setattr("app.cli.app.httpx.post", _fake_post)

    _test_api_request(str(config_path))

    output = capsys.readouterr().out
    assert "Request Route Analysis" in output
    assert "Route Memory" in output
    assert "miss" in output
    assert "trivial:hello" in output
    assert "Failed candidates" in output
    assert "github/gpt-4.1-mini, openrouter/gpt-5.4-mini" in output


def test_select_test_alias_prefers_generated_aliases(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        "app.cli.app._current_inventory_snapshot",
        lambda config_path, refresh=False: {
            "generated_aliases": [
                {"alias_id": "auto/general"},
                {"alias_id": "auto/fast"},
                {"alias_id": "auto/code"},
                {"alias_id": "auto/free"},
                {"alias_id": "auto/free-cheap"},
            ]
        },
    )
    monkeypatch.setattr("app.cli.app._prompt_menu_choice", lambda prompt="Select option", default="1": "2")

    selected = _select_test_alias(str(config_path))

    assert selected == "auto/free"


def test_model_alias_help_rows_include_free_cheap_description(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    cfg = load_gateway_config(str(config_path))

    rows = dict(
        _model_alias_help_rows(
            cfg,
            {
                "generated_aliases": [
                    {"alias_id": "auto/free-cheap"},
                    {"alias_id": "auto/text/free-cheap"},
                ]
            },
        )
    )

    assert rows["auto/free-cheap"] == "free models first, then lightweight paid fallback"
    assert rows["auto/text/free-cheap"] == "canonical text alias for free-first with cheap fallback"


def test_select_test_alias_refreshes_empty_inventory_before_prompt(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    calls: list[bool] = []

    def _fake_snapshot(config_path: str, refresh: bool = False) -> dict:
        calls.append(refresh)
        if refresh:
            return {"generated_aliases": [{"alias_id": "auto/fast"}]}
        return {"generated_aliases": []}

    monkeypatch.setattr("app.cli.app._current_inventory_snapshot", _fake_snapshot)
    monkeypatch.setattr("app.cli.app._prompt_menu_choice", lambda prompt="Select option", default="1": "1")

    selected = _select_test_alias(str(config_path))

    assert calls == [False, True]
    assert selected == "auto/fast"


def test_select_test_alias_returns_none_when_no_aliases_available(monkeypatch, tmp_path: Path, capsys) -> None:
    config_path = _write_config(tmp_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["routes"]["aliases"] = {}
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr("app.cli.app._current_inventory_snapshot", lambda config_path, refresh=False: {"generated_aliases": []})

    selected = _select_test_alias(str(config_path))

    assert selected is None
    assert "No generated or custom aliases are available" in capsys.readouterr().out


def test_select_test_alias_rejects_unavailable_generated_manual_alias(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setattr("app.cli.app._current_inventory_snapshot", lambda config_path, refresh=False: {"generated_aliases": []})
    prompts = iter(["m", "auto/unknown"])
    monkeypatch.setattr("app.cli.app._prompt_menu_choice", lambda prompt="Select option", default="1": next(prompts))
    monkeypatch.setattr("app.cli.app.typer.prompt", lambda message, default="": "auto/unknown")

    with pytest.raises(Exception):
        _select_test_alias(str(config_path))


def test_cli_gateway_access_automatic_test_prompts_for_alias(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    called: dict[str, str] = {}

    monkeypatch.setattr(
        "app.cli.app._current_inventory_snapshot",
        lambda config_path, refresh=False: {
            "generated_aliases": [
                {"alias_id": "auto/fast"},
                {"alias_id": "auto/general"},
            ]
        },
    )
    monkeypatch.setattr(
        "app.cli.app._test_api_request",
        lambda config_path, model="auto/fast", mode="simple": called.update(
            {"config_path": config_path, "model": model, "mode": mode}
        ),
    )

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="3\n3\n2\n\n0\n0\n",
    )

    assert result.exit_code == 0
    assert called["config_path"] == str(config_path)
    assert called["model"] == "auto/general"
    assert called["mode"] == "simple"
    assert "Select Alias for Automatic API Test" in result.stdout


def test_keys_validate_prints_summary_table(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    class _FakeAdminService:
        async def validate_all_keys(self) -> list[dict]:
            return [
                {
                    "provider": "github",
                    "key_id": "github-main",
                    "status": "valid",
                    "models": ["gpt-4.1", "gpt-5.4-mini"],
                    "latency_ms": 123.4,
                    "error_code": None,
                    "error_message": None,
                },
                {
                    "provider": "gemini",
                    "key_id": "gemini-main",
                    "status": "degraded",
                    "models": [],
                    "latency_ms": 456.7,
                    "error_code": "region_blocked",
                    "error_message": "User location is not supported",
                },
            ]

    class _FakeContainer:
        admin_service = _FakeAdminService()

    monkeypatch.setattr("app.cli.app._container", lambda config_path: _FakeContainer())

    result = runner.invoke(cli_app, ["keys", "validate", "--config-path", str(config_path)])

    assert result.exit_code == 0
    assert "Key Validation" in result.stdout
    assert "github-main" in result.stdout
    assert "gemini-main" in result.stdout
    assert "123.40" in result.stdout
    assert "2" in result.stdout
    assert "region_blocked" in result.stdout


def test_providers_test_shows_error_message_when_error_code_missing(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    class _FakeAdminService:
        async def validate_all_keys(self) -> list[dict]:
            return [
                {
                    "provider": "github",
                    "key_id": "github-main",
                    "status": "degraded",
                    "models": [],
                    "latency_ms": 12.3,
                    "error_code": None,
                    "error_message": "GitHub catalog returned no model records",
                }
            ]

    class _FakeContainer:
        admin_service = _FakeAdminService()

    monkeypatch.setattr("app.cli.app._container", lambda config_path: _FakeContainer())

    result = runner.invoke(cli_app, ["providers", "test", "--config-path", str(config_path)])

    assert result.exit_code == 0
    assert "Provider Key Checks" in result.stdout
    assert "GitHub catalog" in result.stdout
    assert "no model" in result.stdout
    assert "records" in result.stdout
    assert "0" in result.stdout


def test_providers_consistency_compares_runtime_health_and_inventory(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    cfg = load_gateway_config(str(config_path))

    class _RuntimeConfig:
        def get(self):
            return cfg

    class _RuntimeRepo:
        def list_states(self) -> list[dict]:
            return [
                {
                    "key_id": "github-main",
                    "provider": "github",
                    "status": "degraded",
                    "last_error_code": "old_error",
                }
            ]

    class _KeyRegistry:
        runtime_repo = _RuntimeRepo()

        def list_configured_keys(self, cfg, include_unconfigured: bool = False) -> list[dict]:
            return [
                {
                    "provider": "github",
                    "id": "github-main",
                    "configured": True,
                    "status": "degraded",
                }
            ]

    class _AdminService:
        async def refresh_inventory(self) -> dict:
            return {
                "key_results": [
                    {
                        "provider": "github",
                        "key_id": "github-main",
                        "status": "valid",
                        "discovered_models": 2,
                        "error_code": None,
                        "error_message": None,
                    }
                ]
            }

        def current_inventory(self) -> dict:
            return {}

        def latest_health(self) -> list[dict]:
            return [
                {
                    "provider": "github",
                    "key_id": "github-main",
                    "status": "valid",
                    "models_json": "[\"openai/gpt-4.1\", \"openai/gpt-4.1-mini\"]",
                    "error_code": None,
                    "error_message": None,
                }
            ]

    class _FakeContainer:
        runtime_config = _RuntimeConfig()
        key_registry = _KeyRegistry()
        admin_service = _AdminService()

    monkeypatch.setattr("app.cli.app._container", lambda config_path: _FakeContainer())

    result = runner.invoke(cli_app, ["providers", "consistency", "--config-path", str(config_path)])

    assert result.exit_code == 0
    assert "Provider Key Consistency" in result.stdout
    assert "runtime" not in result.stderr.lower()
    assert "2/2" in result.stdout
    assert "old_error" in result.stdout


def test_cli_panel_exits_after_full_uninstall(monkeypatch) -> None:
    runner = CliRunner()
    called: dict[str, bool] = {}

    def _fake_uninstall(
        config_path: str,
        mode: str,
        purge_data: bool = False,
        remove_config: bool = False,
        full: bool = False,
        yes: bool = False,
    ) -> None:
        called["full"] = full
        called["yes"] = yes

    monkeypatch.setattr("app.cli.app.uninstall", _fake_uninstall)

    result = runner.invoke(cli_app, ["panel"], input="6\n8\n2\n")

    assert result.exit_code == 0
    assert called == {"full": True, "yes": False}
    assert result.stdout.count("SimpleOpenRoad Management Terminal") == 1


def test_cli_cleanup_removes_unconfigured_placeholder_keys(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["providers"]["github"]["keys"].insert(
        0,
        {"id": "github-placeholder", "key": "${GITHUB_MODELS_TOKEN}", "priority": 200},
    )
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    result = runner.invoke(cli_app, ["panel", "--config-path", str(config_path)], input="2\n5\n\n0\n0\n")

    assert result.exit_code == 0
    assert "Removed unconfigured placeholder keys: 1" in result.stdout
    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    ids = [item["id"] for item in updated["providers"]["github"]["keys"]]
    assert ids == ["github-main"]


def test_cli_panel_removes_key(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="2\n4\n1\n1\n6\ny\n\n0\n0\n",
    )

    assert result.exit_code == 0
    assert "Removed key: github-main" in result.stdout
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    ids = [item["id"] for item in data["providers"]["github"]["keys"]]
    assert "github-main" not in ids


def test_cli_routes_preview_shows_planned_candidates(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["routes", "preview", "--model", "custom/fast", "--config-path", str(config_path)],
    )

    assert result.exit_code == 0
    assert "Route Preview" in result.stdout
    assert "Request Route Analysis" in result.stdout
    assert "Effective Candidate Order" in result.stdout
    assert "Selected source" in result.stdout
    assert "Candidate preview" in result.stdout
    assert "Candidates" in result.stdout
    assert "github" in result.stdout


def test_cli_routes_preview_includes_runtime_key_details(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    _init_key_state(config_path, key_id="github-main", provider="github")

    result = runner.invoke(
        cli_app,
        ["routes", "preview", "--model", "custom/fast", "--config-path", str(config_path)],
    )

    assert result.exit_code == 0
    assert "Runtime status" in result.stdout
    assert "blocked" in result.stdout
    assert "rate_limit" in result.stdout
    assert "2099-01-01T00:00:00+00:00" in result.stdout


def test_cli_routes_preview_includes_route_memory(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    cfg = load_gateway_config(str(config_path))
    db = SQLiteDB(cfg.storage.sqlite_path)
    schema_path = Path(__file__).resolve().parents[2] / "app" / "storage" / "schema.sql"
    db.initialize(str(schema_path))
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO route_model_memory(
              route_alias, profile, context_bucket, provider, model,
              success_count, avg_latency_ms, updated_at
            ) VALUES ('custom/fast', 'fast', 'small', 'openrouter', 'gpt-4o-mini', 3, 42.5, '2026-04-15T00:00:00+00:00')
            """
        )

    result = runner.invoke(
        cli_app,
        ["routes", "preview", "--model", "custom/fast", "--config-path", str(config_path)],
    )

    assert result.exit_code == 0
    assert "Route memory" in result.stdout
    assert "remembered" in result.stdout
    assert "hit" in result.stdout
    assert "openrouter/gpt-4o-mini" in result.stdout


def test_cli_api_test_prints_candidate_diagnostics(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    def _fake_post(*args, **kwargs) -> httpx.Response:  # noqa: ANN002, ANN003
        return httpx.Response(
            503,
            json={
                "detail": {
                    "message": "No healthy route candidates available",
                    "type": "provider_unavailable",
                    "details": {
                        "analysis": {
                            "intent": "trivial",
                            "profile": "fast",
                            "complexity_score": 0,
                            "context_bucket": "small",
                            "token_estimate": 1,
                            "requires_tools": False,
                            "reasons": ["trivial:hello"],
                        },
                        "candidates": [
                            {
                                "provider": "github",
                                "model": "gpt-4.1-mini",
                                "status": "skipped",
                                "reason": "no_active_configured_keys",
                                "available_keys": 0,
                            }
                        ]
                    },
                }
            },
            request=httpx.Request("POST", "http://127.0.0.1:12345/v1/chat/completions"),
        )

    monkeypatch.setattr("app.cli.app.httpx.post", _fake_post)

    result = runner.invoke(cli_app, ["panel", "--config-path", str(config_path)], input="3\n3\n\n1\n\n0\n0\n")

    assert result.exit_code == 0
    assert "Request Route Analysis" in result.stdout
    assert "Route Candidate Diagnostics" in result.stdout
    assert "no_active_configured_keys" in result.stdout


def test_cli_update_runs_installer_with_existing_paths(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    bin_dir = tmp_path / "bin"
    config_dir.mkdir(parents=True)
    bin_dir.mkdir()
    (install_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")

    called: dict[str, list[str]] = {}

    def _fake_run(command: list[str], check: bool = True):
        called["command"] = command

    monkeypatch.setattr("app.cli.app._run_streaming_command", _fake_run)

    result = runner.invoke(
        cli_app,
        [
            "update",
            "--config-path",
            str(config_path),
            "--install-dir",
            str(install_root),
            "--bin-dir",
            str(bin_dir),
            "--repo",
            "owner/repo",
            "--version",
            "v1.2.3",
            "--arch",
            "x86_64",
            "--python",
            "python3.11",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert called["command"] == [
        "bash",
        str(install_root / "install.sh"),
        "--repo",
        "owner/repo",
        "--install-dir",
        str(install_root),
        "--bin-dir",
        str(bin_dir),
        "--version",
        "v1.2.3",
        "--arch",
        "x86_64",
        "--python",
        "python3.11",
    ]


def test_cli_update_restarts_service_after_success(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    bin_dir = tmp_path / "bin"
    config_dir.mkdir(parents=True)
    bin_dir.mkdir()
    (install_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")

    systemctl_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("app.cli.app._run_streaming_command", lambda command, check=True: None)
    monkeypatch.setattr("app.cli.app.shutil.which", lambda name: "/bin/systemctl" if name == "systemctl" else None)
    monkeypatch.setattr(
        "app.cli.app._run_systemctl",
        lambda mode, *args, **kwargs: systemctl_calls.append((mode, *args)),
    )

    result = runner.invoke(
        cli_app,
        [
            "update",
            "--config-path",
            str(config_path),
            "--install-dir",
            str(install_root),
            "--bin-dir",
            str(bin_dir),
            "--version",
            "v1.2.3",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert ("system", "restart", "sor") in systemctl_calls
    assert "Service restarted" in result.stdout


def test_cli_update_can_skip_service_restart(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    bin_dir = tmp_path / "bin"
    config_dir.mkdir(parents=True)
    bin_dir.mkdir()
    (install_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")

    systemctl_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("app.cli.app._run_streaming_command", lambda command, check=True: None)
    monkeypatch.setattr("app.cli.app.shutil.which", lambda name: "/bin/systemctl" if name == "systemctl" else None)
    monkeypatch.setattr(
        "app.cli.app._run_systemctl",
        lambda mode, *args, **kwargs: systemctl_calls.append((mode, *args)),
    )

    result = runner.invoke(
        cli_app,
        [
            "update",
            "--config-path",
            str(config_path),
            "--install-dir",
            str(install_root),
            "--bin-dir",
            str(bin_dir),
            "--version",
            "v1.2.3",
            "--yes",
            "--no-restart",
        ],
    )

    assert result.exit_code == 0
    assert systemctl_calls == []


def test_cli_panel_update_uses_plain_defaults(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    config_dir.mkdir(parents=True)
    (install_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")

    called: dict[str, list[str]] = {}

    def _fake_run(command: list[str], check: bool = True):
        called["command"] = command

    monkeypatch.setattr("app.cli.app._run_streaming_command", _fake_run)
    monkeypatch.setattr("app.cli.app._resolve_bin_dir", lambda install_root, explicit_bin_dir=None: tmp_path / "bin")
    monkeypatch.setattr(
        "app.cli.app._resolve_update_version",
        lambda repo, requested_version, channel="stable": requested_version or "v9.9.9",
    )

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="6\n5\n1\ny\n\n0\n0\n",
    )

    assert result.exit_code == 0
    assert "--repo" in called["command"]
    assert "FHRha/SimpleOpenRoad" in called["command"]
    assert "--install-dir" in called["command"]
    assert str(install_root) in called["command"]
    assert "--version" in called["command"]
    assert "v9.9.9" in called["command"]
    assert "Version to install" in result.stdout
    assert "v9.9.9" in result.stdout
    assert "Current panel is closing" in result.stdout
    assert "SimpleOpenRoad Management Terminal" in result.stdout
    assert "SimpleOpenRoad / Service and Updates / Update" in result.stdout


def test_cli_update_resolves_latest_before_running_installer(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    bin_dir = tmp_path / "bin"
    config_dir.mkdir(parents=True)
    bin_dir.mkdir()
    (install_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")

    called: dict[str, list[str]] = {}

    def _fake_run(command: list[str], check: bool = True):
        called["command"] = command

    monkeypatch.setattr("app.cli.app._run_streaming_command", _fake_run)
    monkeypatch.setattr(
        "app.cli.app._resolve_update_version",
        lambda repo, requested_version, channel="stable": requested_version or "v1.2.4",
    )

    result = runner.invoke(
        cli_app,
        [
            "update",
            "--config-path",
            str(config_path),
            "--install-dir",
            str(install_root),
            "--bin-dir",
            str(bin_dir),
            "--repo",
            "owner/repo",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert called["command"] == [
        "bash",
        str(install_root / "install.sh"),
        "--repo",
        "owner/repo",
        "--install-dir",
        str(install_root),
        "--bin-dir",
        str(bin_dir),
        "--version",
        "v1.2.4",
    ]
    assert "Version to install" in result.stdout
    assert "v1.2.4" in result.stdout


def test_cli_update_warns_when_already_on_latest_version(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    bin_dir = tmp_path / "bin"
    config_dir.mkdir(parents=True)
    bin_dir.mkdir()
    (install_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (install_root / "VERSION").write_text("0.1.7\n", encoding="utf-8")
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")

    called: dict[str, list[str]] = {}

    def _fake_run(command: list[str], check: bool = True):
        called["command"] = command

    monkeypatch.setattr("app.cli.app._run_streaming_command", _fake_run)
    monkeypatch.setattr(
        "app.cli.app._resolve_update_version",
        lambda repo, requested_version, channel="stable": "v0.1.7",
    )

    result = runner.invoke(
        cli_app,
        [
            "update",
            "--config-path",
            str(config_path),
            "--install-dir",
            str(install_root),
            "--bin-dir",
            str(bin_dir),
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert "Installed version is already the latest available for this channel" in result.stdout
    assert called["command"]


def test_cli_update_passes_prerelease_channel(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    bin_dir = tmp_path / "bin"
    config_dir.mkdir(parents=True)
    bin_dir.mkdir()
    (install_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")

    called: dict[str, list[str]] = {}

    def _fake_run(command: list[str], check: bool = True):
        called["command"] = command

    monkeypatch.setattr("app.cli.app._run_streaming_command", _fake_run)
    monkeypatch.setattr(
        "app.cli.app._resolve_update_version",
        lambda repo, requested_version, channel="stable": "v1.2.5-rc1",
    )

    result = runner.invoke(
        cli_app,
        [
            "update",
            "--config-path",
            str(config_path),
            "--install-dir",
            str(install_root),
            "--bin-dir",
            str(bin_dir),
            "--repo",
            "owner/repo",
            "--channel",
            "prerelease",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert "--channel" in called["command"]
    assert "prerelease" in called["command"]
    assert "Release channel: prerelease" in result.stdout


def test_cli_update_can_install_source_ref(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    bin_dir = tmp_path / "bin"
    config_dir.mkdir(parents=True)
    bin_dir.mkdir()
    (install_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")

    called: dict[str, list[str]] = {}

    def _fake_run(command: list[str], check: bool = True):
        called["command"] = command

    monkeypatch.setattr("app.cli.app._run_streaming_command", _fake_run)

    result = runner.invoke(
        cli_app,
        [
            "update",
            "--config-path",
            str(config_path),
            "--install-dir",
            str(install_root),
            "--bin-dir",
            str(bin_dir),
            "--repo",
            "owner/repo",
            "--ref",
            "main",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert called["command"] == [
        "bash",
        str(install_root / "install.sh"),
        "--repo",
        "owner/repo",
        "--install-dir",
        str(install_root),
        "--bin-dir",
        str(bin_dir),
        "--ref",
        "main",
    ]
    assert "Source: Git ref main" in result.stdout


def test_cli_update_prefers_existing_wrapper_install_root(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    wrapper_root = tmp_path / "wrapper-install"
    config_root = tmp_path / "config-install"
    bin_dir = tmp_path / "bin"
    (wrapper_root / "config").mkdir(parents=True)
    (config_root / "config").mkdir(parents=True)
    bin_dir.mkdir()
    (wrapper_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    config_path = config_root / "config" / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")

    called: dict[str, list[str]] = {}

    def _fake_run(command: list[str], check: bool = True):
        called["command"] = command

    monkeypatch.setattr("app.cli.app._run_streaming_command", _fake_run)
    monkeypatch.setattr("app.cli.app._detect_wrapper_install_root", lambda: wrapper_root)
    monkeypatch.setattr(
        "app.cli.app._resolve_update_version",
        lambda repo, requested_version, channel="stable": "v1.2.4",
    )

    result = runner.invoke(
        cli_app,
        [
            "update",
            "--config-path",
            str(config_path),
            "--bin-dir",
            str(bin_dir),
            "--yes",
        ],
    )

    assert result.exit_code == 0
    install_dir_index = called["command"].index("--install-dir") + 1
    assert called["command"][install_dir_index] == str(wrapper_root)


def test_cli_version_prints_install_diagnostics(tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")
    (install_root / "VERSION").write_text("v-test\n", encoding="utf-8")

    result = runner.invoke(cli_app, ["version", "--config-path", str(config_path)])

    assert result.exit_code == 0
    assert "SimpleOpenRoad Install Diagnostics" in result.stdout
    assert "v-test" in result.stdout
    assert "Setup summary code has /v1 Base URL: yes" in result.stdout
    assert "Setup summary code has alias guide: yes" in result.stdout


def test_cli_panel_update_from_main_uses_source_ref(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    config_dir.mkdir(parents=True)
    (install_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")

    called: dict[str, list[str]] = {}

    def _fake_run(command: list[str], check: bool = True):
        called["command"] = command

    monkeypatch.setattr("app.cli.app._run_streaming_command", _fake_run)
    monkeypatch.setattr("app.cli.app._resolve_bin_dir", lambda install_root, explicit_bin_dir=None: tmp_path / "bin")

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="6\n5\n4\ny\n\n0\n0\n",
    )

    assert result.exit_code == 0
    assert "--ref" in called["command"]
    assert "main" in called["command"]
    assert "Source: Git ref main" in result.stdout


def test_cli_panel_update_can_choose_prerelease(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    config_dir.mkdir(parents=True)
    (install_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    config_path = config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"providers": {}, "health": {"startup_check": False}}), encoding="utf-8")

    called: dict[str, list[str]] = {}

    def _fake_run(command: list[str], check: bool = True):
        called["command"] = command

    monkeypatch.setattr("app.cli.app._run_streaming_command", _fake_run)
    monkeypatch.setattr("app.cli.app._resolve_bin_dir", lambda install_root, explicit_bin_dir=None: tmp_path / "bin")
    monkeypatch.setattr(
        "app.cli.app._resolve_update_version",
        lambda repo, requested_version, channel="stable": "v1.2.5-rc1",
    )

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="6\n5\n2\ny\n\n0\n0\n",
    )

    assert result.exit_code == 0
    assert "--channel" in called["command"]
    assert "prerelease" in called["command"]
    assert "Release channel: prerelease" in result.stdout


def test_cli_routes_set_priority(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        [
            "routes",
            "set-priority",
            "--alias",
            "custom/fast",
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
    first = data["routes"]["aliases"]["custom/fast"]["candidates"][0]
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


def test_cli_keys_add_refreshes_generated_aliases_after_validation(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    calls = {"validate": 0, "refresh": 0, "reload": 0}

    class FakeAdminService:
        async def validate_key(self, provider: str, key_id: str) -> dict:
            calls["validate"] += 1
            return {
                "provider": provider,
                "key_id": key_id,
                "status": "valid",
                "models": ["gpt-4.1-mini"],
                "latency_ms": 1.0,
                "error_code": None,
                "error_message": None,
                "checked_at": "2026-04-15T00:00:00+00:00",
            }

        async def refresh_inventory(self) -> dict:
            calls["refresh"] += 1
            return {"generated_aliases": [{"alias_id": "auto/fast"}]}

    class FakeContainer:
        admin_service = FakeAdminService()

    class FakeReloadResponse:
        status_code = 200

        def json(self):
            return {"generated_aliases": 1}

        @property
        def text(self) -> str:
            return ""

    def _fake_post(url: str, **kwargs):
        calls["reload"] += 1
        assert url.endswith("/admin/reload-config")
        assert kwargs["json"]["config_path"] == str(config_path.resolve())
        return FakeReloadResponse()

    monkeypatch.setattr("app.cli.app._container", lambda config_path: FakeContainer())
    monkeypatch.setattr("app.cli.app.httpx.post", _fake_post)

    result = runner.invoke(
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
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert calls == {"validate": 1, "refresh": 1, "reload": 1}
    assert "Model aliases refreshed: 1 generated aliases available." in result.stdout
    assert "Running gateway reloaded (1 generated aliases)." in result.stdout


def test_cli_keys_add_no_validate_does_not_refresh_aliases(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    calls = {"container": 0}

    def _fake_container(config_path: str):
        calls["container"] += 1
        raise AssertionError("container should not be created for --no-validate")

    monkeypatch.setattr("app.cli.app._container", _fake_container)

    result = runner.invoke(
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

    assert result.exit_code == 0
    assert calls == {"container": 0}


def test_cli_keys_add_rejects_duplicate_id_across_providers(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        [
            "keys",
            "add",
            "--provider",
            "openrouter",
            "--key-id",
            "github-main",
            "--secret",
            "new-secret",
            "--no-validate",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code != 0
    assert "globally unique" in result.stderr
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    openrouter_ids = [item["id"] for item in data["providers"]["openrouter"]["keys"]]
    assert openrouter_ids == ["openrouter-main"]


def test_cli_providers_list_shows_only_providers_with_configured_keys_by_default(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["providers"]["gemini"] = {
        "enabled": True,
        "priority": 10,
        "endpoint": "https://generativelanguage.googleapis.com",
        "keys": [{"id": "gemini-main", "key": "${GEMINI_API_KEY}"}],
    }
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    result = runner.invoke(
        cli_app,
        ["providers", "list", "--config-path", str(config_path)],
    )

    assert result.exit_code == 0
    assert "Providers With Configured Keys" in result.stdout
    assert "github" in result.stdout
    assert "openrouter" in result.stdout
    assert "gemini" not in result.stdout


def test_cli_providers_list_all_includes_unconfigured_provider_catalog_entries(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["providers"]["gemini"] = {
        "enabled": True,
        "priority": 10,
        "endpoint": "https://generativelanguage.googleapis.com",
        "keys": [{"id": "gemini-main", "key": "${GEMINI_API_KEY}"}],
    }
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    result = runner.invoke(
        cli_app,
        ["providers", "list", "--all", "--config-path", str(config_path)],
    )

    assert result.exit_code == 0
    assert "Providers" in result.stdout
    assert "github" in result.stdout
    assert "openrouter" in result.stdout
    assert "gemini" in result.stdout


def test_cli_manage_existing_key_only_lists_providers_with_configured_keys(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["providers"]["gemini"] = {
        "enabled": True,
        "priority": 10,
        "endpoint": "https://generativelanguage.googleapis.com",
        "keys": [{"id": "gemini-main", "key": "${GEMINI_API_KEY}"}],
    }
    data["providers"]["ollama"] = {
        "enabled": False,
        "priority": 80,
        "endpoint": "http://127.0.0.1:11434/v1",
        "auth_required": False,
        "keys": [{"id": "ollama-local", "key": "local"}],
    }
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="2\n4\n0\n0\n",
    )

    assert result.exit_code == 0
    assert "github" in result.stdout
    assert "openrouter" in result.stdout
    assert "gemini" not in result.stdout
    assert "ollama" not in result.stdout


def test_cli_keys_view_panel_lists_only_providers_with_configured_keys(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = _write_config(tmp_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["providers"]["gemini"] = {
        "enabled": True,
        "priority": 10,
        "endpoint": "https://generativelanguage.googleapis.com",
        "keys": [{"id": "gemini-main", "key": "${GEMINI_API_KEY}"}],
    }
    data["providers"]["ollama"] = {
        "enabled": False,
        "priority": 80,
        "endpoint": "http://127.0.0.1:11434/v1",
        "auth_required": False,
        "keys": [{"id": "ollama-local", "key": "local"}],
    }
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    result = runner.invoke(
        cli_app,
        ["panel", "--config-path", str(config_path)],
        input="2\n2\n1\n\n0\n0\n",
    )

    assert result.exit_code == 0
    assert "Providers With Configured Keys" in result.stdout
    assert "github" in result.stdout
    assert "openrouter" in result.stdout
    assert "gemini" not in result.stdout
    assert "ollama" not in result.stdout


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


def test_setup_summary_prints_openai_plugin_settings(monkeypatch, tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "providers": {},
                "routes": {"aliases": {}},
                "health": {"startup_check": False},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    cfg = load_gateway_config(str(config_path))

    monkeypatch.delenv("APP_PUBLIC_DOMAIN", raising=False)
    monkeypatch.delenv("APP_DOMAIN", raising=False)
    monkeypatch.setattr("app.cli.app._detect_server_ip", lambda: "10.20.30.40")
    monkeypatch.setattr(
        "app.cli.app._current_inventory_snapshot",
        lambda config_path, refresh=False: {
            "generated_aliases": [
                {"alias_id": "auto/general"},
                {"alias_id": "auto/fast"},
                {"alias_id": "auto/code"},
            ]
        },
    )

    _print_setup_summary(config_path=str(config_path), cfg=cfg)

    output = capsys.readouterr().out
    assert "Base URL: http://10.20.30.40:12345/v1" in output
    assert "auto/fast" in output
    assert "Recommended default: auto/general" in output
    assert "Model Alias Guide" in output
    assert "auto/general" in output
    assert "recommended default for general chat and everyday use" in output
    assert "auto/code" in output
    assert "coding, debugging, refactoring" in output
    assert "Generated aliases are built from current provider inventory" in output
    assert "Chat endpoint: http://10.20.30.40:12345/v1/chat/completions" in output


def test_service_mode_validation() -> None:
    assert _service_mode("system") == "system"
    assert _service_mode("USER") == "user"


def test_default_install_root_for_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("app.cli.app.os.geteuid", lambda: 0, raising=False)

    assert _default_install_root() == Path("/usr/local/share/simple-open-road")


def test_default_install_root_for_user(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("app.cli.app.os.geteuid", lambda: 1000, raising=False)

    assert _default_install_root() == Path.home() / ".local" / "share" / "simple-open-road"


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


def test_cli_full_uninstall_removes_install_root(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    install_root = tmp_path / "simple-open-road"
    config_dir = install_root / "config"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"
    config = {
        "providers": {},
        "storage": {"sqlite_path": str(install_root / "data" / "gateway.db")},
        "health": {"startup_check": False},
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (install_root / "data").mkdir()
    (install_root / "data" / "gateway.db").write_text("x", encoding="utf-8")

    monkeypatch.setattr("app.cli.app._ensure_systemd_available", lambda: None)
    monkeypatch.setattr("app.cli.app._check_system_mode_permissions", lambda mode: None)
    monkeypatch.setattr("app.cli.app._service_unit_path", lambda mode: tmp_path / "missing.service")
    monkeypatch.setattr("app.cli.app._run_systemctl", lambda mode, *args, **kwargs: None)
    monkeypatch.setattr("app.cli.app._candidate_sor_binaries", lambda install_root: [])

    result = runner.invoke(
        cli_app,
        [
            "uninstall",
            "--mode",
            "system",
            "--full",
            "--yes",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert "Removed install directories" in result.stdout
    assert not install_root.exists()


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


def test_interactive_add_provider_key_reprompts_duplicate_id(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    prompts = iter(["2", "github-main", "openrouter-extra", "secret-value", "100"])

    monkeypatch.setattr("app.cli.app.typer.prompt", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr("app.cli.app.typer.confirm", lambda *args, **kwargs: False)

    _interactive_add_provider_key(str(config_path))

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    openrouter_ids = [item["id"] for item in data["providers"]["openrouter"]["keys"]]
    assert "openrouter-extra" in openrouter_ids
    assert "github-main" not in openrouter_ids


def test_interactive_add_provider_key_persists_cloudflare_account_id_before_keys_add(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = _write_config(tmp_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["providers"]["cloudflare"] = {
        "enabled": True,
        "priority": 29,
        "endpoint": "https://api.cloudflare.com/client/v4",
        "account_id": "",
        "keys": [],
    }
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    prompts = iter(["1", "acc-123", "cloudflare-main", "secret-value", "100"])

    monkeypatch.setattr("app.cli.app._print_provider_choices", lambda provider_names: ["cloudflare"])
    monkeypatch.setattr("app.cli.app.typer.prompt", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr("app.cli.app.typer.confirm", lambda *args, **kwargs: False)

    observed: dict[str, str] = {}

    def _fake_keys_add(
        provider: str,
        key_id: str,
        secret: str,
        account_id: str | None,
        priority: int,
        config_path: str,
        validate: bool,
    ) -> None:
        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        observed["account_id"] = str(data["providers"]["cloudflare"]["account_id"])
        observed["key_account_id"] = str(account_id)

    monkeypatch.setattr("app.cli.app.keys_add", _fake_keys_add)

    _interactive_add_provider_key(str(config_path))

    assert observed["account_id"] == "acc-123"
    assert observed["key_account_id"] == "acc-123"


def test_interactive_add_provider_key_configures_local_provider_connection(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["providers"]["ollama"] = {
        "enabled": False,
        "priority": 80,
        "endpoint": "http://127.0.0.1:11434/v1",
        "auth_required": False,
        "keys": [{"id": "ollama-local", "key": "local", "priority": 100}],
    }
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    prompts = iter(["https://llm.example.com/v1", "ollama-remote", "120"])
    validated: dict[str, str] = {}

    monkeypatch.setattr("app.cli.app._select_provider_from_names", lambda provider_names: "ollama")
    monkeypatch.setattr("app.cli.app.typer.prompt", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr(
        "app.cli.app.typer.confirm",
        lambda message, default=False: False if "require an upstream API key" in str(message) else True,
    )
    monkeypatch.setattr(
        "app.cli.app.keys_validate",
        lambda provider, key_id, config_path: validated.update(
            {"provider": provider, "key_id": key_id, "config_path": config_path}
        ),
    )

    _interactive_add_provider_key(str(config_path))

    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    provider_cfg = updated["providers"]["ollama"]
    assert provider_cfg["enabled"] is True
    assert provider_cfg["endpoint"] == "https://llm.example.com/v1"
    assert provider_cfg["auth_required"] is False
    assert provider_cfg["keys"] == [
        {
            "id": "ollama-remote",
            "key": "local",
            "account_id": None,
            "active": True,
            "priority": 120,
            "weight": 1,
            "tags": [],
            "limits": {"rpm": None},
            "cooldown": {"rate_limit_seconds": 30, "error_seconds": 15},
            "max_retries": 1,
            "max_consecutive_errors": 5,
        }
    ]
    assert validated == {
        "provider": "ollama",
        "key_id": "ollama-remote",
        "config_path": str(config_path),
    }
