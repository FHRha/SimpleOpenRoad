from __future__ import annotations

from app.providers.metadata import (
    PROVIDER_METADATA,
    provider_category,
    provider_display_name,
    search_provider_names,
    sorted_provider_names,
)


def test_provider_metadata_contains_display_names_and_key_links() -> None:
    assert provider_display_name("openai") == "OpenAI"
    assert provider_display_name("azure_openai") == "Azure OpenAI"
    assert provider_display_name("bedrock") == "Amazon Bedrock"
    assert provider_display_name("vertex_ai") == "Google Vertex AI"
    assert provider_display_name("google_code_assist") == "Gemini CLI OAuth"
    assert provider_display_name("perplexity") == "Perplexity"
    assert provider_display_name("novita") == "Novita AI"
    assert provider_display_name("baseten") == "Baseten"
    assert provider_display_name("naga") == "NagaAI"
    assert provider_display_name("nebius") == "Nebius Token Factory"
    assert provider_display_name("near_ai") == "NEAR AI Cloud"
    assert provider_display_name("inference_net") == "Inference.net"
    assert provider_display_name("aai") == "a.ai"
    assert provider_display_name("aimlapi") == "AI/ML API"
    assert provider_display_name("vultr") == "Vultr Serverless Inference"
    assert provider_display_name("friendli") == "Friendli"
    assert provider_display_name("fastrouter") == "FastRouter"
    assert provider_display_name("crusoe") == "Crusoe Managed Inference"
    assert provider_display_name("atoma") == "Atoma"
    assert provider_display_name("parasail") == "Parasail"
    assert provider_display_name("customlab") == "customlab"
    assert PROVIDER_METADATA["anthropic"].api_key_url
    assert PROVIDER_METADATA["cloudflare"].api_key_url


def test_provider_metadata_categories_follow_featured_set() -> None:
    assert provider_category("openai") == "Featured"
    assert provider_category("ollama") == "Featured"
    assert provider_category("google_code_assist") == "Experimental"
    assert provider_category("together") == "Other"


def test_provider_metadata_sorting_and_search() -> None:
    providers = [
        "customlab",
        "custom_openai",
        "together",
        "anthropic",
        "azure_openai",
        "bedrock",
        "vertex_ai",
        "gemini",
        "google_code_assist",
        "moonshot",
        "perplexity",
        "novita",
        "baseten",
        "naga",
        "near_ai",
        "nebius",
        "inference_net",
        "aai",
        "aimlapi",
        "vultr",
        "friendli",
        "fastrouter",
        "crusoe",
        "atoma",
        "parasail",
    ]

    assert sorted_provider_names(providers)[:5] == ["anthropic", "azure_openai", "bedrock", "vertex_ai", "gemini"]
    assert "google_code_assist" in sorted_provider_names(providers)
    assert search_provider_names(providers, "claude")[0] == "anthropic"
    assert search_provider_names(providers, "azure")[0] == "azure_openai"
    assert search_provider_names(providers, "amazon bedrock")[0] == "bedrock"
    assert search_provider_names(providers, "vertex ai")[0] == "vertex_ai"
    assert search_provider_names(providers, "gemini cli")[0] == "google_code_assist"
    assert search_provider_names(providers, "kimi")[0] == "moonshot"
    assert search_provider_names(providers, "sonar")[0] == "perplexity"
    assert search_provider_names(providers, "base ten")[0] == "baseten"
    assert search_provider_names(providers, "novita ai")[0] == "novita"
    assert search_provider_names(providers, "token factory")[0] == "nebius"
    assert search_provider_names(providers, "near ai")[0] == "near_ai"
    assert search_provider_names(providers, "inference net")[0] == "inference_net"
    assert search_provider_names(providers, "apex")[0] == "aai"
    assert search_provider_names(providers, "aiml")[0] == "aimlapi"
    assert search_provider_names(providers, "vultr inference")[0] == "vultr"
    assert search_provider_names(providers, "fast router")[0] == "fastrouter"
    assert search_provider_names(providers, "crusoe cloud")[0] == "crusoe"
    assert search_provider_names(providers, "customlab") == ["customlab"]
    assert search_provider_names(providers, "openai compatible") == ["custom_openai"]
