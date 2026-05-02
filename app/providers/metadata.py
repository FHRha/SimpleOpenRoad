"""Provider catalog metadata shared by CLI and documentation helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderMetadata:
    id: str
    display_name: str
    aliases: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    api_key_url: str | None = None


FEATURED_PROVIDER_ORDER = (
    "openai",
    "anthropic",
    "azure_openai",
    "bedrock",
    "vertex_ai",
    "gemini",
    "google_code_assist",
    "github",
    "openrouter",
    "groq",
    "cloudflare",
    "mistral",
    "deepseek",
    "xai",
    "ollama",
)
FEATURED_PROVIDER_SET = set(FEATURED_PROVIDER_ORDER)
OTHER_PROVIDER_DISPLAY_LIMIT = 12

PROVIDER_METADATA: dict[str, ProviderMetadata] = {
    "aai": ProviderMetadata(
        id="aai",
        display_name="a.ai",
        aliases=("apex", "apex-1"),
        groups=("other", "paid"),
        api_key_url="https://chat.a.ai/api",
    ),
    "aimlapi": ProviderMetadata(
        id="aimlapi",
        display_name="AI/ML API",
        aliases=("ai ml api", "aiml"),
        groups=("other", "paid"),
        api_key_url="https://aimlapi.com/app/keys",
    ),
    "anthropic": ProviderMetadata(
        id="anthropic",
        display_name="Anthropic / Claude",
        aliases=("claude", "ant"),
        groups=("featured", "paid"),
        api_key_url="https://console.anthropic.com/settings/keys",
    ),
    "azure_openai": ProviderMetadata(
        id="azure_openai",
        display_name="Azure OpenAI",
        aliases=("azure", "azure ai", "microsoft"),
        groups=("featured", "enterprise", "paid"),
        api_key_url="https://portal.azure.com/",
    ),
    "atoma": ProviderMetadata(
        id="atoma",
        display_name="Atoma",
        aliases=("atoma network",),
        groups=("other", "paid"),
        api_key_url="https://cloud.atoma.network/",
    ),
    "baseten": ProviderMetadata(
        id="baseten",
        display_name="Baseten",
        aliases=("base ten",),
        groups=("other", "paid"),
        api_key_url="https://app.baseten.co/settings/api_keys",
    ),
    "bedrock": ProviderMetadata(
        id="bedrock",
        display_name="Amazon Bedrock",
        aliases=("aws bedrock", "amazon bedrock"),
        groups=("featured", "enterprise", "paid"),
        api_key_url="https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html",
    ),
    "cerebras": ProviderMetadata(
        id="cerebras",
        display_name="Cerebras Inference",
        groups=("other", "paid"),
        api_key_url="https://cloud.cerebras.ai/platform",
    ),
    "cloudflare": ProviderMetadata(
        id="cloudflare",
        display_name="Cloudflare Workers AI",
        aliases=("cf", "workers"),
        groups=("featured", "paid"),
        api_key_url="https://dash.cloudflare.com/profile/api-tokens",
    ),
    "cohere": ProviderMetadata(
        id="cohere",
        display_name="Cohere",
        groups=("other", "paid"),
        api_key_url="https://dashboard.cohere.com/api-keys",
    ),
    "crusoe": ProviderMetadata(
        id="crusoe",
        display_name="Crusoe Managed Inference",
        aliases=("crusoe cloud",),
        groups=("other", "paid"),
        api_key_url="https://console.crusoecloud.com/",
    ),
    "custom_openai": ProviderMetadata(
        id="custom_openai",
        display_name="Custom OpenAI-compatible endpoint",
        aliases=("custom", "openai compatible"),
        groups=("other", "proxy"),
    ),
    "deepinfra": ProviderMetadata(
        id="deepinfra",
        display_name="DeepInfra",
        groups=("other", "paid"),
        api_key_url="https://deepinfra.com/dash/api_keys",
    ),
    "deepseek": ProviderMetadata(
        id="deepseek",
        display_name="DeepSeek",
        groups=("featured", "paid"),
        api_key_url="https://platform.deepseek.com/api_keys",
    ),
    "featherless": ProviderMetadata(
        id="featherless",
        display_name="Featherless",
        groups=("other", "paid"),
        api_key_url="https://featherless.ai/account/api-keys",
    ),
    "fastrouter": ProviderMetadata(
        id="fastrouter",
        display_name="FastRouter",
        aliases=("fast router",),
        groups=("other", "paid"),
        api_key_url="https://go.fastrouter.ai/",
    ),
    "fireworks": ProviderMetadata(
        id="fireworks",
        display_name="Fireworks AI",
        groups=("other", "paid"),
        api_key_url="https://fireworks.ai/account/api-keys",
    ),
    "friendli": ProviderMetadata(
        id="friendli",
        display_name="Friendli",
        aliases=("friendli ai", "friendli suite"),
        groups=("other", "paid"),
        api_key_url="https://suite.friendli.ai/",
    ),
    "gemini": ProviderMetadata(
        id="gemini",
        display_name="Google Gemini",
        aliases=("google", "ai studio"),
        groups=("featured", "free-tier", "paid"),
        api_key_url="https://aistudio.google.com/app/apikey",
    ),
    "google_code_assist": ProviderMetadata(
        id="google_code_assist",
        display_name="Google AI Pro / Code Assist OAuth",
        aliases=("google ai pro", "code assist", "gemini cli", "google oauth"),
        groups=("featured", "experimental", "subscription"),
        api_key_url="https://google-gemini.github.io/gemini-cli/docs/get-started/authentication.html",
    ),
    "github": ProviderMetadata(
        id="github",
        display_name="GitHub Models",
        aliases=("gh", "github models"),
        groups=("featured", "free-tier"),
        api_key_url="https://github.com/settings/personal-access-tokens",
    ),
    "groq": ProviderMetadata(
        id="groq",
        display_name="Groq",
        groups=("featured", "free-tier", "paid"),
        api_key_url="https://console.groq.com/keys",
    ),
    "huggingface": ProviderMetadata(
        id="huggingface",
        display_name="Hugging Face Inference Providers",
        aliases=("hf", "hugging face"),
        groups=("other", "free-tier", "paid"),
        api_key_url="https://huggingface.co/settings/tokens",
    ),
    "hyperbolic": ProviderMetadata(
        id="hyperbolic",
        display_name="Hyperbolic",
        groups=("other", "paid"),
        api_key_url="https://app.hyperbolic.xyz/settings",
    ),
    "inference_net": ProviderMetadata(
        id="inference_net",
        display_name="Inference.net",
        aliases=("inference net",),
        groups=("other", "paid"),
        api_key_url="https://docs.inference.net/api/overview",
    ),
    "jan": ProviderMetadata(
        id="jan",
        display_name="Jan",
        groups=("local",),
        api_key_url="https://jan.ai/",
    ),
    "litellm": ProviderMetadata(
        id="litellm",
        display_name="LiteLLM Proxy",
        aliases=("lite llm", "proxy"),
        groups=("local", "proxy"),
        api_key_url="https://docs.litellm.ai/docs/proxy/virtual_keys",
    ),
    "llamacpp": ProviderMetadata(
        id="llamacpp",
        display_name="llama.cpp server",
        aliases=("llama.cpp", "llama-cpp", "llama server"),
        groups=("local",),
        api_key_url="https://github.com/ggml-org/llama.cpp",
    ),
    "lmstudio": ProviderMetadata(
        id="lmstudio",
        display_name="LM Studio",
        aliases=("lm studio",),
        groups=("local",),
        api_key_url="https://lmstudio.ai/",
    ),
    "localai": ProviderMetadata(
        id="localai",
        display_name="LocalAI",
        groups=("local",),
        api_key_url="https://localai.io/",
    ),
    "mistral": ProviderMetadata(
        id="mistral",
        display_name="Mistral AI",
        groups=("featured", "paid"),
        api_key_url="https://console.mistral.ai/api-keys",
    ),
    "moonshot": ProviderMetadata(
        id="moonshot",
        display_name="Moonshot AI / Kimi",
        aliases=("kimi",),
        groups=("other", "paid"),
        api_key_url="https://platform.moonshot.ai/console/api-keys",
    ),
    "naga": ProviderMetadata(
        id="naga",
        display_name="NagaAI",
        aliases=("naga ai",),
        groups=("other", "paid"),
        api_key_url="https://chat.naga.ac/",
    ),
    "near_ai": ProviderMetadata(
        id="near_ai",
        display_name="NEAR AI Cloud",
        aliases=("near", "near ai"),
        groups=("other", "paid"),
        api_key_url="https://cloud.near.ai/",
    ),
    "nebius": ProviderMetadata(
        id="nebius",
        display_name="Nebius Token Factory",
        aliases=("nebius ai", "token factory"),
        groups=("other", "paid"),
        api_key_url="https://tokenfactory.nebius.com/",
    ),
    "nvidia": ProviderMetadata(
        id="nvidia",
        display_name="NVIDIA NIM",
        aliases=("nim",),
        groups=("other", "free-tier", "paid"),
        api_key_url="https://build.nvidia.com/",
    ),
    "novita": ProviderMetadata(
        id="novita",
        display_name="Novita AI",
        aliases=("novita ai",),
        groups=("other", "paid"),
        api_key_url="https://novita.ai/settings/key-management",
    ),
    "ollama": ProviderMetadata(
        id="ollama",
        display_name="Ollama",
        groups=("featured", "local"),
        api_key_url="https://ollama.com/",
    ),
    "openai": ProviderMetadata(
        id="openai",
        display_name="OpenAI",
        groups=("featured", "paid"),
        api_key_url="https://platform.openai.com/api-keys",
    ),
    "openrouter": ProviderMetadata(
        id="openrouter",
        display_name="OpenRouter",
        aliases=("or",),
        groups=("featured", "free-tier", "paid"),
        api_key_url="https://openrouter.ai/settings/keys",
    ),
    "ovhcloud": ProviderMetadata(
        id="ovhcloud",
        display_name="OVHcloud AI Endpoints",
        groups=("other", "paid"),
        api_key_url="https://www.ovhcloud.com/en/public-cloud/ai-endpoints/",
    ),
    "parasail": ProviderMetadata(
        id="parasail",
        display_name="Parasail",
        groups=("other", "paid"),
        api_key_url="https://www.saas.parasail.io/",
    ),
    "perplexity": ProviderMetadata(
        id="perplexity",
        display_name="Perplexity",
        aliases=("sonar", "pplx", "search"),
        groups=("other", "search", "paid"),
        api_key_url="https://www.perplexity.ai/settings/api",
    ),
    "sambanova": ProviderMetadata(
        id="sambanova",
        display_name="SambaNova",
        groups=("other", "free-tier", "paid"),
        api_key_url="https://cloud.sambanova.ai/apis",
    ),
    "siliconflow": ProviderMetadata(
        id="siliconflow",
        display_name="SiliconFlow",
        groups=("other", "free-tier", "paid"),
        api_key_url="https://cloud.siliconflow.cn/account/ak",
    ),
    "textgenwebui": ProviderMetadata(
        id="textgenwebui",
        display_name="text-generation-webui",
        aliases=("oobabooga", "text generation webui"),
        groups=("local",),
        api_key_url="https://github.com/oobabooga/text-generation-webui",
    ),
    "together": ProviderMetadata(
        id="together",
        display_name="Together AI",
        groups=("other", "paid"),
        api_key_url="https://api.together.ai/settings/api-keys",
    ),
    "vllm": ProviderMetadata(
        id="vllm",
        display_name="vLLM",
        groups=("local",),
        api_key_url="https://docs.vllm.ai/",
    ),
    "vertex_ai": ProviderMetadata(
        id="vertex_ai",
        display_name="Google Vertex AI",
        aliases=("vertex", "vertex ai", "gcp"),
        groups=("featured", "enterprise", "paid"),
        api_key_url="https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/openai",
    ),
    "vultr": ProviderMetadata(
        id="vultr",
        display_name="Vultr Serverless Inference",
        aliases=("vultr inference",),
        groups=("other", "paid"),
        api_key_url="https://docs.vultr.com/how-to-use-vultr-cloud-inference-in-node-js",
    ),
    "xai": ProviderMetadata(
        id="xai",
        display_name="xAI / Grok",
        aliases=("grok",),
        groups=("featured", "paid"),
        api_key_url="https://console.x.ai/team/default/api-keys",
    ),
    "zai": ProviderMetadata(
        id="zai",
        display_name="Z.AI",
        aliases=("glm",),
        groups=("other", "paid"),
        api_key_url="https://docs.z.ai/",
    ),
    "zhipuai": ProviderMetadata(
        id="zhipuai",
        display_name="ZhipuAI / BigModel",
        aliases=("bigmodel", "glm", "chatglm"),
        groups=("other", "paid"),
        api_key_url="https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
    ),
}


def provider_category(provider_name: str) -> str:
    return "Featured" if provider_name in FEATURED_PROVIDER_SET else "Other"


def provider_display_name(provider_name: str) -> str:
    metadata = PROVIDER_METADATA.get(provider_name)
    return metadata.display_name if metadata else provider_name


def provider_aliases(provider_name: str) -> tuple[str, ...]:
    metadata = PROVIDER_METADATA.get(provider_name)
    return metadata.aliases if metadata else ()


def sorted_provider_names(provider_names: list[str]) -> list[str]:
    featured_index = {name: index for index, name in enumerate(FEATURED_PROVIDER_ORDER)}
    return sorted(
        provider_names,
        key=lambda name: (
            0 if name in FEATURED_PROVIDER_SET else 1,
            featured_index.get(name, 999),
            name,
        ),
    )


def provider_search_haystack(provider_name: str) -> str:
    values = [provider_name, provider_display_name(provider_name)]
    values.extend(provider_aliases(provider_name))
    return " ".join(values).lower()


def search_provider_names(provider_names: list[str], query: str) -> list[str]:
    normalized = query.strip().lower()
    if not normalized:
        return sorted_provider_names(provider_names)
    exact_alias_matches: list[str] = []
    fuzzy_matches: list[str] = []
    for provider in sorted_provider_names(provider_names):
        if normalized == provider.lower():
            exact_alias_matches.append(provider)
        elif normalized in provider_aliases(provider):
            exact_alias_matches.append(provider)
        elif normalized in provider_search_haystack(provider):
            fuzzy_matches.append(provider)
    return exact_alias_matches + fuzzy_matches
