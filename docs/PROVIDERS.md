# Providers

SimpleOpenRoad connects provider APIs behind one OpenAI-compatible gateway. Provider model catalogs are discovered into runtime inventory and used to generate aliases.

## Support Matrix

| Provider | Chat | Streaming | Tools | Inventory | API Key / Token |
|---|---:|---:|---:|---:|---|
| [Gemini](https://aistudio.google.com/apikey) | yes | yes | model-dependent | yes | Google AI Studio API keys. |
| [GitHub Models](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) | yes | yes | model-dependent | yes | GitHub personal access token. |
| [Groq](https://console.groq.com/keys) | yes | yes | model-dependent | yes | GroqCloud API keys. |
| [Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/get-started/rest-api/) | yes | yes | model-dependent | yes | Workers AI API token plus Account ID. |
| [OpenRouter](https://openrouter.ai/settings/keys) | yes | yes | model-dependent | yes | OpenRouter workspace API keys. |
| [Together AI](https://docs.together.ai/docs/api-keys-authentication) | yes | yes | model-dependent | yes | Together project API keys. |
| [Cerebras](https://inference-docs.cerebras.ai/api-reference/authentication) | yes | yes | model-dependent | yes | Cerebras Inference Cloud Console keys. |

Capabilities are inferred from provider metadata and model names, then corrected by filters and overrides. Verify with:

```bash
sor providers inventory --refresh
sor routes preview --model auto/general
```

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
