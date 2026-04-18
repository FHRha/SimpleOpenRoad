from __future__ import annotations

from app.providers.aai import AAIAdapter
from app.providers.aimlapi import AIMLAPIAdapter
from app.config.models import GatewayConfig
from app.providers.atoma import AtomaAdapter
from app.providers.anthropic import AnthropicAdapter
from app.providers.azure_openai import AzureOpenAIAdapter
from app.providers.bedrock import BedrockAdapter
from app.providers.baseten import BasetenAdapter
from app.providers.cerebras import CerebrasAdapter
from app.providers.cloudflare_workers_ai import CloudflareWorkersAIAdapter
from app.providers.cohere import CohereAdapter
from app.providers.crusoe import CrusoeAdapter
from app.providers.deepinfra import DeepInfraAdapter
from app.providers.deepseek import DeepSeekAdapter
from app.providers.fastrouter import FastRouterAdapter
from app.providers.featherless import FeatherlessAdapter
from app.providers.fireworks import FireworksAdapter
from app.providers.friendli import FriendliAdapter
from app.providers.gemini import GeminiAdapter
from app.providers.groq import GroqAdapter
from app.providers.github_models import GitHubModelsAdapter
from app.providers.huggingface import HuggingFaceAdapter
from app.providers.hyperbolic import HyperbolicAdapter
from app.providers.inference_net import InferenceNetAdapter
from app.providers.mistral import MistralAdapter
from app.providers.moonshot import MoonshotAdapter
from app.providers.naga import NagaAdapter
from app.providers.near_ai import NearAIAdapter
from app.providers.nebius import NebiusAdapter
from app.providers.nvidia import NVIDIAAdapter
from app.providers.novita import NovitaAdapter
from app.providers.openai import OpenAIAdapter
from app.providers.openai_compatible import OpenAICompatibleAdapter
from app.providers.openrouter import OpenRouterAdapter
from app.providers.ovhcloud import OVHcloudAdapter
from app.providers.parasail import ParasailAdapter
from app.providers.perplexity import PerplexityAdapter
from app.providers.sambanova import SambaNovaAdapter
from app.providers.siliconflow import SiliconFlowAdapter
from app.providers.registry import build_provider_registry
from app.providers.together import TogetherAdapter
from app.providers.vertex_ai import VertexAIAdapter
from app.providers.vultr import VultrAdapter
from app.providers.xai import XAIAdapter
from app.providers.zai import ZAIAdapter
from app.providers.zhipuai import ZhipuAIAdapter


def test_provider_registry_builds_all_supported_adapters() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "providers": {
                "openai": {"enabled": True, "priority": 9, "endpoint": "https://api.openai.com/v1"},
                "anthropic": {"enabled": True, "priority": 11, "endpoint": "https://api.anthropic.com/v1"},
                "azure_openai": {
                    "enabled": True,
                    "priority": 12,
                    "endpoint": "https://example-resource.openai.azure.com?api-version=2024-10-21",
                },
                "bedrock": {
                    "enabled": True,
                    "priority": 13,
                    "endpoint": "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1",
                },
                "vertex_ai": {
                    "enabled": True,
                    "priority": 14,
                    "endpoint": "https://aiplatform.googleapis.com/v1/projects/p/locations/global/endpoints/openapi",
                },
                "gemini": {"enabled": True, "priority": 10, "endpoint": "https://gemini.invalid"},
                "github": {"enabled": True, "priority": 20, "endpoint": "https://models.github.ai"},
                "mistral": {"enabled": True, "priority": 23, "endpoint": "https://api.mistral.ai/v1"},
                "groq": {"enabled": True, "priority": 25, "endpoint": "https://api.groq.com/openai/v1"},
                "deepseek": {"enabled": True, "priority": 26, "endpoint": "https://api.deepseek.com/v1"},
                "xai": {"enabled": True, "priority": 27, "endpoint": "https://api.x.ai/v1"},
                "cohere": {
                    "enabled": True,
                    "priority": 28,
                    "endpoint": "https://api.cohere.ai/compatibility/v1",
                },
                "moonshot": {"enabled": True, "priority": 28, "endpoint": "https://api.moonshot.ai/v1"},
                "sambanova": {"enabled": True, "priority": 29, "endpoint": "https://api.sambanova.ai/v1"},
                "nvidia": {"enabled": True, "priority": 30, "endpoint": "https://integrate.api.nvidia.com/v1"},
                "zhipuai": {
                    "enabled": True,
                    "priority": 32,
                    "endpoint": "https://open.bigmodel.cn/api/paas/v4",
                },
                "zai": {
                    "enabled": True,
                    "priority": 33,
                    "endpoint": "https://api.z.ai/api/paas/v4",
                },
                "featherless": {
                    "enabled": True,
                    "priority": 34,
                    "endpoint": "https://api.featherless.ai/v1",
                },
                "hyperbolic": {
                    "enabled": True,
                    "priority": 35,
                    "endpoint": "https://api.hyperbolic.xyz/v1",
                },
                "ovhcloud": {
                    "enabled": True,
                    "priority": 36,
                    "endpoint": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
                },
                "perplexity": {
                    "enabled": True,
                    "priority": 37,
                    "endpoint": "https://api.perplexity.ai/v1",
                },
                "novita": {
                    "enabled": True,
                    "priority": 38,
                    "endpoint": "https://api.novita.ai/openai",
                },
                "baseten": {
                    "enabled": True,
                    "priority": 39,
                    "endpoint": "https://inference.baseten.co/v1",
                },
                "naga": {"enabled": True, "priority": 40, "endpoint": "https://api.naga.ac/v1"},
                "nebius": {
                    "enabled": True,
                    "priority": 41,
                    "endpoint": "https://api.tokenfactory.nebius.com/v1",
                },
                "friendli": {
                    "enabled": True,
                    "priority": 42,
                    "endpoint": "https://api.friendli.ai/serverless/v1",
                },
                "fastrouter": {
                    "enabled": True,
                    "priority": 43,
                    "endpoint": "https://go.fastrouter.ai/api/v1",
                },
                "crusoe": {"enabled": True, "priority": 44, "endpoint": "https://api.crusoe.ai/v1"},
                "atoma": {"enabled": True, "priority": 45, "endpoint": "https://api.atoma.network/v1"},
                "parasail": {
                    "enabled": True,
                    "priority": 46,
                    "endpoint": "https://api.saas.parasail.io/v1",
                },
                "inference_net": {
                    "enabled": True,
                    "priority": 47,
                    "endpoint": "https://api.inference.net/v1",
                },
                "near_ai": {
                    "enabled": True,
                    "priority": 48,
                    "endpoint": "https://cloud-api.near.ai/v1",
                },
                "aai": {"enabled": True, "priority": 49, "endpoint": "https://api.a.ai/v1"},
                "aimlapi": {
                    "enabled": True,
                    "priority": 50,
                    "endpoint": "https://api.aimlapi.com/v1",
                },
                "vultr": {
                    "enabled": True,
                    "priority": 51,
                    "endpoint": "https://api.vultrinference.com/v1",
                },
                "together": {"enabled": True, "priority": 27, "endpoint": "https://api.together.xyz/v1"},
                "cerebras": {"enabled": True, "priority": 28, "endpoint": "https://api.cerebras.ai/v1"},
                "cloudflare": {
                    "enabled": True,
                    "priority": 29,
                    "endpoint": "https://api.cloudflare.com/client/v4",
                    "account_id": "acc-123",
                },
                "openrouter": {"enabled": True, "priority": 30, "endpoint": "https://openrouter.ai/api/v1"},
                "fireworks": {
                    "enabled": True,
                    "priority": 35,
                    "endpoint": "https://api.fireworks.ai/inference/v1",
                },
                "deepinfra": {
                    "enabled": True,
                    "priority": 36,
                    "endpoint": "https://api.deepinfra.com/v1/openai",
                },
                "siliconflow": {
                    "enabled": True,
                    "priority": 47,
                    "endpoint": "https://api.siliconflow.cn/v1",
                },
                "huggingface": {
                    "enabled": True,
                    "priority": 48,
                    "endpoint": "https://router.huggingface.co/v1",
                },
                "local_vllm": {
                    "enabled": True,
                    "priority": 100,
                    "adapter": "openai_compatible",
                    "endpoint": "http://127.0.0.1:8000/v1",
                    "auth_required": False,
                },
                "jan": {
                    "enabled": True,
                    "priority": 84,
                    "adapter": "openai_compatible",
                    "endpoint": "http://127.0.0.1:1337/v1",
                    "auth_required": False,
                },
                "litellm": {
                    "enabled": True,
                    "priority": 87,
                    "adapter": "openai_compatible",
                    "endpoint": "http://127.0.0.1:4000/v1",
                    "auth_required": False,
                },
            }
        }
    )

    adapters = build_provider_registry(cfg)

    assert isinstance(adapters["openai"], OpenAIAdapter)
    assert isinstance(adapters["anthropic"], AnthropicAdapter)
    assert isinstance(adapters["azure_openai"], AzureOpenAIAdapter)
    assert isinstance(adapters["bedrock"], BedrockAdapter)
    assert isinstance(adapters["vertex_ai"], VertexAIAdapter)
    assert isinstance(adapters["gemini"], GeminiAdapter)
    assert isinstance(adapters["github"], GitHubModelsAdapter)
    assert isinstance(adapters["mistral"], MistralAdapter)
    assert isinstance(adapters["groq"], GroqAdapter)
    assert isinstance(adapters["deepseek"], DeepSeekAdapter)
    assert isinstance(adapters["xai"], XAIAdapter)
    assert isinstance(adapters["cohere"], CohereAdapter)
    assert isinstance(adapters["moonshot"], MoonshotAdapter)
    assert isinstance(adapters["sambanova"], SambaNovaAdapter)
    assert isinstance(adapters["nvidia"], NVIDIAAdapter)
    assert isinstance(adapters["zhipuai"], ZhipuAIAdapter)
    assert isinstance(adapters["zai"], ZAIAdapter)
    assert isinstance(adapters["featherless"], FeatherlessAdapter)
    assert isinstance(adapters["hyperbolic"], HyperbolicAdapter)
    assert isinstance(adapters["ovhcloud"], OVHcloudAdapter)
    assert isinstance(adapters["perplexity"], PerplexityAdapter)
    assert isinstance(adapters["novita"], NovitaAdapter)
    assert isinstance(adapters["baseten"], BasetenAdapter)
    assert isinstance(adapters["naga"], NagaAdapter)
    assert isinstance(adapters["nebius"], NebiusAdapter)
    assert isinstance(adapters["friendli"], FriendliAdapter)
    assert isinstance(adapters["fastrouter"], FastRouterAdapter)
    assert isinstance(adapters["crusoe"], CrusoeAdapter)
    assert isinstance(adapters["atoma"], AtomaAdapter)
    assert isinstance(adapters["parasail"], ParasailAdapter)
    assert isinstance(adapters["inference_net"], InferenceNetAdapter)
    assert isinstance(adapters["near_ai"], NearAIAdapter)
    assert isinstance(adapters["aai"], AAIAdapter)
    assert isinstance(adapters["aimlapi"], AIMLAPIAdapter)
    assert isinstance(adapters["vultr"], VultrAdapter)
    assert isinstance(adapters["together"], TogetherAdapter)
    assert isinstance(adapters["cerebras"], CerebrasAdapter)
    assert isinstance(adapters["cloudflare"], CloudflareWorkersAIAdapter)
    assert isinstance(adapters["openrouter"], OpenRouterAdapter)
    assert isinstance(adapters["fireworks"], FireworksAdapter)
    assert isinstance(adapters["deepinfra"], DeepInfraAdapter)
    assert isinstance(adapters["siliconflow"], SiliconFlowAdapter)
    assert isinstance(adapters["huggingface"], HuggingFaceAdapter)
    assert isinstance(adapters["local_vllm"], OpenAICompatibleAdapter)
    assert isinstance(adapters["jan"], OpenAICompatibleAdapter)
    assert isinstance(adapters["litellm"], OpenAICompatibleAdapter)


def test_custom_openai_compatible_adapter_can_skip_auth_header() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "providers": {
                "local_vllm": {
                    "enabled": True,
                    "adapter": "openai_compatible",
                    "endpoint": "http://127.0.0.1:8000/v1",
                    "auth_required": False,
                    "keys": [{"id": "local-vllm", "key": "unused"}],
                }
            }
        }
    )
    adapter = build_provider_registry(cfg)["local_vllm"]

    headers = adapter._build_headers(cfg.providers["local_vllm"].keys[0])

    assert headers["Content-Type"] == "application/json"
    assert "Authorization" not in headers
