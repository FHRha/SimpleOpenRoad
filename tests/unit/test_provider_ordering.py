from __future__ import annotations

from app.cli.app import _provider_category, _sorted_provider_names


def test_sorted_provider_names_puts_featured_first() -> None:
    ordered = _sorted_provider_names(
        ["customlab", "cloudflare", "groq", "gemini", "openrouter", "zzz-provider"]
    )

    assert ordered[:4] == ["gemini", "openrouter", "groq", "cloudflare"]
    assert ordered[-2:] == ["customlab", "zzz-provider"]


def test_provider_category_marks_featured_and_other() -> None:
    assert _provider_category("gemini") == "Featured"
    assert _provider_category("cloudflare") == "Featured"
    assert _provider_category("customlab") == "Other"
