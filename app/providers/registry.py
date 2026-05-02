"""Provider adapter registry and factory."""

from __future__ import annotations

from app.config.models import GatewayConfig
from app.providers.atoma import AtomaAdapter
from app.providers.base import ProviderAdapter
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
from app.providers.google_code_assist import GoogleCodeAssistAdapter
from app.providers.github_models import GitHubModelsAdapter
from app.providers.groq import GroqAdapter
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
from app.providers.aai import AAIAdapter
from app.providers.aimlapi import AIMLAPIAdapter
from app.providers.sambanova import SambaNovaAdapter
from app.providers.siliconflow import SiliconFlowAdapter
from app.providers.together import TogetherAdapter
from app.providers.vertex_ai import VertexAIAdapter
from app.providers.vultr import VultrAdapter
from app.providers.xai import XAIAdapter
from app.providers.zai import ZAIAdapter
from app.providers.zhipuai import ZhipuAIAdapter


def build_provider_registry(config: GatewayConfig) -> dict[str, ProviderAdapter]:
    adapters: dict[str, ProviderAdapter] = {}
    for name, provider_cfg in config.providers.items():
        if not provider_cfg.enabled:
            continue
        if name == "openai":
            adapters[name] = OpenAIAdapter(provider_cfg)
        elif name == "anthropic":
            adapters[name] = AnthropicAdapter(provider_cfg)
        elif name == "azure_openai":
            adapters[name] = AzureOpenAIAdapter(provider_cfg)
        elif name == "bedrock":
            adapters[name] = BedrockAdapter(provider_cfg)
        elif name == "vertex_ai":
            adapters[name] = VertexAIAdapter(provider_cfg)
        elif name == "gemini":
            adapters[name] = GeminiAdapter(provider_cfg)
        elif name == "google_code_assist":
            adapters[name] = GoogleCodeAssistAdapter(provider_cfg)
        elif name == "github":
            adapters[name] = GitHubModelsAdapter(provider_cfg)
        elif name == "mistral":
            adapters[name] = MistralAdapter(provider_cfg)
        elif name == "deepseek":
            adapters[name] = DeepSeekAdapter(provider_cfg)
        elif name == "xai":
            adapters[name] = XAIAdapter(provider_cfg)
        elif name == "fireworks":
            adapters[name] = FireworksAdapter(provider_cfg)
        elif name == "deepinfra":
            adapters[name] = DeepInfraAdapter(provider_cfg)
        elif name == "sambanova":
            adapters[name] = SambaNovaAdapter(provider_cfg)
        elif name == "nvidia":
            adapters[name] = NVIDIAAdapter(provider_cfg)
        elif name == "moonshot":
            adapters[name] = MoonshotAdapter(provider_cfg)
        elif name == "siliconflow":
            adapters[name] = SiliconFlowAdapter(provider_cfg)
        elif name == "huggingface":
            adapters[name] = HuggingFaceAdapter(provider_cfg)
        elif name == "cohere":
            adapters[name] = CohereAdapter(provider_cfg)
        elif name == "zhipuai":
            adapters[name] = ZhipuAIAdapter(provider_cfg)
        elif name == "zai":
            adapters[name] = ZAIAdapter(provider_cfg)
        elif name == "featherless":
            adapters[name] = FeatherlessAdapter(provider_cfg)
        elif name == "hyperbolic":
            adapters[name] = HyperbolicAdapter(provider_cfg)
        elif name == "ovhcloud":
            adapters[name] = OVHcloudAdapter(provider_cfg)
        elif name == "perplexity":
            adapters[name] = PerplexityAdapter(provider_cfg)
        elif name == "novita":
            adapters[name] = NovitaAdapter(provider_cfg)
        elif name == "baseten":
            adapters[name] = BasetenAdapter(provider_cfg)
        elif name == "naga":
            adapters[name] = NagaAdapter(provider_cfg)
        elif name == "nebius":
            adapters[name] = NebiusAdapter(provider_cfg)
        elif name == "friendli":
            adapters[name] = FriendliAdapter(provider_cfg)
        elif name == "fastrouter":
            adapters[name] = FastRouterAdapter(provider_cfg)
        elif name == "crusoe":
            adapters[name] = CrusoeAdapter(provider_cfg)
        elif name == "atoma":
            adapters[name] = AtomaAdapter(provider_cfg)
        elif name == "parasail":
            adapters[name] = ParasailAdapter(provider_cfg)
        elif name == "inference_net":
            adapters[name] = InferenceNetAdapter(provider_cfg)
        elif name == "near_ai":
            adapters[name] = NearAIAdapter(provider_cfg)
        elif name == "aai":
            adapters[name] = AAIAdapter(provider_cfg)
        elif name == "aimlapi":
            adapters[name] = AIMLAPIAdapter(provider_cfg)
        elif name == "vultr":
            adapters[name] = VultrAdapter(provider_cfg)
        elif name == "groq":
            adapters[name] = GroqAdapter(provider_cfg)
        elif name == "together":
            adapters[name] = TogetherAdapter(provider_cfg)
        elif name == "cerebras":
            adapters[name] = CerebrasAdapter(provider_cfg)
        elif name == "cloudflare":
            adapters[name] = CloudflareWorkersAIAdapter(provider_cfg)
        elif name == "openrouter":
            adapters[name] = OpenRouterAdapter(provider_cfg)
        elif provider_cfg.adapter == "openai_compatible":
            adapters[name] = OpenAICompatibleAdapter(provider_name=name, config=provider_cfg)
    return adapters
