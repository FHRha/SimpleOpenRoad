from pathlib import Path

import pytest

from app.config.loader import load_gateway_config
from app.core.errors import ConfigError


def test_load_gateway_config_success() -> None:
    cfg = load_gateway_config("tests/fixtures/sample_config.yaml")
    assert cfg.server.port == 12345
    assert "github" in cfg.providers


def test_load_gateway_config_missing_file() -> None:
    with pytest.raises(ConfigError):
        load_gateway_config("tests/fixtures/not_exists.yaml")


def test_load_gateway_config_invalid_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- invalid", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_gateway_config(str(bad))
