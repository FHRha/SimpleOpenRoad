# Client Configuration

SimpleOpenRoad is designed to look like an OpenAI-compatible `/v1` endpoint to clients, IDE plugins, coding agents, and scripts.

## Standard Settings

Use these values in most OpenAI-compatible tools:

```text
Base URL: http://<SERVER_IP>:12345/v1
API Key:  <MASTER_API_KEY>
Model:    auto/general
```

For local testing:

```text
Base URL: http://127.0.0.1:12345/v1
API Key:  value from .env -> MASTER_API_KEY
Model:    auto/general
```

`MASTER_API_KEY` can be shown or regenerated from:

```text
sor -> Gateway -> API access token and test
```

## Recommended Models

| Client Use Case | Model |
|---|---|
| Default chat | `auto/general` |
| Fast checks and short prompts | `auto/fast` |
| Coding agents | `auto/code` |
| Hard reasoning | `auto/reasoning` |
| Strict free-only route | `auto/free` |
| Free-first with cheap fallback | `auto/free-cheap` |

See [Routing and Model Selection](ROUTING.md) for how aliases are generated and routed.

## Cline-Style Agents

For Cline-like clients, use:

```text
Provider/API type: OpenAI-compatible
Base URL:          http://<SERVER_IP>:12345/v1
API Key:           <MASTER_API_KEY>
Model:             auto/code
```

Then validate the gateway path:

```text
sor -> Gateway -> API access token and test -> Test API request automatically -> Cline-like
```

If the Cline-like test fails:

- Run `sor providers inventory --refresh`.
- Preview `auto/code`: `sor routes preview --model auto/code`.
- Check [Troubleshooting](TROUBLESHOOTING.md) for tool, streaming, Cloudflare, Together, and quarantine cases.

## Continue and Similar IDE Plugins

Use an OpenAI-compatible provider entry:

```text
Base URL: http://<SERVER_IP>:12345/v1
API Key:  <MASTER_API_KEY>
Model:    auto/code
```

Use `auto/general` for chat panels and `auto/code` for edit/refactor flows.

## curl

Linux/macOS:

```bash
MASTER_API_KEY="$(grep '^MASTER_API_KEY=' .env | cut -d= -f2-)"

curl -sS -X POST "http://127.0.0.1:12345/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${MASTER_API_KEY}" \
  --data-binary @- <<'JSON'
{
  "model": "auto/general",
  "messages": [
    {"role": "user", "content": "Say hello in one short sentence."}
  ]
}
JSON
```

Windows PowerShell:

```powershell
$env:MASTER_API_KEY = (Select-String -Path .env -Pattern '^MASTER_API_KEY=').Line.Split('=', 2)[1]

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:12345/v1/chat/completions" `
  -Headers @{ "x-api-key" = $env:MASTER_API_KEY } `
  -ContentType "application/json" `
  -Body '{
    "model": "auto/general",
    "messages": [
      {"role": "user", "content": "Say hello in one short sentence."}
    ]
  }'
```

## Streaming Check

Use the terminal panel first:

```text
sor -> Gateway -> API access token and test -> Test API request automatically -> streaming chat
```

A minimal streaming request:

```bash
curl -N -sS -X POST "http://127.0.0.1:12345/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${MASTER_API_KEY}" \
  --data-binary @- <<'JSON'
{
  "model": "auto/fast",
  "stream": true,
  "messages": [
    {"role": "user", "content": "Count to three."}
  ]
}
JSON
```

## Direct Model Requests

Use `provider/model` when you want to force one provider:

```text
openrouter/openai/gpt-5.4-mini
cloudflare/@cf/openai/gpt-oss-20b
together/arize-ai/qwen-2-1.5b-instruct
anthropic/claude-sonnet-4-6
deepseek/deepseek-chat
xai/grok-4.20-reasoning
cohere/command-a-03-2025
moonshot/kimi-k2-0905-preview
zhipuai/glm-5
zai/GLM-4.5-air
featherless/zai-org/GLM-4.7
hyperbolic/Qwen/Qwen3-Coder-480B-A35B-Instruct
ovhcloud/Meta-Llama-3_3-70B-Instruct
fireworks/accounts/fireworks/models/llama-v3p1-8b-instruct
huggingface/openai/gpt-oss-120b:fastest
ollama/gpt-oss:20b
jan/local-model-id
llamacpp/local-model-id
textgenwebui/local-model-id
litellm/gpt-4o-mini
```

Use generated aliases when you want failover:

```text
auto/general
auto/code
```

## Authentication Headers

User API accepts either:

```text
x-api-key: <MASTER_API_KEY>
Authorization: Bearer <MASTER_API_KEY>
```

Admin API accepts either:

```text
x-admin-key: <ADMIN_API_KEY>
Authorization: Bearer <ADMIN_API_KEY>
```

Do not put provider keys into client tools. Client tools should only receive the gateway `MASTER_API_KEY`.
