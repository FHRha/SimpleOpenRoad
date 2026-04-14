from pathlib import Path

import pytest

from app.config.loader import load_gateway_config
from app.core.errors import ConfigError


def test_load_gateway_config_success() -> None:
    cfg = load_gateway_config("tests/fixtures/sample_config.yaml")
    assert cfg.server.port == 12345
    assert "github" in cfg.providers
    assert cfg.routes.aliases == {}


def test_load_gateway_config_removes_generated_aliases_from_custom_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
providers:
  github:
    enabled: true
    priority: 20
    endpoint: https://example.invalid
    keys:
      - id: github-main
        key: k
routes:
  aliases:
    auto/example:
      strategy: strict_priority
      candidates:
        - provider: github
          model: gpt-4.1
    custom/example:
      strategy: strict_priority
      candidates:
        - provider: github
          model: gpt-4.1-mini
health:
  startup_check: false
""",
        encoding="utf-8",
    )

    cfg = load_gateway_config(str(config_path))

    assert "auto/example" not in cfg.routes.aliases
    assert "custom/example" in cfg.routes.aliases


def test_load_gateway_config_keeps_empty_aliases_when_none_are_defined(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
providers: {}
routes:
  aliases: {}
health:
  startup_check: false
""",
        encoding="utf-8",
    )

    cfg = load_gateway_config(str(config_path))

    assert cfg.routes.aliases == {}


def test_load_gateway_config_missing_file() -> None:
    with pytest.raises(ConfigError):
        load_gateway_config("tests/fixtures/not_exists.yaml")


def test_load_gateway_config_invalid_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- invalid", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_gateway_config(str(bad))


def test_load_gateway_config_parses_inventory_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
providers: {}
inventory:
  overrides:
    - provider: openrouter
      model_pattern: "openai/*codex*"
      force_categories: [code]
      force_tool_capable: true
health:
  startup_check: false
""",
        encoding="utf-8",
    )

    cfg = load_gateway_config(str(config_path))

    assert len(cfg.inventory.overrides) == 1
    assert cfg.inventory.overrides[0].provider == "openrouter"
    assert cfg.inventory.overrides[0].force_categories == ["code"]


def test_load_gateway_config_parses_inventory_refresh_schedule(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
providers: {}
inventory:
  refresh_time: "04:30"
  refresh_timezone: UTC
  refresh_interval_hours: 12
health:
  startup_check: false
""",
        encoding="utf-8",
    )

    cfg = load_gateway_config(str(config_path))

    assert cfg.inventory.refresh_time == "04:30"
    assert cfg.inventory.refresh_timezone == "UTC"
    assert cfg.inventory.refresh_interval_hours == 12
