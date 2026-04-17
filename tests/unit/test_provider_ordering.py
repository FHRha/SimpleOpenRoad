from __future__ import annotations

from app.cli.app import _print_provider_choices, _provider_category, _sorted_provider_names


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


def test_print_provider_choices_shows_explicit_group_separators(capsys) -> None:
    ordered = _print_provider_choices(["customlab", "gemini"])

    captured = capsys.readouterr().out

    assert ordered == ["gemini", "customlab"]
    assert "--- Featured providers ---" in captured
    assert "--- Other providers ---" in captured
    assert "1) gemini" in captured
    assert "2) customlab" in captured
