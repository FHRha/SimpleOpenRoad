# SimpleOpenRoad

Self-hosted OpenAI-compatible AI gateway with automatic routing, provider failover, multi-key management, generated model aliases, inventory refresh, diagnostics, and runtime quarantine for broken models.

Run one stable `/v1` endpoint for your apps and coding agents while SimpleOpenRoad routes requests across providers such as Gemini, GitHub Models, Groq, Cloudflare Workers AI, OpenRouter, Together AI, and Cerebras.

> [!WARNING]
> Provider support in SimpleOpenRoad means the adapter, routing, and inventory integration exist in the project. It does not guarantee that every listed provider or every discovered model will work correctly in every account. Real behavior still depends on provider-side billing, region limits, account permissions, deployment settings, model availability, and upstream API changes. Validate the providers you actually plan to use with `sor providers test`, `sor providers inventory --refresh`, and route preview before relying on them in production.

## Why Use It

SimpleOpenRoad is useful when your tools expect an OpenAI-compatible API, but you do not want to depend on one provider, one key, or one model.

It helps with:

- Provider outages: switch to another provider when a request fails.
- Rate limits and bad keys: track key state, cooldowns, and failover.
- Unstable models: quarantine models that repeatedly fail instead of retrying them every request.
- Agent clients: accept OpenAI-style chat payloads, streaming, tools, and Cline-like requests.
- Operations: validate keys, refresh model inventory, preview routes, inspect diagnostics, and manage everything from a terminal panel.

## Feature Highlights

| Area | What SimpleOpenRoad Does |
|---|---|
| OpenAI-compatible API | Exposes `/v1/chat/completions`, `/v1/responses`, `/v1/models`-style usage for compatible clients. |
| Generated aliases | Builds aliases such as `auto/fast`, `auto/general`, `auto/code`, and media aliases from live provider inventory. |
| Multi-provider routing | Routes across configured providers and keys using priority, adaptive profiles, retries, and fallback policy. |
| Key lifecycle | Tracks key health, runtime status, cooldowns, failures, successes, and latency. |
| Model quarantine | Temporarily skips models that repeatedly fail, with configurable TTLs and provider/model overrides. |
| Inventory refresh | Discovers provider models, capabilities, modalities, context sizes, and generated aliases. |
| Terminal operations | `sor` opens an interactive management panel for setup, validation, testing, routing, and service operations. |

## Quick Start

### Linux Release Install

```bash
curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash
```

Then open the terminal panel:

```bash
sor
```

Recommended first path:

```text
Providers and keys -> Add provider key
Gateway -> API access token and test
```

### Source Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
cp config/config.example.yaml config/config.yaml
sor start --config-path config/config.yaml
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
Copy-Item config\config.example.yaml config\config.yaml
sor start --config-path config/config.yaml
```

## First Client Configuration

Use these settings in OpenAI-compatible clients, coding agents, and local tools. See [Getting Started](docs/GETTING_STARTED.md) for the full first-run flow.

```text
Base URL: http://<SERVER_IP>:12345/v1
API Key:  <MASTER_API_KEY>
Model:    auto/general
```

`MASTER_API_KEY` is stored in `.env`. The terminal panel can show or regenerate it:

```text
sor -> Gateway -> API access token and test
```

## Example Request

```bash
MASTER_API_KEY="$(grep '^MASTER_API_KEY=' .env | cut -d= -f2-)"

curl -sS -X POST "http://127.0.0.1:12345/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${MASTER_API_KEY}" \
  --data-binary @- <<'JSON'
{
  "model": "auto/fast",
  "messages": [
    {"role": "user", "content": "Hello"}
  ]
}
JSON
```

## Model Aliases

Generated aliases are built from the current provider inventory and available keys. See [Routing and Model Selection](docs/ROUTING.md) for adaptive routing, route memory, free-route behavior, and model quarantine.

| Alias | Use For |
|---|---|
| `auto/fast` | Lightweight, cheap, low-latency requests. |
| `auto/general` | Default everyday chat and general tasks. |
| `auto/reasoning` | Harder reasoning, analysis, and long-context work. |
| `auto/code` | Coding, debugging, refactoring, and repository work. |
| `auto/free` | Strict free-only route when free-capable models exist. |
| `auto/free-cheap` | Free-first route with cheap fallback only when a free candidate exists. |
| `auto/image/default` | Image-capable models discovered in inventory. |
| `auto/audio/default` | Audio-capable models discovered in inventory. |
| `auto/video/default` | Video-capable models discovered in inventory. |

Direct routing is also supported:

```text
openrouter/openai/gpt-5.4-mini
cloudflare/@cf/openai/gpt-oss-20b
together/arize-ai/qwen-2-1.5b-instruct
```

If you send an exact model id without `provider/`, SimpleOpenRoad tries that model id across configured providers.

## Supported Providers

| Provider | Notes |
|---|---|
| [OpenAI](https://platform.openai.com/settings/organization/api-keys) | First-class OpenAI API adapter for chat, streaming, responses, tools, and model inventory. |
| [Anthropic](https://console.anthropic.com/settings/keys) | Claude through Anthropic's OpenAI-compatible endpoint for chat, streaming, tools, and model inventory. |
| [Azure OpenAI](https://portal.azure.com/) | Deployment-scoped Azure OpenAI chat adapter using `api-key` auth and Azure `api-version` URLs. |
| [Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html) | OpenAI-compatible Bedrock runtime endpoint using Amazon Bedrock API keys. |
| [Google Vertex AI](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/openai) | OpenAI-compatible Vertex endpoint using Google Cloud auth, access tokens, or service account credentials. |
| [Gemini](https://aistudio.google.com/apikey) | Native adapter for Google Gemini models. Create or view keys in Google AI Studio. |
| [GitHub Models](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) | OpenAI-compatible chat and catalog adapter. Uses GitHub personal access tokens. |
| [Mistral AI](https://console.mistral.ai/api-keys) | OpenAI-compatible chat, streaming, and model inventory. |
| [Groq](https://console.groq.com/keys) | OpenAI-compatible chat and streaming. Create keys in GroqCloud. |
| [DeepSeek](https://platform.deepseek.com/api_keys) | OpenAI-compatible chat and reasoning models. |
| [xAI](https://console.x.ai/) | OpenAI-compatible Grok chat/responses endpoint. |
| [Cohere](https://dashboard.cohere.com/api-keys) | OpenAI-compatible Cohere compatibility API for chat, streaming, tools, embeddings, and transcription surfaces. |
| [Moonshot AI / Kimi](https://platform.moonshot.ai/console/api-keys) | OpenAI-compatible Kimi endpoint for chat and long-context models. |
| [SambaNova](https://cloud.sambanova.ai/apis) | OpenAI-compatible SambaCloud endpoint. |
| [NVIDIA NIM](https://build.nvidia.com/) | OpenAI-compatible hosted NIM endpoint through NVIDIA build/integrate APIs. |
| [ZhipuAI / BigModel](https://bigmodel.cn/usercenter/proj-mgmt/apikeys) | OpenAI-compatible GLM endpoint from ZhipuAI. |
| [Z.AI](https://z.ai/manage-apikey/apikey-list) | OpenAI-compatible GLM endpoint from Z.AI. |
| [Featherless](https://featherless.ai/account/api-keys) | OpenAI-compatible hosted open-model catalog. |
| [Hyperbolic](https://app.hyperbolic.xyz/settings) | OpenAI-compatible inference endpoint for Hyperbolic-hosted models. |
| [OVHcloud AI Endpoints](https://www.ovhcloud.com/en/public-cloud/ai-endpoints/) | OpenAI-compatible European hosted AI endpoints. |
| [Perplexity](https://www.perplexity.ai/settings/api) | Perplexity Sonar/Agent API support for search-grounded chat and OpenAI-compatible model discovery. |
| [Novita AI](https://novita.ai/settings/key-management) | OpenAI-compatible hosted LLM endpoint. |
| [Baseten](https://app.baseten.co/settings/api_keys) | OpenAI-compatible Baseten Model APIs; uses Baseten's `Api-Key` auth scheme. |
| [NagaAI](https://docs.naga.ac/) | OpenAI-compatible chat, streaming, tools, multimodal, and model catalog surfaces. |
| [Nebius Token Factory](https://tokenfactory.nebius.com/) | OpenAI-compatible inference endpoint for Nebius-hosted models. |
| [Friendli](https://friendli.ai/docs/guides/openai-compatibility) | OpenAI-compatible serverless and dedicated endpoints. |
| [FastRouter](https://docs.fastrouter.ai/api-reference/chat-request-api) | OpenAI-compatible routing endpoint for multi-provider model ids. |
| [Crusoe Managed Inference](https://docs.crusoecloud.com/managed-inference/getting-started-with-managed-inference/) | OpenAI-compatible Crusoe text model inference. |
| [Atoma](https://docs.atoma.ai/cloud-api-reference/get-started) | OpenAI-compatible decentralized inference API. |
| [Parasail](https://docs.parasail.io/parasail-docs/batch/api-reference) | OpenAI-compatible serverless model endpoint. |
| [Inference.net](https://docs.inference.net/api/overview) | OpenAI-compatible hosted inference API for chat, streaming, tools, vision, and embeddings. |
| [NEAR AI Cloud](https://docs.near.ai/cloud/guides/openai-compatibility/) | OpenAI-compatible gateway and direct-completions endpoints. |
| [a.ai](https://chat.a.ai/api) | OpenAI-compatible `chat/completions` and `models` API for apex-1. |
| [AI/ML API](https://docs.aimlapi.com/integrations/aider) | OpenAI-compatible multi-provider routing endpoint. |
| [Vultr Serverless Inference](https://docs.vultr.com/how-to-use-vultr-cloud-inference-in-node-js) | OpenAI-compatible Vultr hosted inference API. |
| [Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/get-started/rest-api/) | Account-scoped Workers AI support; Cloudflare account ID can be stored per key. |
| [OpenRouter](https://openrouter.ai/settings/keys) | OpenAI-compatible routing and special handling for free-tier routes. |
| [Together AI](https://docs.together.ai/docs/api-keys-authentication) | OpenAI-compatible catalog and chat; available models depend on account billing and provider availability. |
| [Cerebras](https://inference-docs.cerebras.ai/api-reference/authentication) | OpenAI-compatible chat support. Create keys in the Cerebras Inference Cloud Console. |
| [Fireworks AI](https://docs.fireworks.ai/api-reference/introduction) | OpenAI-compatible inference endpoint for Fireworks-hosted models. |
| [DeepInfra](https://deepinfra.com/dash/api_keys) | OpenAI-compatible hosted open-model inference endpoint. |
| [SiliconFlow](https://cloud.siliconflow.cn/account/ak) | OpenAI-compatible SiliconCloud endpoint. |
| [Hugging Face Inference Providers](https://huggingface.co/settings/tokens) | OpenAI-compatible router for Hugging Face Inference Providers. |
| Local presets | Disabled-by-default presets for Ollama, LM Studio, LocalAI, vLLM, Jan, llama.cpp server, text-generation-webui, and LiteLLM Proxy. |
| Custom OpenAI-compatible | Connect local or hosted OpenAI-compatible endpoints such as vLLM, LM Studio, or LocalAI. |

See [docs/PROVIDERS.md](docs/PROVIDERS.md) for provider-specific setup and caveats.

## Runtime Behavior

SimpleOpenRoad tracks runtime state separately from static configuration. The detailed behavior is documented in [Routing and Model Selection](docs/ROUTING.md), and the tunable YAML settings are in [Config Reference](docs/CONFIG_REFERENCE.md).

- Key cooldown: temporarily avoids keys that hit rate limits or repeated failures.
- Route memory: remembers successful models per alias/profile/context bucket and moves them forward.
- Model quarantine: after repeated model failures, temporarily skips that `provider/model`.
- Diagnostics: automatic tests and route preview show attempted, skipped, and failed candidates.

Default model quarantine behavior:

| Error Class | Default TTL |
|---|---:|
| `rate_limit` | 30 minutes |
| `provider_unavailable` | 10 minutes |
| `network_timeout` | 5 minutes |
| `malformed_response` | 6 hours |
| `unsupported_model` | 24 hours |
| `unknown` | 30 minutes |

Model quarantine settings are available in:

```text
sor -> Settings -> Model quarantine settings
```

See [docs/ROUTING.md](docs/ROUTING.md) for the full routing model.

## Useful Commands

```bash
sor
sor providers test
sor providers inventory --refresh
sor providers consistency
sor routes preview --model auto/general
sor keys validate
sor config validate
sor update
sor uninstall --full
```

## Documentation

- [Getting Started](docs/GETTING_STARTED.md)
- [Client Configuration](docs/CLIENTS.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Providers](docs/PROVIDERS.md)
- [Routing and Model Selection](docs/ROUTING.md)
- [Admin Guide](docs/ADMIN_GUIDE.md)
- [Config Reference](docs/CONFIG_REFERENCE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Project Structure](docs/PROJECT_STRUCTURE.md)
- [Test Plan](docs/TEST_PLAN.md)
- [Release Guide](docs/RELEASE.md)

## Updating

Update an installed package while preserving `.env`, `config/config.yaml`, provider keys, and `data/`:

```bash
sor update
```

Install a specific release:

```bash
sor update --version v0.3.0
```

Use a prerelease channel:

```bash
sor update --channel prerelease
```

Test unreleased changes from `main`:

```bash
sor update --ref main
```

## License

Apache-2.0. See [LICENSE](LICENSE).
