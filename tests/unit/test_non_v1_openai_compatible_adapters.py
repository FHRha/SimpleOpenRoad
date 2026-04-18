from __future__ import annotations

from app.config.models import ProviderConfig
from app.providers.zai import ZAIAdapter
from app.providers.zhipuai import ZhipuAIAdapter


def test_zhipuai_adapter_uses_provider_base_path_without_extra_v1() -> None:
    adapter = ZhipuAIAdapter(
        ProviderConfig(
            endpoint="https://open.bigmodel.cn/api/paas/v4",
        )
    )

    assert adapter._url(adapter.chat_completions_path) == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert adapter._url(adapter.models_path) == "https://open.bigmodel.cn/api/paas/v4/models"


def test_zai_adapter_uses_provider_base_path_without_extra_v1() -> None:
    adapter = ZAIAdapter(
        ProviderConfig(
            endpoint="https://api.z.ai/api/paas/v4",
        )
    )

    assert adapter._url(adapter.chat_completions_path) == "https://api.z.ai/api/paas/v4/chat/completions"
    assert adapter._url(adapter.models_path) == "https://api.z.ai/api/paas/v4/models"
