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
                    "auto/fast": {
                        "strategy": "strict_priority",
                        "candidates": [{"provider": "github", "model": "gpt-4.1-mini"}],
                    }
                }
            },
        }
    )

    candidates, alias = resolve_candidates(cfg, "auto/fast")
    assert alias == "auto/fast"
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
