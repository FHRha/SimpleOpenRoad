from __future__ import annotations

from app.config.models import ProviderConfig
from app.providers.deepinfra import DeepInfraAdapter


def test_deepinfra_adapter_uses_openai_subpath_without_double_v1() -> None:
    adapter = DeepInfraAdapter(
        ProviderConfig(
            endpoint="https://api.deepinfra.com/v1/openai",
            keys=[],
        )
    )

    assert adapter._url(adapter.chat_completions_path) == "https://api.deepinfra.com/v1/openai/chat/completions"
    assert adapter._url(adapter.models_path) == "https://api.deepinfra.com/v1/openai/models"
