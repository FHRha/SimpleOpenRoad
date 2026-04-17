# Provider Expansion Roadmap

This document tracks future provider expansion and the CLI UX needed to manage a large provider catalog.

It is a planning document, not a support matrix. Current supported providers are documented in [Providers](../PROVIDERS.md).

## Goals

- Add high-value providers without turning setup into a 100-item terminal list.
- Prefer OpenAI-compatible providers first when the adapter cost is low.
- Add native adapters only when a provider has different payload/auth semantics or important unique behavior.
- Classify providers so users can choose by intent: known, free-friendly, local, enterprise, media, embeddings, or ordinary hosted inference.
- Keep generated aliases reliable by filtering non-chat/media/embedding models out of text routes.

## Current First-Class Providers

| Provider | Category | Notes |
|---|---|---|
| Gemini | Known | Native Google AI Studio adapter. |
| GitHub Models | Known | OpenAI-compatible, needs GitHub token permissions. |
| Groq | Known | OpenAI-compatible, fast hosted inference. |
| Cloudflare Workers AI | Known | Account-scoped Workers AI, key-level account IDs supported. |
| OpenRouter | Known / Free-friendly | Aggregator, supports free-suffixed routes and special routes. |
| Together AI | Ordinary hosted inference | Large catalog, account billing/model availability varies. |
| Cerebras | Ordinary hosted inference | OpenAI-compatible inference cloud. |

## Provider Categories

### Featured / Known Providers

These should appear near the top of setup flows because users recognize them or they are broadly useful.

Initial candidates:

- OpenAI
- Anthropic
- Azure OpenAI
- Google Gemini
- Google Vertex AI
- AWS Bedrock
- OpenRouter
- GitHub Models
- Groq
- Cloudflare Workers AI

### Free-Friendly Providers

These may expose free tiers, free routes, local execution, or free developer credits. They still need runtime validation because free availability changes often.

Candidates:

- OpenRouter
- Google Gemini / Google AI Studio
- GitHub Models
- Cloudflare Workers AI
- Groq
- Ollama
- LM Studio
- LocalAI
- vLLM
- Hugging Face Inference / Endpoints

Important rule: never assume a provider is free globally. Store free capability at model/route level from inventory and runtime behavior.

### Local / Self-Hosted Providers

These are valuable because they avoid external billing and make SimpleOpenRoad useful offline or inside private infrastructure.

Candidates:

- Ollama
- LM Studio
- vLLM
- LocalAI
- Text Generation Inference
- llama.cpp server
- generic OpenAI-compatible local endpoint

Implementation direction:

- Add one generic `openai_compatible_custom` provider first.
- Add presets for common local endpoints later.
- Allow users to define display name, base URL, auth requirement, inventory behavior, and model list fallback.

### Ordinary Hosted Inference Providers

These are useful fallback providers but should not crowd the top of setup lists.

Candidates:

- Mistral AI
- DeepSeek
- xAI
- Fireworks AI
- DeepInfra
- NVIDIA NIM
- Novita AI
- SambaNova
- Moonshot AI / Kimi
- ZhipuAI / GLM
- SiliconFlow
- AI21
- Cohere
- Perplexity
- Replicate
- Baseten
- Predibase

### Enterprise / Cloud Providers

These are high-value but usually require more complex auth, regions, deployments, or provider-specific request formats.

Candidates:

- Azure OpenAI
- AWS Bedrock
- Google Vertex AI
- AWS SageMaker
- Databricks
- IBM watsonx.ai

Implementation direction:

- Add Azure OpenAI before Bedrock/Vertex because it is closer to OpenAI-compatible routing.
- Treat Bedrock and Vertex as native adapters with region/project/auth-specific config.
- Keep enterprise provider setup out of the quick-start path unless configured.

### Embeddings / Rerank / Search Providers

These should not automatically enter text chat aliases.

Candidates:

- Cohere
- Jina AI
- Voyage AI
- Nomic AI
- BAAI-compatible hosted endpoints
- Perplexity search models

Implementation direction:

- Add separate capability buckets for `embedding`, `rerank`, `search`, `audio`, `image`, and `video`.
- Generate modality-specific aliases only when the API surface supports them.

## Implementation Priority

### Phase 1: Low Adapter Cost, High User Value

1. OpenAI
2. Mistral AI
3. DeepSeek
4. xAI
5. Fireworks AI
6. DeepInfra
7. generic OpenAI-compatible provider

Reasoning:

- Most are OpenAI-compatible or close to it.
- They improve fallback coverage quickly.
- They exercise the existing inventory, routing, and quarantine mechanisms without major auth changes.

### Phase 2: Native / Important Providers

1. Anthropic
2. Azure OpenAI
3. Ollama
4. LM Studio / LocalAI / vLLM presets
5. Perplexity

Reasoning:

- Anthropic is critical for coding-agent users but needs native payload translation.
- Azure OpenAI is important for enterprise users.
- Local providers are important for cost-free/private use.
- Perplexity needs search-aware routing so it does not behave like normal chat.

### Phase 3: Enterprise and Specialized Providers

1. AWS Bedrock
2. Google Vertex AI
3. NVIDIA NIM
4. Cohere
5. Voyage / Jina / rerank providers
6. Replicate / Baseten / Predibase

Reasoning:

- Valuable but more config-heavy.
- Some are not primarily chat providers.
- Some need separate endpoints or capability-specific aliases.

## Provider Setup UX Problem

When the catalog grows beyond 15-20 providers, terminal setup must not print a huge numbered list by default.

Current style:

```text
Featured providers
1) gemini
2) github
3) openrouter
...
Other providers
...
```

This will not scale to 50-100 providers.

## Proposed Provider Picker UX

### Default View

The first screen should show the most recognizable providers immediately, without forcing the user to search.

Example:

```text
Featured providers
1) OpenAI
2) Anthropic / Claude
3) Gemini
4) OpenRouter
5) GitHub Models
6) Groq
7) Cloudflare Workers AI
8) Azure OpenAI
9) AWS Bedrock
10) Ollama

S) Search provider
G) Browse by group
M) Manual provider id
0) Back
```

Rules:

- Keep the featured list short, ideally 8-12 providers.
- Include currently configured providers even if they are not globally featured.
- Put recently used providers near the top.
- Do not show the full long-tail provider catalog by default.

### Browse By Group

Group browsing is the secondary path for users who do not see their provider in the featured list:

```text
Select provider group
1) Featured / known
2) Free-friendly
3) Local / self-hosted
4) Enterprise cloud
5) Ordinary hosted inference
6) Embeddings / rerank / search
S) Search provider
M) Manual provider id
0) Back
```

Then show a short list inside the selected group, capped to 10-15 entries. If the group is larger, ask for search/filter text before rendering more.

### Search Mode

Search should accept:

- provider id: `anthropic`
- display name: `Anthropic`
- partial substring: `ant`
- acronym-ish fragments: `aws`, `bed`, `cf`
- common aliases: `claude` -> `anthropic`, `kimi` -> `moonshot`, `grok` -> `xai`

Example:

```text
Search provider: ant

1) anthropic       Anthropic / Claude        Featured
2) together        Together AI               Ordinary
3) replicate       Replicate                 Ordinary

Select provider [1]:
```

Search ranking:

1. exact provider id match;
2. exact alias match;
3. prefix match;
4. display-name prefix match;
5. substring match;
6. fuzzy match for short typos.

### Provider Metadata Needed

Each provider definition should include:

```yaml
id: anthropic
display_name: Anthropic
aliases:
  - claude
  - ant
groups:
  - featured
  - known
capabilities:
  - chat
  - streaming
  - tools
auth:
  type: api_key
docs:
  api_key_url: https://console.anthropic.com/settings/keys
adapter:
  type: native
```

This metadata can be in code first, then moved to a small registry file if it grows.

### CLI Behavior Rules

- Never print all providers by default when count exceeds a configured threshold.
- Show a short featured list immediately so known providers are one keypress away.
- Always offer `Search provider`.
- Always offer `Browse by group`.
- Always offer `Manual provider id` for custom or not-yet-first-class providers.
- Show provider display name and short note, not only the id.
- Show warning badges for complex providers:
  - `requires account id`
  - `requires region`
  - `requires deployment`
  - `local endpoint`
  - `non-chat catalog`
- Remember recently used providers and show them near the top.

## Config Model Direction

Provider config should remain simple:

```yaml
providers:
  anthropic:
    enabled: true
    priority: 25
    endpoint: https://api.anthropic.com
    timeout_seconds: 60
    keys: []
```

For generic OpenAI-compatible providers:

```yaml
providers:
  my_local_vllm:
    enabled: true
    adapter: openai_compatible
    display_name: Local vLLM
    endpoint: http://127.0.0.1:8000/v1
    auth_required: false
    inventory:
      mode: static
      models:
        - Qwen/Qwen3-Coder
```

The exact schema can evolve, but the goal is to avoid writing a new adapter for every OpenAI-compatible endpoint.

## Open Questions

- Should provider metadata live in Python registry code or a YAML/JSON catalog?
- Should users be able to install third-party provider definitions?
- Should local providers be enabled by default when detected on common ports?
- How much fuzzy matching is worth implementing without adding heavy dependencies?
- Should `free-friendly` be provider-level only, or should it be shown only after inventory confirms free models?
