# GitHub `degraded` Validation Triage

This note tracks suspicious points that can make a GitHub key show `degraded` even when a direct catalog request works.

## Current Symptom

Observed CLI output:

```text
github | 2 | degraded | 454.95 | 0 | unknown
```

Manual request from the same server returns GitHub Models catalog data:

```text
GET https://models.github.ai/catalog/models
-> [{"id":"openai/gpt-4.1", ...}, {"id":"openai/gpt-4.1-mini", ...}]
```

That means the token and GitHub catalog endpoint can work. The likely issue is inside SOR validation, endpoint construction, stale runtime state, or CLI display.

## Runtime Paths That Can Produce `degraded`

## Implementation Status

Implemented fixes:

- GitHub catalog validation now reports `no_models_discovered` with response shape and resolved URL context when the catalog returns no usable model records.
- GitHub default API version header is `2022-11-28`; provider config headers can override adapter defaults.
- GitHub catalog and inference URLs are handled separately, so `/inference` is kept for chat and removed for catalog requests.
- Inventory refresh records an explicit `no_models_discovered` error instead of `degraded` with empty error fields.
- Health checks catch unexpected adapter exceptions as `validation_exception`.
- Successful health validation clears stale runtime key errors and cooldown state.
- CLI provider validation now shows model counts plus error message fallback.
- CLI diagnostics now includes `providers consistency` / `Key consistency` to compare config, runtime state, health results, and inventory results.

Useful verification commands:

```text
sor providers test
sor providers inventory --refresh
sor providers consistency
```

### 1. Health validation path

Entry point:

```text
app/health/checker.py::HealthChecker.validate_single_key
```

Flow:

```text
AdminService.validate_key
-> HealthChecker.validate_single_key
-> adapter.validate_key
-> adapter.list_models
-> adapter.list_model_records
```

`degraded` can be returned when:

- `adapter.validate_key()` returns status `degraded`.
- `HealthChecker` times out and replaces the result with `health_check_timeout`.
- An adapter returns an empty model list without a clear error.

Suspicious point:

- `HealthChecker` only catches `asyncio.TimeoutError`. If an adapter has an unexpected exception type, it may surface differently depending on caller.

Suggested fix:

- Make validation diagnostics explicit for all non-valid outcomes.
- Catch unexpected adapter exceptions and return `error_code=validation_exception` with a sanitized message.

### 2. Inventory discovery path

Entry point:

```text
app/inventory/discovery.py::InventoryDiscoveryService.refresh
```

Flow:

```text
AdminService.refresh_inventory
-> InventoryDiscoveryService.refresh
-> adapter.list_model_records
```

`degraded` can be written into inventory key results when:

- `list_model_records()` returns an empty list.
- `list_model_records()` raises `GatewayError` that is not auth-related.

Suspicious point:

- Empty discovered records currently become `status=degraded`, `discovered_models=0`, `error_code=None`, `error_message=None`.
- CLI then displays this as an unclear degraded/unknown state.

Suggested fix:

- If `discovered_records` is empty, write `error_code=no_models_discovered`.
- Include the resolved provider URL or endpoint type in diagnostics, without secrets.

### 3. GitHub endpoint normalization

Entry point:

```text
app/providers/github_models.py::GitHubModelsAdapter._url
```

Required GitHub URLs:

```text
Catalog: https://models.github.ai/catalog/models
Chat:    https://models.github.ai/inference/chat/completions
```

Suspicious point:

- If the configured endpoint is `https://models.github.ai/inference`, chat and catalog need different normalization.
- Chat should keep `/inference`.
- Catalog should remove `/inference`.

Suggested fix:

- Add a dedicated URL builder for GitHub catalog vs inference paths.
- Add diagnostics that print the resolved catalog URL with token removed.

### 4. GitHub API version header

Entry point:

```text
app/providers/github_models.py::GitHubModelsAdapter.__init__
```

Current header:

```text
X-GitHub-Api-Version: 2026-03-10
```

Manual command used:

```text
X-GitHub-Api-Version: 2022-11-28
```

Suspicious point:

- GitHub REST API commonly documents `2022-11-28`. If `2026-03-10` is not accepted for this endpoint in some accounts/regions, GitHub may return nonstandard behavior.

Suggested fix:

- Use `2022-11-28` by default unless GitHub Models explicitly requires a newer version.
- Make GitHub API version configurable in provider headers.
- Add a test that confirms custom provider headers override defaults.

### 5. Header merge order

Entry point:

```text
app/providers/openai_compatible.py::OpenAICompatibleAdapter._build_headers
```

Current order:

```text
default Authorization/Content-Type
-> config.headers
-> adapter extra_headers
```

Suspicious point:

- Adapter `extra_headers` always override `config.headers`.
- This prevents users from overriding `Accept` or `X-GitHub-Api-Version` via config for GitHub.

Suggested fix:

- Decide whether provider config should override adapter defaults.
- For GitHub, prefer: default auth/content-type -> adapter defaults -> config headers.
- Add tests for header override precedence.

### 6. CLI provider test output hides useful error message

Entry point:

```text
app/cli/app.py::providers_test
```

Current behavior:

```text
Error = error_code only
```

Suspicious point:

- If `error_code` is empty but `error_message` contains the actual issue, `providers test` hides it.
- This can look like `unknown`, depending on the table/function used.

Suggested fix:

- Display `error_code or error_message or "-"`.
- Add `Models` count to `providers test`, matching key validation output.

### 7. Runtime key state can remain degraded after successful inventory refresh

Entry points:

```text
app/registry/keys.py::KeyRegistry.mark_health
app/storage/repositories/keys_repo.py::KeysRuntimeRepository.update_health
```

Suspicious point:

- `update_health()` updates status and timestamp, but only updates `last_error_code` and `last_error_message` via `COALESCE`.
- If a key later becomes valid with `error_code=None`, old error fields remain.

Current query:

```sql
last_error_code = COALESCE(?, last_error_code)
last_error_message = COALESCE(?, last_error_message)
```

Suggested fix:

- On `status=valid`, clear `last_error_code`, `last_error_message`, and possibly `consecutive_errors`.
- Add a test: degraded health result followed by valid health result must clear last error.

### 8. Runtime key state and inventory key results are separate sources

Relevant commands/screens:

```text
keys list -> key_runtime_state
providers test / keys validate -> live health check
providers inventory -> inventory snapshot key_results
api test -> running HTTP gateway process
```

Suspicious point:

- User may see `degraded` from a previous runtime state while inventory refresh already found models.
- Or CLI process may refresh inventory, while running `sor.service` still has stale config/inventory.

Suggested fix:

- In UI, label source explicitly: `runtime`, `health check`, `inventory`.
- After key changes, force running gateway reload and show whether it succeeded.
- Add a `Diagnostics -> Key consistency` command comparing runtime state, latest health check, and inventory key result.

### 9. Catalog parsing supports root arrays, but not all possible GitHub wrappers

Entry point:

```text
app/providers/github_models.py::GitHubModelsAdapter._extract_model_items
```

Supported:

```text
[]
{"models": []}
{"data": []}
{"items": []}
nested one-level wrappers
```

Suspicious point:

- If GitHub returns an error-like JSON with status 200, or a different wrapper, parser returns empty list and validation becomes degraded.

Suggested fix:

- If parser returns empty list, include a short sanitized preview of the response shape in `error_message`.
- Do not include token or full body.

## Proposed Fix Order

1. Improve GitHub validation diagnostics first.
   - Add explicit `no_models_discovered`.
   - Include resolved catalog URL and response shape.
   - Show `error_message` in CLI provider test.

2. Fix stale runtime state clearing.
   - Valid health check should clear old last error fields.
   - Valid health check should reset consecutive error counter.

3. Fix GitHub header/version behavior.
   - Use safer default GitHub API version.
   - Allow config headers to override adapter defaults.

4. Add a key consistency diagnostic panel.
   - Show runtime state, latest health check, inventory key result, generated aliases count.
   - This should make future `valid but degraded somewhere else` cases obvious.

5. Add integration test for real-world GitHub catalog response shape.
   - Root array.
   - `supported_input_modalities`.
   - `limits.max_input_tokens`.
   - IDs like `openai/gpt-4.1-mini`.

## Server Commands For Next Debug Round

Run these after installing the next build:

```bash
sor providers test
sor providers inventory --refresh
sor keys list --all
journalctl -u sor -n 100 --no-pager
```

If GitHub still shows degraded, capture the exact row from both:

```text
providers test
providers inventory --refresh
```

The two commands use different validation paths, so comparing them tells us where the mismatch starts.
