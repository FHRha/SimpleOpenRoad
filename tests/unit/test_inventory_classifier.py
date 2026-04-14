from app.config.models import GatewayConfig, InventoryOverrideConfig
from app.inventory.classifier import classify_model
from app.inventory.models import DiscoveredModel


def test_inventory_classifier_scores_code_model() -> None:
    model = DiscoveredModel(
        provider="openrouter",
        model_id="openai/gpt-5.3-codex",
        display_name="openai/gpt-5.3-codex",
        modality="text",
        is_text_candidate=True,
        supports_tools=True,
    )

    classification = classify_model(model)

    assert classification.code_score > 0
    assert classification.tool_capable is True
    assert "code" in classification.classification_tags


def test_inventory_classifier_scores_free_fast_model() -> None:
    model = DiscoveredModel(
        provider="openrouter",
        model_id="openai/gpt-5-mini:free",
        display_name="openai/gpt-5-mini:free",
        modality="text",
        is_text_candidate=True,
        is_free=True,
    )

    classification = classify_model(model)

    assert classification.free_score == 100
    assert classification.fast_score > 0
    assert "free" in classification.classification_tags
    assert "fast" in classification.classification_tags


def test_inventory_classifier_marks_excluded_model() -> None:
    model = DiscoveredModel(
        provider="gemini",
        model_id="imagen-4.0-generate-001",
        display_name="imagen-4.0-generate-001",
        modality="image",
        is_text_candidate=False,
        excluded_reason="non_text_modality:image",
    )

    classification = classify_model(model)

    assert "excluded" in classification.classification_tags
    assert classification.classification_reason.endswith("excluded:non_text_modality:image")


def test_inventory_classifier_applies_manual_override_categories_and_tools() -> None:
    model = DiscoveredModel(
        provider="openrouter",
        model_id="openai/gpt-5-mini",
        display_name="openai/gpt-5-mini",
        modality="text",
        is_text_candidate=True,
    )
    cfg = GatewayConfig()
    override = InventoryOverrideConfig(
        provider="openrouter",
        model_pattern="openai/gpt-5-mini",
        force_categories=["reasoning", "code"],
        force_tool_capable=True,
        reason="promote for testing",
    )

    classification = classify_model(model, capabilities=cfg.model_capabilities, overrides=[override])

    assert classification.reasoning_score >= 100
    assert classification.code_score >= 100
    assert classification.tool_capable is True
    assert "reasoning" in classification.classification_tags
    assert "code" in classification.classification_tags
