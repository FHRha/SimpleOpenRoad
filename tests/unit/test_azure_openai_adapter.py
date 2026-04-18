from __future__ import annotations

from app.config.models import KeyConfig, ProviderConfig
from app.core.types import ChatMessage, UnifiedLLMRequest
from app.providers.azure_openai import AzureOpenAIAdapter


def test_azure_openai_adapter_builds_deployment_url_from_resource_endpoint() -> None:
    adapter = AzureOpenAIAdapter(
        ProviderConfig(
            endpoint="https://example-resource.openai.azure.com?api-version=2024-10-21",
        )
    )

    assert adapter._url_for_deployment("/chat/completions", "gpt-4o-mini") == (
        "https://example-resource.openai.azure.com/openai/deployments/"
        "gpt-4o-mini/chat/completions?api-version=2024-10-21"
    )


def test_azure_openai_adapter_builds_deployment_url_from_template_endpoint() -> None:
    adapter = AzureOpenAIAdapter(
        ProviderConfig(
            endpoint=(
                "https://example-resource.openai.azure.com/openai/deployments/"
                "{deployment}?api-version=2024-10-21"
            ),
        )
    )

    assert adapter._url_for_deployment("/chat/completions", "my deployment") == (
        "https://example-resource.openai.azure.com/openai/deployments/"
        "my%20deployment/chat/completions?api-version=2024-10-21"
    )


def test_azure_openai_adapter_uses_api_key_header() -> None:
    adapter = AzureOpenAIAdapter(ProviderConfig(endpoint="https://example-resource.openai.azure.com"))

    headers = adapter._build_headers(KeyConfig(id="azure-1", key="secret"))

    assert headers["api-key"] == "secret"
    assert "Authorization" not in headers


def test_azure_openai_payload_omits_model_field() -> None:
    adapter = AzureOpenAIAdapter(ProviderConfig(endpoint="https://example-resource.openai.azure.com"))

    payload = adapter._request_payload(
        UnifiedLLMRequest(
            model="my-deployment",
            messages=[ChatMessage(role="user", content="hello")],
            stream=False,
        )
    )

    assert "model" not in payload
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
