from __future__ import annotations

from app.config.models import ProviderConfig
from app.providers.perplexity import PerplexityAdapter


def test_perplexity_adapter_uses_sonar_chat_path_and_v1_models() -> None:
    adapter = PerplexityAdapter(ProviderConfig(endpoint="https://api.perplexity.ai/v1"))

    assert adapter._url(adapter.chat_completions_path) == "https://api.perplexity.ai/v1/sonar"
    assert adapter._url(adapter.models_path) == "https://api.perplexity.ai/v1/models"
