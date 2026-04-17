# Cline + `auto/free` Routing Fix Plan

This document tracks the changes needed to make `auto/free` reliable for Cline and other
OpenAI-compatible agent clients without silently falling back to paid models.

## Implementation Status

Implemented in the current pass:

- Cline-like automatic API test mode.
- OpenAI-compatible error body with preserved SOR diagnostics.
- Upstream provider error metadata and OpenRouter free-tier rate-limit scope detection.
- Strict `auto/free` attempt budget with immediate stop on provider free-tier `429`.
- Free-only diagnostics in route preview and API test failures.

Deferred:

- Per-model negative memory/cooldown. The current fix bounds `auto/free` attempts and stops
  free-tier amplification; model-level cooldown can be added separately if repeated same-model
  failures remain a practical issue.

## Problem Summary

Observed behavior:

- `sor` automatic API test for `auto/free` succeeds.
- Cline configured as OpenAI Compatible with model `auto/free` receives:

```text
[OPENAI] 429 status code (no body)
{"message":"429 status code (no body)","status":429,"modelId":"auto/free","providerId":"openai"}
```

Important context:

- `providerId=openai` is Cline's OpenAI-compatible provider label, not the real upstream provider.
- `sor routes preview --model auto/free` shows 24 free candidates, all under `openrouter`.
- `sor providers inventory --refresh` and `sor providers consistency` show valid keys and inventory.
- Therefore the alias and key lifecycle are working; the failure is in request/runtime behavior.

Most likely cause:

- Cline sends a heavier streaming/agent request than the simple SOR API test.
- OpenRouter free-tier requests can hit account/global free limits.
- SOR currently treats all `429` as a generic model/key failure and can try many free candidates in one client request.
- For OpenRouter free tier, retrying many `:free` models can amplify the rate-limit problem instead of solving it.

## Non-Goal

Do not make `auto/free` fall back to paid models.

`auto/free` must remain strict free-only. Any optional paid/cheap fallback must be a different explicit alias or user setting later, not default `auto/free` behavior.

## Evidence To Collect First

After reproducing the Cline failure, inspect recent attempts:

```bash
/usr/local/share/simple-open-road/.venv/bin/python - <<'PY'
import sqlite3

db = "/usr/local/share/simple-open-road/data/gateway.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
for row in con.execute("""
select created_at, route_alias, provider, key_id, model, outcome, error_class, latency_ms
from request_attempts
order by id desc
limit 80
"""):
    print(dict(row))
PY
```

Expected confirmation pattern:

- Many rows for one Cline request.
- `route_alias = auto/free`.
- `provider = openrouter`.
- Multiple different `:free` models.
- `error_class = rate_limit`.

If this appears, the root cause is rate-limit amplification across free candidates.

## External Behavior To Match

OpenRouter:

- `:free` models have free usage limits.
- Free-tier rate limits can be account/global, not just one model.
- Streaming errors before first token are returned as normal HTTP errors such as `429`.

LiteLLM-style gateways:

- Separate retry, cooldown, and fallback behavior.
- Rate-limit handling can be model/group aware.
- Cooldowns prevent repeatedly selecting a failing deployment/model group.

SOR should adopt the useful parts without changing the free-only policy.

## Change 1: Add Cline-Like API Test Mode

Why:

- Current API test only sends a tiny non-stream request:

```json
{
  "model": "auto/free",
  "messages": [{"role": "user", "content": "hello"}]
}
```

- Cline likely sends streaming, tool schemas, larger system prompts, and agent-specific parameters.
- We need a local reproducer that approximates Cline without using VS Code.

Files:

- `app/cli/app.py`

Implementation:

- Add a test mode selector before automatic API test:
  - `simple`: current behavior.
  - `stream`: same prompt with `stream: true`.
  - `tools`: non-stream request with simple tool schema.
  - `cline-like`: stream request with a larger system prompt and tool schema.

Example `cline-like` payload:

```json
{
  "model": "auto/free",
  "stream": true,
  "messages": [
    {
      "role": "system",
      "content": "You are an autonomous coding assistant. Use tools only when needed. Answer concisely."
    },
    {
      "role": "user",
      "content": "привет, как твои дела?"
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "read_file",
        "description": "Read a file from the workspace.",
        "parameters": {
          "type": "object",
          "properties": {
            "path": {"type": "string"}
          },
          "required": ["path"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  "stream_options": {"include_usage": true}
}
```

Output should include:

- HTTP status.
- Answered model on success.
- Failed candidates on failure.
- For streaming, first meaningful chunk or stream error details.

Tests:

- `tests/unit/test_cli_app.py`
- Add tests for payload mode selection and stream error display.

## Change 2: Add Attempt Diagnostics To Final Provider Errors

Why:

- Current route diagnostics are rich for `503 No healthy route candidates`.
- But when the router has a final provider error, it raises that error directly:

```python
if final_error is not None:
    raise final_error
```

- For Cline this becomes `429 no body`, and the user loses visibility into which candidates failed.

Files:

- `app/router/engine.py`
- `app/api/routes_public.py`
- possibly `app/core/errors.py`

Implementation:

- When raising final errors after routing attempts, attach `details`:
  - request analysis.
  - route memory.
  - candidates attempted/skipped.
  - attempts summary.

Example error detail:

```json
{
  "message": "Provider openrouter stream error 429: ...",
  "type": "rate_limit",
  "provider": "openrouter",
  "key_id": "3",
  "details": {
    "route_alias": "auto/free",
    "free_only": true,
    "attempts": [
      {
        "provider": "openrouter",
        "model": "nvidia/nemotron-3-nano-30b-a3b:free",
        "outcome": "failure",
        "error_class": "rate_limit"
      }
    ]
  }
}
```

Tests:

- `tests/unit/test_runtime_behaviors.py`
- `tests/integration/test_api_gateway_flow.py`
- Add a route where all generated free candidates return `429` and assert response includes candidate/attempt diagnostics.

## Change 3: Detect OpenRouter Account/Free-Tier Rate Limits

Why:

- A `429` can mean:
  - one model is busy/rate-limited;
  - the whole OpenRouter free tier/account is rate-limited;
  - Cloudflare/DDoS protection.

- These cases should not behave the same.

Files:

- `app/providers/openai_compatible.py`
- `app/providers/openrouter.py`
- `app/core/errors.py`

Implementation options:

1. Minimal:
   - Add `GatewayError.details` fields for HTTP error headers/body markers.
   - Preserve selected response headers:
     - `retry-after`
     - `x-ratelimit-limit`
     - `x-ratelimit-remaining`
     - `x-ratelimit-reset`
     - OpenRouter-specific rate limit headers if present.

2. Provider-specific:
   - Override OpenRouter error classification in `OpenRouterAdapter`.
   - If body/header indicates free-tier/account/global limit, set:

```json
{
  "rate_limit_scope": "provider_free_tier"
}
```

Possible body markers:

- `rate limit`
- `free model`
- `free tier`
- `requests per minute`
- `requests per day`
- `limit exceeded`

Do not rely only on body text; headers are better when available.

Tests:

- `tests/unit/test_openai_compatible_adapter.py`
- Add OpenRouter 429 fixture with headers/body and assert details contain rate-limit metadata.

## Change 4: Add Free-Alias Attempt Budget

Why:

- `auto/free` currently can try many candidates in one client request.
- For OpenRouter free tier this can multiply requests and accelerate rate limiting.
- We need free-only routing, but with bounded attempts.

Files:

- `app/config/models.py`
- `config/config.example.yaml`
- `app/router/engine.py`
- `app/router/model_planner.py` if candidate trimming belongs there.

Suggested config:

```yaml
routing:
  free_alias:
    max_candidates_per_request: 3
    stop_on_provider_free_tier_rate_limit: true
```

Behavior:

- Applies only when resolved alias category is `free` or alias is `auto/free`.
- Keep candidates free-only.
- Try at most N candidates per client request.
- If OpenRouter returns provider/account/free-tier `429`, stop immediately and return `429`.
- If one specific model returns unsupported/malformed/provider error, continue to next free candidate up to limit.

Example:

- `nvidia/nemotron...:free` returns model-specific 429 -> try next free candidate.
- `openrouter/free` returns account/free-tier 429 -> stop, do not try all 24.

Tests:

- `tests/unit/test_runtime_behaviors.py`
- Cases:
  - model-specific `429` tries next candidate.
  - provider-free-tier `429` stops immediately.
  - more than configured candidate count is not attempted.

## Change 5: Add Per-Model Negative Memory / Cooldown

Why:

- Route memory currently remembers successful `(alias, profile, context_bucket) -> provider/model`.
- If the remembered model later gets rate-limited, it can remain first until another success overwrites it.
- Key runtime state is too coarse: it applies to whole key, not model.

Files:

- `app/storage/schema.sql`
- `app/storage/repositories/route_memory_repo.py` or new repository.
- `app/router/engine.py`
- `app/cli/app.py` for diagnostics.

Option A: extend `route_model_memory`.

Add columns:

```sql
last_failure_at TEXT
last_error_class TEXT
cooldown_until TEXT
```

Option B: add new table:

```sql
CREATE TABLE IF NOT EXISTS route_model_runtime_state (
  route_alias TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  error_class TEXT,
  cooldown_until TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(route_alias, provider, model)
);
```

Behavior:

- On `rate_limit` from a candidate, mark `(route_alias, provider, model)` cooldown.
- Candidate planner should skip cooled down model for that alias.
- Do not delete positive memory immediately; just suppress it while cooldown is active.

Tests:

- `tests/unit/test_runtime_behaviors.py`
- Route memory hit candidate rate-limits, next request should not put it first until cooldown expires.

## Change 6: Make `auto/free` Diagnostics Explicit In UI

Why:

- User must understand that `auto/free` is free-only and can fail when free quota is exhausted.
- This is not the same as provider broken or key invalid.

Files:

- `app/cli/app.py`
- `docs/TROUBLESHOOTING.md`
- `docs/ADMIN_GUIDE.md`

CLI additions:

- In `Route preview`, show:
  - `Free-only: yes`
  - `Max free attempts: N`
  - `Stop on provider free-tier 429: yes/no`

- In API test failure, show:
  - `Free alias exhausted`
  - `No paid fallback was used`
  - `Try again after Retry-After / cooldown`

Example:

```text
Result: failed
Error type: rate_limit
Free-only: yes
Paid fallback: disabled
Reason: OpenRouter free-tier rate limit
Retry after: 38s
Attempted: 2 / 24 free candidates
```

## Change 7: Improve OpenAI-Compatible Error Body For Cline

Why:

- Cline currently displays `429 status code (no body)`.
- SOR may be returning FastAPI-style `{"detail": ...}`.
- Some OpenAI-compatible clients expect OpenAI-style:

```json
{
  "error": {
    "message": "...",
    "type": "rate_limit",
    "code": "rate_limit"
  }
}
```

Files:

- `app/api/routes_public.py`

Implementation:

- For `/v1/chat/completions` and `/v1/responses`, return OpenAI-compatible error shape.
- Optionally keep full SOR diagnostics under `error.sor_details`.

Example:

```json
{
  "error": {
    "message": "OpenRouter free-tier rate limit. auto/free is strict free-only; paid fallback was not used.",
    "type": "rate_limit",
    "code": "rate_limit",
    "provider": "openrouter",
    "key_id": "3",
    "sor_details": {
      "route_alias": "auto/free",
      "attempted_candidates": 2,
      "free_only": true
    }
  }
}
```

Tests:

- `tests/integration/test_api_gateway_flow.py`
- Assert OpenAI-compatible error shape for `429`, `503`, and `502`.

## Suggested Implementation Order

1. Add Cline-like API test mode.
2. Add final provider error diagnostics.
3. Preserve provider HTTP error headers/body metadata.
4. Add OpenRouter free-tier/account rate-limit detection.
5. Add `auto/free` attempt budget.
6. Add per-model negative memory/cooldown.
7. Switch public API errors to OpenAI-compatible error shape.
8. Update docs/troubleshooting.

## Acceptance Criteria

- `auto/free` never routes to paid candidates by default.
- A simple API test can still pass.
- A Cline-like stream test shows detailed success/failure.
- If OpenRouter free-tier quota is exhausted, SOR returns a clear `429` quickly without trying all 24 candidates.
- Cline no longer shows a completely opaque `no body` error if SOR can control the response shape.
- Route preview and diagnostics explain free-only behavior and cooldown state.
- Tests cover:
  - strict free-only behavior;
  - bounded free attempts;
  - provider-free-tier rate limit stop;
  - model-specific rate limit continue;
  - OpenAI-compatible error body;
  - Cline-like stream test path.
