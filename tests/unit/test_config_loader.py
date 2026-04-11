from pathlib import Path

import pytest

from app.config.loader import load_gateway_config
from app.core.errors import ConfigError


def test_load_gateway_config_success() -> None:
    cfg = load_gateway_config("tests/fixtures/sample_config.yaml")
    assert cfg.server.port == 12345
    assert "github" in cfg.providers
    assert "auto/fast" in cfg.routes.aliases
    assert "auto/fallback" not in cfg.routes.aliases


def test_load_gateway_config_migrates_old_fallback_alias(tmp_path: Path) -> None:
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
    auto/fallback:
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

    assert "auto/fallback" not in cfg.routes.aliases
    assert "auto/smart" in cfg.routes.aliases
    assert "auto/fast" in cfg.routes.aliases
    assert "auto/balanced" in cfg.routes.aliases
    assert "auto/strong" in cfg.routes.aliases
    assert "auto/code" in cfg.routes.aliases


def test_load_gateway_config_seeds_defaults_when_aliases_are_empty(tmp_path: Path) -> None:
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

    assert "auto/smart" in cfg.routes.aliases
    assert "auto/fast" in cfg.routes.aliases
    assert "auto/balanced" in cfg.routes.aliases
    assert "auto/strong" in cfg.routes.aliases
    assert "auto/code" in cfg.routes.aliases


def test_load_gateway_config_missing_file() -> None:
    with pytest.raises(ConfigError):
        load_gateway_config("tests/fixtures/not_exists.yaml")


def test_load_gateway_config_invalid_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- invalid", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_gateway_config(str(bad))
