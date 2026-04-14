from app.config.models import GatewayConfig
from app.router.alias_resolver import resolve_candidates


def test_alias_resolution_returns_ordered_candidates() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "providers": {
                "github": {
                    "enabled": True,
                    "priority": 20,
                    "endpoint": "https://example.invalid",
                    "keys": [
                        {
                            "id": "github-main",
                            "key": "k",
                        }
                    ],
                }
            },
            "routes": {
                "aliases": {
                    "custom/fast": {
                        "strategy": "strict_priority",
                        "candidates": [{"provider": "github", "model": "gpt-4.1-mini"}],
                    }
                }
            },
        }
    )

    candidates, alias = resolve_candidates(cfg, "custom/fast")
    assert alias == "custom/fast"
    assert len(candidates) == 1
    assert candidates[0].provider == "github"
    assert candidates[0].model == "gpt-4.1-mini"


def test_provider_model_resolution() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "providers": {
                "gemini": {
                    "enabled": True,
                    "priority": 10,
                    "endpoint": "https://example.invalid",
                    "keys": [{"id": "gemini-main", "key": "k"}],
                }
            }
        }
    )

    candidates, alias = resolve_candidates(cfg, "gemini/gemini-2.5-flash")
    assert alias is None
    assert len(candidates) == 1
    assert candidates[0].provider == "gemini"
    assert candidates[0].model == "gemini-2.5-flash"


def test_alias_resolution_skips_providers_without_configured_keys() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "providers": {
                "gemini": {
                    "enabled": True,
                    "priority": 10,
                    "endpoint": "https://example.invalid",
                    "keys": [],
                },
                "github": {
                    "enabled": True,
                    "priority": 20,
                    "endpoint": "https://example.invalid",
                    "keys": [{"id": "github-main", "key": "k"}],
                },
            },
            "routes": {
                "aliases": {
                    "custom/fast": {
                        "strategy": "strict_priority",
                        "candidates": [
                            {"provider": "gemini", "model": "gemini-2.5-flash"},
                            {"provider": "github", "model": "gpt-4.1-mini"},
                        ],
                    }
                }
            },
        }
    )

    candidates, alias = resolve_candidates(cfg, "custom/fast")

    assert alias == "custom/fast"
    assert len(candidates) == 1
    assert candidates[0].provider == "github"
    assert candidates[0].model == "gpt-4.1-mini"


def test_exact_model_name_is_preserved_for_configured_providers() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "providers": {
                "github": {
                    "enabled": True,
                    "priority": 20,
                    "endpoint": "https://example.invalid",
                    "keys": [{"id": "github-main", "key": "k"}],
                },
                "openrouter": {
                    "enabled": True,
                    "priority": 30,
                    "endpoint": "https://example.invalid",
                    "keys": [{"id": "openrouter-main", "key": "k"}],
                },
            }
        }
    )

    candidates, alias = resolve_candidates(cfg, "gpt-4.1-mini")

    assert alias is None
    assert [candidate.model for candidate in candidates] == ["gpt-4.1-mini", "gpt-4.1-mini"]
    assert [candidate.provider for candidate in candidates] == ["github", "openrouter"]
