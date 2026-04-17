from app.config.models import GatewayConfig, ProviderConfig
from app.inventory.aliases import build_generated_aliases
from app.inventory.models import DiscoveredModel, ModelClassification, ProviderSpecialRoute


def _config() -> GatewayConfig:
    return GatewayConfig(
        providers={
            "gemini": ProviderConfig(enabled=True, priority=10, endpoint="https://gemini.invalid"),
            "openrouter": ProviderConfig(enabled=True, priority=20, endpoint="https://openrouter.invalid"),
        }
    )


def test_inventory_aliases_build_provider_and_global_text_aliases() -> None:
    models = [
        DiscoveredModel(
            provider="gemini",
            model_id="gemini-2.5-flash",
            display_name="gemini-2.5-flash",
            modality="text",
            is_text_candidate=True,
        ),
        DiscoveredModel(
            provider="openrouter",
            model_id="openai/gpt-5-mini:free",
            display_name="openai/gpt-5-mini:free",
            modality="text",
            is_text_candidate=True,
            is_free=True,
        ),
        DiscoveredModel(
            provider="openrouter",
            model_id="openai/gpt-5.3-codex",
            display_name="openai/gpt-5.3-codex",
            modality="text",
            is_text_candidate=True,
            supports_tools=True,
            tools_state="supported",
        ),
        DiscoveredModel(
            provider="openrouter",
            model_id="openai/gpt-5.4-nano",
            display_name="openai/gpt-5.4-nano",
            modality="text",
            is_text_candidate=True,
        ),
    ]
    classifications = [
        ModelClassification(
            provider="gemini",
            model_id="gemini-2.5-flash",
            modality="text",
            fast_score=30,
            general_score=35,
            classification_tags=["fast", "general"],
        ),
        ModelClassification(
            provider="openrouter",
            model_id="openai/gpt-5-mini:free",
            modality="text",
            free_score=100,
            fast_score=30,
            general_score=20,
            classification_tags=["free", "fast", "general"],
        ),
        ModelClassification(
            provider="openrouter",
            model_id="openai/gpt-5.3-codex",
            modality="text",
            code_score=90,
            general_score=20,
            tool_capable=True,
            classification_tags=["code", "general", "tool_capable"],
        ),
        ModelClassification(
            provider="openrouter",
            model_id="openai/gpt-5.4-nano",
            modality="text",
            fast_score=30,
            general_score=20,
            classification_tags=["fast", "general"],
        ),
    ]
    special_routes = [
        ProviderSpecialRoute(
            provider="openrouter",
            route_id="openrouter/free",
            modality="text",
            supports_chat=True,
            supports_tools=False,
            category_hints=["free"],
        )
    ]

    aliases = build_generated_aliases(_config(), models, classifications, special_routes)
    alias_map = {item.alias_id: item for item in aliases}

    assert "gemini/text/fast" in alias_map
    assert "openrouter/text/free" in alias_map
    assert "openrouter/text/free-cheap" in alias_map
    assert "openrouter/text/code" in alias_map
    assert "auto/text/free" in alias_map
    assert "auto/text/free-cheap" in alias_map
    assert "auto/free-cheap" in alias_map
    assert "auto/text/fast" in alias_map
    assert "auto/code" in alias_map

    free_alias = alias_map["openrouter/text/free"]
    assert free_alias.candidates[0].candidate_type == "special_route"
    assert free_alias.candidates[0].model_id == "openrouter/free"

    free_cheap_alias = alias_map["openrouter/text/free-cheap"]
    assert [item.model_id for item in free_cheap_alias.candidates[:3]] == [
        "openrouter/free",
        "openai/gpt-5-mini:free",
        "openai/gpt-5.4-nano",
    ]

    code_alias = alias_map["openrouter/text/code"]
    assert code_alias.candidates[0].model_id == "openai/gpt-5.3-codex"

    global_fast = alias_map["auto/text/fast"]
    assert [item.provider for item in global_fast.candidates[:2]] == ["gemini", "openrouter"]


def test_inventory_aliases_skip_categories_without_candidates() -> None:
    models = [
        DiscoveredModel(
            provider="gemini",
            model_id="gemini-2.5-flash",
            display_name="gemini-2.5-flash",
            modality="text",
            is_text_candidate=True,
        )
    ]
    classifications = [
        ModelClassification(
            provider="gemini",
            model_id="gemini-2.5-flash",
            modality="text",
            fast_score=30,
            general_score=20,
            classification_tags=["fast", "general"],
        )
    ]

    aliases = build_generated_aliases(_config(), models, classifications, [])
    alias_ids = {item.alias_id for item in aliases}

    assert "gemini/text/fast" in alias_ids
    assert "gemini/text/code" not in alias_ids
    assert "auto/text/code" not in alias_ids


def test_inventory_aliases_build_media_families_without_affecting_text_aliases() -> None:
    models = [
        DiscoveredModel(
            provider="gemini",
            model_id="imagen-4.0-generate-001",
            display_name="imagen-4.0-generate-001",
            modality="image",
        ),
        DiscoveredModel(
            provider="gemini",
            model_id="veo-3.0-generate-001",
            display_name="veo-3.0-generate-001",
            modality="video",
        ),
        DiscoveredModel(
            provider="gemini",
            model_id="gemini-2.5-flash-native-audio-latest",
            display_name="gemini-2.5-flash-native-audio-latest",
            modality="audio",
        ),
    ]

    aliases = build_generated_aliases(_config(), models, [], [])
    alias_ids = {item.alias_id for item in aliases}

    assert "gemini/image/default" in alias_ids
    assert "gemini/video/default" in alias_ids
    assert "gemini/audio/default" in alias_ids
    assert "auto/image/default" in alias_ids
    assert "auto/video/default" in alias_ids
    assert "auto/audio/default" in alias_ids
    assert "auto/text/general" not in alias_ids
