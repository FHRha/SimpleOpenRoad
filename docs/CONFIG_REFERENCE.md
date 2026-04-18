# Config Reference

SimpleOpenRoad reads environment values from `.env` and gateway settings from `config/config.yaml`.

## `.env`

```env
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=12345
APP_LOG_LEVEL=INFO
APP_CONFIG_PATH=config/config.yaml
APP_DB_PATH=data/gateway.db

MASTER_API_KEY=change-me-user-api-key
ADMIN_API_KEY=change-me-admin-api-key
```

## `config/config.yaml`

Use `config/config.example.yaml` as the authoritative template. The important sections are summarized below. For provider-specific setup and API key links, see [Providers](PROVIDERS.md).

### Server

```yaml
server:
  host: 0.0.0.0
  port: 12345
  request_timeout_seconds: 60
  stream_timeout_seconds: 300
```

### Security

```yaml
security:
  require_master_key: true
  require_admin_key: true
  mask_secrets_in_logs: true
```

User API accepts:

- `x-api-key: <MASTER_API_KEY>`
- `Authorization: Bearer <MASTER_API_KEY>`

Admin API accepts:

- `x-admin-key: <ADMIN_API_KEY>`
- `Authorization: Bearer <ADMIN_API_KEY>`

### Routing

```yaml
routing:
  default_strategy: strict_priority
  retry:
    max_attempts_per_candidate: 2
    backoff_base_ms: 200
    backoff_max_ms: 2000
    jitter_ms: 100
  error_policy:
    auth_invalid: switch_key
    auth_forbidden: switch_key
    rate_limit: retry_then_switch_key
    provider_unavailable: retry_then_switch_provider
    network_timeout: retry_then_switch_key
    malformed_response: switch_provider
    unsupported_model: switch_provider
```

`default_strategy` controls key selection unless a custom alias overrides it.

Common strategies:

- `strict_priority`
- `least_errors`
- `random_by_weight`
- `least_recently_used`

### Free Alias Policy

```yaml
routing:
  free_alias:
    max_candidates_per_request: 3
    stop_on_provider_free_tier_rate_limit: true
```

`auto/free` is strict free-only. It does not silently fall back to paid models.

### Model Quarantine

```yaml
routing:
  model_quarantine:
    enabled: true
    failure_threshold: 3
    default_ttl_seconds: 1800
    error_ttl_seconds:
      rate_limit: 1800
      provider_unavailable: 600
      network_timeout: 300
      malformed_response: 21600
      unsupported_model: 86400
      unknown: 1800
    overrides: []
```

After `failure_threshold` consecutive failures, a `provider/model` is skipped until the configured TTL expires.

Override example:

```yaml
routing:
  model_quarantine:
    overrides:
      - provider: together
        model_pattern: "nvidia/*"
        failure_threshold: 1
        ttl_seconds: 7200
```

### Model Capability Hints

```yaml
model_capabilities:
  tool_capable:
    - codex
    - coder
    - qwen
  tool_disabled:
    - nano
    - haiku
```

These are heuristic hints used during inventory classification.

### Inventory

```yaml
inventory:
  refresh_time: "05:00"
  refresh_timezone: Europe/Moscow
  refresh_interval_hours: 24
  overrides: []
```

Generated aliases are built from provider inventory and cached until the next refresh window.

Inventory override example:

```yaml
inventory:
  overrides:
    - provider: openrouter
      model_pattern: "openai/*codex*"
      force_categories: [code]
      force_tool_capable: true
```

### Providers

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

Lower provider `priority` values are ordered earlier in generated global aliases.

Built-in OpenAI-compatible providers use the shared transport with fixed provider names and default endpoints. This includes `openai`, `anthropic`, `bedrock`, `perplexity`, `novita`, `naga`, `nebius`, `near_ai`, `friendli`, `fastrouter`, `crusoe`, `atoma`, `parasail`, `inference_net`, `aai`, `aimlapi`, `vultr`, `mistral`, `deepseek`, `xai`, `cohere`, `moonshot`, `sambanova`, `nvidia`, `zhipuai`, `zai`, `featherless`, `hyperbolic`, `ovhcloud`, `fireworks`, `deepinfra`, `siliconflow`, and `huggingface`.

`azure_openai` is built in but is not a normal `/v1` provider. It uses Azure's `api-key` header and deployment-scoped URLs where the requested model id is treated as the deployment name.

`bedrock` is built in with Amazon Bedrock's OpenAI-compatible endpoint. It uses a Bedrock API key directly in the normal Bearer auth flow.

`vertex_ai` is built in with Vertex AI's OpenAI-compatible endpoint, but the `key` field is interpreted specially:

- `adc` uses Google Application Default Credentials;
- a path ending in `.json` uses that service account file;
- any other value is treated as a direct Bearer access token.

`baseten` is also built in with OpenAI-compatible paths, but uses `Authorization: Api-Key <TOKEN>` instead of Bearer auth.

Custom OpenAI-compatible providers can use the shared adapter:

```yaml
providers:
  local_vllm:
    enabled: true
    adapter: openai_compatible
    display_name: Local vLLM
    endpoint: http://127.0.0.1:8000/v1
    auth_required: false
    keys:
      - id: local-vllm
        key: local
```

When `auth_required: false`, the key value is not sent upstream, but the router still needs one key record for selection and diagnostics.

Local presets such as `ollama`, `lmstudio`, `localai`, `vllm`, `jan`, `llamacpp`, `textgenwebui`, and `litellm` use the same `openai_compatible` adapter and are disabled by default in the example config.

Cloudflare supports account IDs at provider or key level:

```yaml
providers:
  cloudflare:
    enabled: true
    priority: 29
    endpoint: https://api.cloudflare.com/client/v4
    account_id: ""
    keys:
      - id: cloudflare-main
        key: <TOKEN>
        account_id: <ACCOUNT_ID>
```

Use key-level `account_id` for multiple Cloudflare accounts.

### Custom Aliases

```yaml
routes:
  aliases:
    custom/fast:
      strategy: strict_priority
      selection: ordered
      candidates:
        - provider: github
          model: gpt-4.1-mini
```

Generated aliases such as `auto/general` should not be stored in `routes.aliases`; they are built from inventory.

### Storage

```yaml
storage:
  sqlite_path: data/gateway.db
```

Runtime state is stored in SQLite:

- key runtime state;
- health checks;
- request attempts;
- usage stats;
- route memory;
- model quarantine state.

### Health and Observability

```yaml
health:
  check_interval_seconds: 300
  startup_check: true
  check_timeout_seconds: 20

observability:
  json_logs: true
  request_log: true
  router_decision_log: true
  save_attempt_events: true
```

## Validation

```bash
sor config validate
sor providers test
sor providers inventory --refresh
sor routes preview --model auto/general
```
