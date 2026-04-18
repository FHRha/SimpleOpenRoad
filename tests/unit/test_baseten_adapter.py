from __future__ import annotations

from app.config.models import KeyConfig, ProviderConfig
from app.providers.baseten import BasetenAdapter


def test_baseten_adapter_uses_api_key_authorization_scheme() -> None:
    adapter = BasetenAdapter(ProviderConfig(endpoint="https://inference.baseten.co/v1"))

    headers = adapter._build_headers(KeyConfig(id="baseten-1", key="secret"))

    assert headers["Authorization"] == "Api-Key secret"
    assert headers["Content-Type"] == "application/json"


def test_baseten_adapter_uses_openai_compatible_paths() -> None:
    adapter = BasetenAdapter(ProviderConfig(endpoint="https://inference.baseten.co/v1"))

    assert adapter._url(adapter.chat_completions_path) == "https://inference.baseten.co/v1/chat/completions"
    assert adapter._url(adapter.models_path) == "https://inference.baseten.co/v1/models"
