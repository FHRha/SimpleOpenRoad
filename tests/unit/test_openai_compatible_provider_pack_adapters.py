from __future__ import annotations

import pytest

from app.providers.aai import AAIAdapter
from app.providers.aimlapi import AIMLAPIAdapter
from app.config.models import ProviderConfig
from app.providers.atoma import AtomaAdapter
from app.providers.crusoe import CrusoeAdapter
from app.providers.fastrouter import FastRouterAdapter
from app.providers.friendli import FriendliAdapter
from app.providers.inference_net import InferenceNetAdapter
from app.providers.naga import NagaAdapter
from app.providers.near_ai import NearAIAdapter
from app.providers.nebius import NebiusAdapter
from app.providers.parasail import ParasailAdapter
from app.providers.vultr import VultrAdapter


@pytest.mark.parametrize(
    ("adapter_cls", "endpoint"),
    [
        (NagaAdapter, "https://api.naga.ac/v1"),
        (NebiusAdapter, "https://api.tokenfactory.nebius.com/v1"),
        (FriendliAdapter, "https://api.friendli.ai/serverless/v1"),
        (FastRouterAdapter, "https://go.fastrouter.ai/api/v1"),
        (CrusoeAdapter, "https://api.crusoe.ai/v1"),
        (AtomaAdapter, "https://api.atoma.network/v1"),
        (ParasailAdapter, "https://api.saas.parasail.io/v1"),
        (InferenceNetAdapter, "https://api.inference.net/v1"),
        (NearAIAdapter, "https://cloud-api.near.ai/v1"),
        (AAIAdapter, "https://api.a.ai/v1"),
        (AIMLAPIAdapter, "https://api.aimlapi.com/v1"),
        (VultrAdapter, "https://api.vultrinference.com/v1"),
    ],
)
def test_openai_compatible_provider_pack_uses_standard_paths(adapter_cls, endpoint: str) -> None:
    adapter = adapter_cls(ProviderConfig(endpoint=endpoint))

    assert adapter._url(adapter.chat_completions_path) == f"{endpoint}/chat/completions"
    assert adapter._url(adapter.models_path) == f"{endpoint}/models"
