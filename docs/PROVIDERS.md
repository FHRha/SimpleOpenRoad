# Providers

SimpleOpenRoad connects provider APIs behind one OpenAI-compatible gateway. Provider model catalogs are discovered into runtime inventory and used to generate aliases.

Provider support here means SimpleOpenRoad has an adapter and routing path for that provider. It does not mean every account, region, model, or pricing tier will work the same way. Always validate the providers and models you plan to use with:

```bash
sor providers test
sor providers inventory --refresh
sor routes preview --model auto/general
```

## Support Matrix

| Provider | Chat | Streaming | Tools | Inventory | API Key / Token |
|---|---:|---:|---:|---:|---|
| [OpenAI](https://platform.openai.com/settings/organization/api-keys) | yes | yes | yes | yes | OpenAI platform API keys. |
| [Anthropic](https://console.anthropic.com/settings/keys) | yes | yes | yes | yes | Anthropic Console API keys. |
| [Azure OpenAI](https://portal.azure.com/) | yes | yes | model-dependent | no | Azure OpenAI resource API key; model id is treated as deployment name. |
| [Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html) | yes | yes | model-dependent | yes | Amazon Bedrock API keys. |
| [Google Vertex AI](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/openai) | yes | yes | model-dependent | yes | Google Cloud auth via access token, service account JSON, or ADC. |
| [Gemini](https://aistudio.google.com/apikey) | yes | yes | model-dependent | yes | Google AI Studio API keys. |
| [Google OAuth for Gemini Code Assist](https://google-gemini.github.io/gemini-cli/docs/get-started/authentication.html) | yes | yes | experimental | yes | Direct Google OAuth for Gemini Code Assist / AI Pro accounts. Supports browser callback or manual code entry. |
| [GitHub Models](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) | yes | yes | model-dependent | yes | GitHub personal access token. |
| [Mistral AI](https://console.mistral.ai/api-keys) | yes | yes | model-dependent | yes | Mistral console API keys. |
| [Groq](https://console.groq.com/keys) | yes | yes | model-dependent | yes | GroqCloud API keys. |
| [DeepSeek](https://platform.deepseek.com/api_keys) | yes | yes | model-dependent | yes | DeepSeek platform API keys. |
| [xAI](https://console.x.ai/) | yes | yes | model-dependent | yes | xAI console API keys. |
| [Cohere](https://dashboard.cohere.com/api-keys) | yes | yes | yes | yes | Cohere dashboard API keys. |
| [Moonshot AI / Kimi](https://platform.moonshot.ai/console/api-keys) | yes | yes | model-dependent | yes | Moonshot platform API keys. |
| [SambaNova](https://cloud.sambanova.ai/apis) | yes | yes | model-dependent | yes | SambaCloud API keys. |
| [NVIDIA NIM](https://build.nvidia.com/) | yes | yes | model-dependent | yes | NVIDIA API keys. |
| [ZhipuAI / BigModel](https://bigmodel.cn/usercenter/proj-mgmt/apikeys) | yes | yes | model-dependent | yes | ZhipuAI API keys. |
| [Z.AI](https://z.ai/manage-apikey/apikey-list) | yes | yes | model-dependent | yes | Z.AI API keys. |
| [Featherless](https://featherless.ai/account/api-keys) | yes | yes | model-dependent | yes | Featherless API keys. |
| [Hyperbolic](https://app.hyperbolic.xyz/settings) | yes | yes | model-dependent | yes | Hyperbolic API keys. |
| [OVHcloud AI Endpoints](https://www.ovhcloud.com/en/public-cloud/ai-endpoints/) | yes | yes | model-dependent | yes | OVHcloud AI Endpoints API keys. |
| [Perplexity](https://www.perplexity.ai/settings/api) | yes | yes | no | yes | Perplexity API keys; chat uses Sonar API. |
| [Novita AI](https://novita.ai/settings/key-management) | yes | yes | model-dependent | yes | Novita API keys. |
| [Baseten](https://app.baseten.co/settings/api_keys) | yes | yes | model-dependent | yes | Baseten API keys; uses `Authorization: Api-Key ...`. |
| [NagaAI](https://docs.naga.ac/) | yes | yes | yes | yes | NagaAI API keys. |
| [Nebius Token Factory](https://tokenfactory.nebius.com/) | yes | yes | model-dependent | yes | Nebius API keys. |
| [Friendli](https://friendli.ai/docs/guides/openai-compatibility) | yes | yes | model-dependent | yes | Friendli tokens. |
| [FastRouter](https://docs.fastrouter.ai/api-reference/chat-request-api) | yes | yes | model-dependent | endpoint-dependent | FastRouter API keys. |
| [Crusoe Managed Inference](https://docs.crusoecloud.com/managed-inference/getting-started-with-managed-inference/) | yes | yes | model-dependent | endpoint-dependent | Crusoe Inference API tokens. |
| [Atoma](https://docs.atoma.ai/cloud-api-reference/get-started) | yes | yes | model-dependent | yes | Atoma bearer tokens. |
| [Parasail](https://docs.parasail.io/parasail-docs/batch/api-reference) | yes | yes | model-dependent | endpoint-dependent | Parasail API keys. |
| [Inference.net](https://docs.inference.net/api/overview) | yes | yes | yes | yes | Inference.net API keys. |
| [NEAR AI Cloud](https://docs.near.ai/cloud/guides/openai-compatibility/) | yes | yes | yes | yes | NEAR AI Cloud API keys. |
| [a.ai](https://chat.a.ai/api) | yes | yes | yes | yes | a.ai bearer keys. |
| [AI/ML API](https://docs.aimlapi.com/integrations/aider) | yes | yes | model-dependent | yes | AI/ML API keys. |
| [Vultr Serverless Inference](https://docs.vultr.com/how-to-use-vultr-cloud-inference-in-node-js) | yes | yes | model-dependent | yes | Vultr Serverless Inference API keys. |
| [Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/get-started/rest-api/) | yes | yes | model-dependent | yes | Workers AI API token plus Account ID. |
| [OpenRouter](https://openrouter.ai/settings/keys) | yes | yes | model-dependent | yes | OpenRouter workspace API keys. |
| [Together AI](https://docs.together.ai/docs/api-keys-authentication) | yes | yes | model-dependent | yes | Together project API keys. |
| [Cerebras](https://inference-docs.cerebras.ai/api-reference/authentication) | yes | yes | model-dependent | yes | Cerebras Inference Cloud Console keys. |
| [Fireworks AI](https://docs.fireworks.ai/api-reference/introduction) | yes | yes | model-dependent | yes | Fireworks API keys. |
| [DeepInfra](https://deepinfra.com/dash/api_keys) | yes | yes | model-dependent | yes | DeepInfra API tokens. |
| [SiliconFlow](https://cloud.siliconflow.cn/account/ak) | yes | yes | model-dependent | yes | SiliconCloud API keys. |
| [Hugging Face Inference Providers](https://huggingface.co/settings/tokens) | yes | yes | model-dependent | yes | Hugging Face tokens with Inference Providers permission. |
| Local presets | yes | yes | endpoint-dependent | endpoint-dependent | Ollama, LM Studio, LocalAI, vLLM, Jan, llama.cpp server, text-generation-webui, and LiteLLM Proxy presets are disabled by default. |
| Custom OpenAI-compatible | yes | yes | depends on endpoint | endpoint-dependent | Local or hosted OpenAI-compatible endpoint. |

Capabilities are inferred from provider metadata and model names, then corrected by filters, runtime failures, and overrides.

## Provider Configuration

Providers live under `providers` in `config/config.yaml`. See [Config Reference](CONFIG_REFERENCE.md) for all provider fields.

```yaml
providers:
  openrouter:
    enabled: true
    priority: 30
    endpoint: https://openrouter.ai/api/v1
    timeout_seconds: 45
    headers:
      HTTP-Referer: https://localhost
      X-Title: simple-open-road
    keys: []
```

Add keys through the CLI or terminal panel:

```bash
sor keys add --provider openrouter --key-id openrouter-main --secret <TOKEN>
```

## Provider Priority

Lower `priority` values are earlier in provider ordering for generated global aliases.

Provider priority is only one factor. Generated aliases, adaptive profiles, route memory, key health, context limits, and model quarantine can also affect effective order.

## Cloudflare Workers AI

Cloudflare URLs are account scoped:

```text
https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/...
```

SimpleOpenRoad supports provider-level and key-level account IDs. Prefer key-level account IDs when one installation uses multiple Cloudflare accounts. The Cloudflare REST guide explains creating a Workers AI token and copying the account ID.

```yaml
providers:
  cloudflare:
    endpoint: https://api.cloudflare.com/client/v4
    keys:
      - id: cloudflare-main
        key: <TOKEN>
        account_id: <ACCOUNT_ID>
```

CLI:

```bash
sor keys add \
  --provider cloudflare \
  --key-id cloudflare-main \
  --secret <TOKEN> \
  --account-id <ACCOUNT_ID>
```

Inventory tracks which key discovered each model, and routing uses matching keys for that model.

## OpenRouter

OpenRouter supports many upstream providers and free-suffixed models.

- `auto/free` is strict free-only.
- Free-tier rate limits may apply account-wide.
- SimpleOpenRoad detects OpenRouter free-tier rate-limit scope where possible and avoids paid fallback for `auto/free`.

Recommended headers:

```yaml
headers:
  HTTP-Referer: https://localhost
  X-Title: simple-open-road
```

## Azure OpenAI

Azure OpenAI is deployment scoped. The requested model id is used as the Azure deployment name.

```yaml
providers:
  azure_openai:
    enabled: true
    endpoint: https://YOUR_RESOURCE.openai.azure.com?api-version=2024-10-21
    keys:
      - id: azure-openai-main
        key: <TOKEN>
```

For a request using `model: azure_openai/gpt-4o-mini`, SimpleOpenRoad calls:

```text
https://YOUR_RESOURCE.openai.azure.com/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-10-21
```

You can also set a deployment template explicitly:

```yaml
endpoint: https://YOUR_RESOURCE.openai.azure.com/openai/deployments/{deployment}?api-version=2024-10-21
```

Azure does not expose the same simple `/models` inventory surface as most OpenAI-compatible providers. Use direct model ids or explicit routes for Azure deployments.

## Amazon Bedrock

Amazon Bedrock exposes an OpenAI-compatible runtime endpoint.

```yaml
providers:
  bedrock:
    enabled: true
    endpoint: https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1
    keys:
      - id: bedrock-main
        key: <TOKEN>
```

`key` is the Amazon Bedrock API key. This is not the AWS access key / secret key pair path.

## Google Vertex AI

Vertex AI exposes an OpenAI-compatible endpoint at the project/location OpenAPI endpoint:

```yaml
providers:
  vertex_ai:
    enabled: true
    endpoint: https://aiplatform.googleapis.com/v1/projects/YOUR_PROJECT/locations/global/endpoints/openapi
    keys:
      - id: vertex-main
        key: adc
```

`key` supports three modes:

- `adc` to use Application Default Credentials.
- Absolute path to a service account JSON file.
- A direct Google Cloud access token.

This provider refreshes Google auth tokens automatically when using ADC or a service account file.

## Perplexity

Perplexity has two OpenAI-compatible surfaces:

- Sonar chat uses `POST /v1/sonar`.
- Agent API and model discovery use `/v1/responses` and `/v1/models`.

```yaml
providers:
  perplexity:
    endpoint: https://api.perplexity.ai/v1
    keys: []
```

```bash
sor keys add --provider perplexity --key-id perplexity-main --secret <TOKEN>
```

Perplexity is search-grounded and can return citations/search metadata. Treat it as a strong fallback for web-grounded answers, not as a generic cheapest model provider.

## Baseten

Baseten's public Model APIs use OpenAI-compatible request/response shapes, but the auth scheme is `Authorization: Api-Key <TOKEN>` instead of Bearer.

```yaml
providers:
  baseten:
    endpoint: https://inference.baseten.co/v1
    keys: []
```

```bash
sor keys add --provider baseten --key-id baseten-main --secret <TOKEN>
```

## Together AI

Together inventory may include paid models, media models, and models unavailable to the current account. Together's API key docs describe project-scoped keys and key management.

SimpleOpenRoad filters obvious non-text models from text aliases and uses runtime model quarantine to skip models that repeatedly fail. If several Together candidates fail before a working one, repeated failures will be skipped after the configured quarantine threshold. See [Routing and Model Selection](ROUTING.md#model-quarantine).

## Gemini

```yaml
providers:
  gemini:
    endpoint: https://generativelanguage.googleapis.com
    keys: []
```

```bash
sor keys add --provider gemini --key-id gemini-main --secret <TOKEN>
```

## Google OAuth for Gemini Code Assist

SimpleOpenRoad can connect Gemini Code Assist accounts with its own OAuth pipeline. The flow uses PKCE, opens the system browser for consent, and stores credentials per local profile under `data/credentials/google_code_assist/`.

By default, the wizard uses the built-in installed-app Google OAuth client, so no env setup is needed for a normal local sign-in. Advanced users can override the client or redirect target with:

- `GEMINI_OAUTH_CLIENT_ID`
- `GEMINI_OAUTH_CLIENT_SECRET`
- `GEMINI_OAUTH_REDIRECT_URI`

Recommended usage:

```bash
sor providers connect google
sor providers accounts
```

If `GEMINI_OAUTH_REDIRECT_URI` points to `http://127.0.0.1` or `http://localhost`, SimpleOpenRoad starts a loopback callback listener and waits for the browser redirect. Otherwise it falls back to manual authorization-code entry.

Multiple Google accounts are supported by using different local profiles. Each profile gets its own credential file and provider key, so you can keep `main`, `work`, and `personal` separate.

Legacy Gemini CLI credential files are still supported for imports when you already have `oauth_creds.json` or `gemini-credentials.json` on disk.

## Gemini CLI OAuth

This provider is experimental. It is separate from the public Gemini API key provider and from Vertex AI.

The recommended path is to let SimpleOpenRoad open the browser sign-in directly. This works for normal desktops and also for remote machines when you use the loopback callback or manual code fallback.

```bash
sor providers connect google
```

SimpleOpenRoad stores the resulting credentials per profile and writes only an `oauth-file:` reference into `config/config.yaml`.

You can connect multiple Google accounts by using different profiles and key ids:

```bash
sor providers connect google --profile personal --key-id google-ai-pro-personal
sor providers connect google --profile work --key-id google-ai-pro-work --force-gemini-login
```

The interactive `Connect Google OAuth` wizard asks for the profile and key id. Each profile gets its own saved credential file under `data/credentials/google_code_assist/`, so signing in to one account does not overwrite another SimpleOpenRoad profile.

`Local profile` is only a local SimpleOpenRoad slot name, for example `main`, `personal`, or `work`. It is not your Google email and not a password. `Key ID` is the local provider key name shown in logs, validation, routing, and key management.

If the token expires and SimpleOpenRoad cannot refresh it, run the official Gemini CLI again, then repeat:

```bash
sor providers connect google
```

The command writes OAuth credentials under `data/credentials/google_code_assist/` and stores only an `oauth-file:` reference in `config/config.yaml`.

After connecting, use either generated aliases such as `auto/code` or direct models:

```text
google_code_assist/gemini-2.5-pro
google_code_assist/gemini-2.5-flash
```

## GitHub Models

```yaml
providers:
  github:
    endpoint: https://models.github.ai
    keys: []
```

```bash
sor keys add --provider github --key-id github-main --secret <TOKEN>
```

## OpenAI-Compatible Hosted Providers

These providers use the shared OpenAI-compatible transport with provider-specific defaults:

```yaml
providers:
  openai:
    endpoint: https://api.openai.com/v1

  anthropic:
    endpoint: https://api.anthropic.com/v1

  perplexity:
    endpoint: https://api.perplexity.ai/v1

  novita:
    endpoint: https://api.novita.ai/openai

  baseten:
    endpoint: https://inference.baseten.co/v1

  naga:
    endpoint: https://api.naga.ac/v1

  nebius:
    endpoint: https://api.tokenfactory.nebius.com/v1

  friendli:
    endpoint: https://api.friendli.ai/serverless/v1

  fastrouter:
    endpoint: https://go.fastrouter.ai/api/v1

  crusoe:
    endpoint: https://api.crusoe.ai/v1

  atoma:
    endpoint: https://api.atoma.network/v1

  parasail:
    endpoint: https://api.saas.parasail.io/v1

  inference_net:
    endpoint: https://api.inference.net/v1

  near_ai:
    endpoint: https://cloud-api.near.ai/v1

  aai:
    endpoint: https://api.a.ai/v1

  aimlapi:
    endpoint: https://api.aimlapi.com/v1

  vultr:
    endpoint: https://api.vultrinference.com/v1

  mistral:
    endpoint: https://api.mistral.ai/v1

  deepseek:
    endpoint: https://api.deepseek.com/v1

  xai:
    endpoint: https://api.x.ai/v1

  cohere:
    endpoint: https://api.cohere.ai/compatibility/v1

  moonshot:
    endpoint: https://api.moonshot.ai/v1

  sambanova:
    endpoint: https://api.sambanova.ai/v1

  nvidia:
    endpoint: https://integrate.api.nvidia.com/v1

  zhipuai:
    endpoint: https://open.bigmodel.cn/api/paas/v4

  zai:
    endpoint: https://api.z.ai/api/paas/v4

  featherless:
    endpoint: https://api.featherless.ai/v1

  hyperbolic:
    endpoint: https://api.hyperbolic.xyz/v1

  ovhcloud:
    endpoint: https://oai.endpoints.kepler.ai.cloud.ovh.net/v1

  fireworks:
    endpoint: https://api.fireworks.ai/inference/v1

  deepinfra:
    endpoint: https://api.deepinfra.com/v1/openai

  siliconflow:
    endpoint: https://api.siliconflow.cn/v1

  huggingface:
    endpoint: https://router.huggingface.co/v1
```

Add keys the same way:

```bash
sor keys add --provider openai --key-id openai-main --secret <TOKEN>
sor keys add --provider anthropic --key-id anthropic-main --secret <TOKEN>
sor keys add --provider azure_openai --key-id azure-openai-main --secret <TOKEN>
sor keys add --provider bedrock --key-id bedrock-main --secret <TOKEN>
sor keys add --provider vertex_ai --key-id vertex-main --secret adc
sor keys add --provider perplexity --key-id perplexity-main --secret <TOKEN>
sor keys add --provider novita --key-id novita-main --secret <TOKEN>
sor keys add --provider baseten --key-id baseten-main --secret <TOKEN>
sor keys add --provider naga --key-id naga-main --secret <TOKEN>
sor keys add --provider nebius --key-id nebius-main --secret <TOKEN>
sor keys add --provider friendli --key-id friendli-main --secret <TOKEN>
sor keys add --provider fastrouter --key-id fastrouter-main --secret <TOKEN>
sor keys add --provider crusoe --key-id crusoe-main --secret <TOKEN>
sor keys add --provider atoma --key-id atoma-main --secret <TOKEN>
sor keys add --provider parasail --key-id parasail-main --secret <TOKEN>
sor keys add --provider inference_net --key-id inference-net-main --secret <TOKEN>
sor keys add --provider near_ai --key-id near-ai-main --secret <TOKEN>
sor keys add --provider aai --key-id aai-main --secret <TOKEN>
sor keys add --provider aimlapi --key-id aimlapi-main --secret <TOKEN>
sor keys add --provider vultr --key-id vultr-main --secret <TOKEN>
sor keys add --provider mistral --key-id mistral-main --secret <TOKEN>
sor keys add --provider deepseek --key-id deepseek-main --secret <TOKEN>
sor keys add --provider xai --key-id xai-main --secret <TOKEN>
sor keys add --provider cohere --key-id cohere-main --secret <TOKEN>
sor keys add --provider moonshot --key-id moonshot-main --secret <TOKEN>
sor keys add --provider sambanova --key-id sambanova-main --secret <TOKEN>
sor keys add --provider nvidia --key-id nvidia-main --secret <TOKEN>
sor keys add --provider zhipuai --key-id zhipuai-main --secret <TOKEN>
sor keys add --provider zai --key-id zai-main --secret <TOKEN>
sor keys add --provider featherless --key-id featherless-main --secret <TOKEN>
sor keys add --provider hyperbolic --key-id hyperbolic-main --secret <TOKEN>
sor keys add --provider ovhcloud --key-id ovhcloud-main --secret <TOKEN>
sor keys add --provider fireworks --key-id fireworks-main --secret <TOKEN>
sor keys add --provider deepinfra --key-id deepinfra-main --secret <TOKEN>
sor keys add --provider siliconflow --key-id siliconflow-main --secret <TOKEN>
sor keys add --provider huggingface --key-id huggingface-main --secret <TOKEN>
```

## Custom OpenAI-Compatible Endpoint

Use `adapter: openai_compatible` for local or hosted endpoints that expose `/v1/chat/completions` and compatible streaming.

```yaml
providers:
  local_vllm:
    enabled: true
    adapter: openai_compatible
    display_name: Local vLLM
    endpoint: http://127.0.0.1:8000/v1
    auth_required: false
    timeout_seconds: 60
    keys:
      - id: local-vllm
        key: local
```

Even when `auth_required: false`, configure one local key entry so the router has a selectable key record.

## Local Provider Presets

Local presets are disabled by default to avoid connection errors on machines that are not running local model servers. Enable the provider you use:

```yaml
providers:
  ollama:
    enabled: true
    endpoint: http://127.0.0.1:11434/v1
    auth_required: false
    keys:
      - id: ollama-local
        key: local

  lmstudio:
    enabled: true
    endpoint: http://127.0.0.1:1234/v1
    auth_required: false
    keys:
      - id: lmstudio-local
        key: local

  jan:
    enabled: true
    endpoint: http://127.0.0.1:1337/v1
    auth_required: false
    keys:
      - id: jan-local
        key: local

  litellm:
    enabled: true
    endpoint: http://127.0.0.1:4000/v1
    auth_required: false
    keys:
      - id: litellm-local
        key: local
```

The `key` value is not sent upstream when `auth_required: false`; it exists so routing, health, and diagnostics have a key record.

Default local endpoints:

| Preset | Endpoint |
|---|---|
| `ollama` | `http://127.0.0.1:11434/v1` |
| `lmstudio` | `http://127.0.0.1:1234/v1` |
| `localai` | `http://127.0.0.1:8080/v1` |
| `vllm` | `http://127.0.0.1:8000/v1` |
| `jan` | `http://127.0.0.1:1337/v1` |
| `llamacpp` | `http://127.0.0.1:8080/v1` |
| `textgenwebui` | `http://127.0.0.1:5000/v1` |
| `litellm` | `http://127.0.0.1:4000/v1` |

## Groq and Cerebras

```yaml
providers:
  groq:
    endpoint: https://api.groq.com/openai/v1

  cerebras:
    endpoint: https://api.cerebras.ai/v1
```

## Validation Commands

```bash
sor providers test
sor keys validate
sor providers inventory --refresh
sor providers consistency
sor routes preview --model auto/fast
```
