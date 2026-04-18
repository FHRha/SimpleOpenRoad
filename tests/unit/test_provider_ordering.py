from __future__ import annotations

from app.cli.app import _print_provider_choices, _provider_category, _search_provider_names, _sorted_provider_names


def test_sorted_provider_names_puts_featured_first() -> None:
    ordered = _sorted_provider_names(
        [
            "customlab",
            "cloudflare",
            "groq",
            "gemini",
            "openrouter",
            "together",
            "cerebras",
            "openai",
            "anthropic",
            "mistral",
            "deepseek",
            "ollama",
            "zzz-provider",
        ]
    )

    assert ordered[:9] == [
        "openai",
        "anthropic",
        "gemini",
        "openrouter",
        "groq",
        "cloudflare",
        "mistral",
        "deepseek",
        "ollama",
    ]
    assert ordered[-4:] == ["cerebras", "customlab", "together", "zzz-provider"]


def test_provider_category_marks_featured_and_other() -> None:
    assert _provider_category("openai") == "Featured"
    assert _provider_category("anthropic") == "Featured"
    assert _provider_category("azure_openai") == "Featured"
    assert _provider_category("gemini") == "Featured"
    assert _provider_category("cloudflare") == "Featured"
    assert _provider_category("mistral") == "Featured"
    assert _provider_category("deepseek") == "Featured"
    assert _provider_category("ollama") == "Featured"
    assert _provider_category("together") == "Other"
    assert _provider_category("cerebras") == "Other"
    assert _provider_category("customlab") == "Other"


def test_print_provider_choices_shows_explicit_group_separators(capsys) -> None:
    ordered = _print_provider_choices(["customlab", "gemini"])

    captured = capsys.readouterr().out

    assert ordered == ["gemini", "customlab"]
    assert "--- Featured providers ---" in captured
    assert "--- Other providers ---" in captured
    assert "1) gemini - Google Gemini" in captured
    assert "2) customlab - customlab" in captured
    assert "S) Search provider" in captured
    assert "M) Manual provider id" in captured


def test_print_provider_choices_limits_long_tail(capsys) -> None:
    providers = ["gemini"] + [f"provider{i:02d}" for i in range(20)]

    displayed = _print_provider_choices(providers)

    captured = capsys.readouterr().out

    assert "provider00" in displayed
    assert "provider12" not in displayed
    assert "... 8 more provider(s)." in captured


def test_search_provider_names_matches_aliases_and_substrings() -> None:
    providers = ["anthropic", "moonshot", "textgenwebui", "zhipuai", "customlab"]

    assert _search_provider_names(providers, "claude")[0] == "anthropic"
    assert _search_provider_names(providers, "kimi")[0] == "moonshot"
    assert _search_provider_names(providers, "ooba")[0] == "textgenwebui"
    assert _search_provider_names(providers, "glm")[0] == "zhipuai"
