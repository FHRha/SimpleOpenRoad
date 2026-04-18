from __future__ import annotations

from app.config.models import ProviderConfig
from app.providers.novita import NovitaAdapter


def test_novita_adapter_uses_openai_compatible_base_path() -> None:
    adapter = NovitaAdapter(ProviderConfig(endpoint="https://api.novita.ai/openai"))

    assert adapter._url(adapter.chat_completions_path) == "https://api.novita.ai/openai/v1/chat/completions"
    assert adapter._url(adapter.models_path) == "https://api.novita.ai/openai/v1/models"
