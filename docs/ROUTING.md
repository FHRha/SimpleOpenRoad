# Routing and Model Selection

SimpleOpenRoad routes each request through a candidate list. Candidates can come from generated aliases, custom aliases, direct provider/model requests, or exact model IDs.

## Request Forms

Generated alias:

```text
auto/general
auto/fast
auto/code
```

Direct provider/model:

```text
openrouter/openai/gpt-5.4-mini
cloudflare/@cf/openai/gpt-oss-20b
together/arize-ai/qwen-2-1.5b-instruct
```

Exact model ID across providers:

```text
gpt-5.4-mini
```

## Generated Aliases

Generated aliases are built from provider inventory. Provider-specific inventory caveats are documented in [Providers](PROVIDERS.md).

| Alias | Behavior |
|---|---|
| `auto/fast` | Lightweight, cheap, low-latency models. |
| `auto/general` | Recommended default. |
| `auto/reasoning` | Stronger reasoning and analysis models. |
| `auto/code` | Coding and agent-oriented models. |
| `auto/free` | Strict free-only route. |
| `auto/free-cheap` | Free-first route with cheap fallback only when free candidates exist. |
| `auto/image/default` | Image-capable inventory models. |
| `auto/audio/default` | Audio-capable inventory models. |
| `auto/video/default` | Video-capable inventory models. |

Preview an alias:

```bash
sor routes preview --model auto/general
```

Refresh inventory:

```bash
sor providers inventory --refresh
```

## Adaptive Routing

For generated text aliases, SimpleOpenRoad analyzes the request and assigns a profile:

- `fast`
- `balanced`
- `strong`
- `code`

It estimates context size and detects tool requirements. This can reorder generated candidates before execution.

## Candidate Execution

For each candidate, the router checks:

1. provider is registered and enabled;
2. model is not quarantined;
3. context estimate fits known context limits;
4. provider has available active keys;
5. for discovered models, selected keys match the keys that discovered that model;
6. routing policy allows retry, key switch, or provider switch.

Diagnostics can show candidates as `attempted`, `skipped`, `context_too_large`, `model_quarantined`, `no_available_keys`, or `provider_not_registered`.

## Key Cooldown

Keys have runtime state in SQLite:

- active/inactive;
- status;
- consecutive errors;
- cooldown;
- success/failure counts;
- average latency.

Rate limits and auth failures affect key state. Auth failures do not quarantine models because they usually mean the key or account is wrong.

## Route Memory

Route memory remembers a successful `provider/model` for:

```text
route_alias + request_profile + context_bucket
```

If the same alias/profile/bucket appears again, the remembered model is moved toward the front.

## Model Quarantine

Model quarantine tracks failures by:

```text
provider + model
```

After enough consecutive failures, the model gets `quarantined_until` and is skipped before any provider request is made.

Default settings:

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
```

Default TTLs:

| Error Class | TTL |
|---|---:|
| `rate_limit` | 30 minutes |
| `provider_unavailable` | 10 minutes |
| `network_timeout` | 5 minutes |
| `malformed_response` | 6 hours |
| `unsupported_model` | 24 hours |
| `unknown` | 30 minutes |

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

Manual settings:

```text
sor -> Settings -> Model quarantine settings
```

## Free Routes

`auto/free` is strict free-only. It should not silently fall back to paid models.

`auto/free-cheap` is free-first, but it is only generated when at least one real free candidate exists.

```yaml
routing:
  free_alias:
    max_candidates_per_request: 3
    stop_on_provider_free_tier_rate_limit: true
```

## Custom Aliases

Custom aliases live in `routes.aliases`.

```yaml
routes:
  aliases:
    custom/fast:
      strategy: strict_priority
      selection: ordered
      candidates:
        - provider: github
          model: gpt-4.1-mini
        - provider: openrouter
          model: openai/gpt-4o-mini
```

Generated aliases should not be manually stored in `routes.aliases`; they are generated from inventory.

## Debugging Routing

```bash
sor routes preview --model auto/fast
sor providers consistency
```

Automatic API test:

```text
sor -> Gateway -> API access token and test -> Test API request automatically
```
