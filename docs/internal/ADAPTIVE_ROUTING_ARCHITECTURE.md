# Adaptive Routing Architecture

## Purpose

This document defines the target architecture for smarter per-request routing in SimpleOpenRoad.

The gateway must not route only by prompt length or static alias order. A short prompt can still be a complex planning, architecture, debugging, or risk-analysis task. The solution must stay lightweight enough to run on weak VPS hardware.

Core requirements:

- local-only analysis, no extra LLM call
- deterministic and fast execution
- no heavy NLP dependencies
- explainable diagnostics
- compatible with generated provider inventory aliases
- safe defaults that prefer `general` over `fast` when uncertain

## Current Problem

Simple token-count routing is too weak.

Bad cases:

- `make an auth migration plan` is short, but should not go to a tiny model.
- `choose a gateway architecture` is short, but reasoning-heavy.
- `hello` and API smoke tests should use the cheapest fast route.
- `explain this code briefly` may not need the strongest code model.
- `read files and edit the repo` needs tool-capable/code routing even if the user prompt is short.

The new layer must analyze intent and risk before choosing the alias bucket.

## Design Principles

- Do not use an LLM classifier. It adds latency, cost, load, and another failure mode.
- Use substring checks, small regexes, and weighted features.
- Use token estimate as one feature, not the main decision.
- Keep the first implementation mostly hardcoded and tune from diagnostics.
- Route memory may reorder candidates, but must never block fallback.
- Direct explicit model requests must bypass adaptive bucket switching.
- `auto/free` must never silently upgrade to paid routes.
- `auto/reasoning` may use `fast` only for clearly trivial prompts.

## High-Level Flow

1. Normalize request text from `messages`, `input`, `instructions`, and selected metadata.
2. Estimate tokens cheaply by character count.
3. Extract boolean and weighted features.
4. Classify request intent.
5. Compute complexity score.
6. Assign context bucket.
7. Resolve target route profile.
8. Select generated alias bucket or direct candidate list.
9. Apply route memory for the same `alias + profile + context_bucket`.
10. Run existing retry/failover policy.
11. On success, update route memory.
12. Expose selected model and analysis reasons in diagnostics.

## Target Analysis Object

The analyzer should return a small object, for example:

```python
RequestRouteAnalysis(
    intent="planning",
    profile="reasoning",
    complexity_score=72,
    context_bucket="small",
    token_estimate=420,
    requires_tools=False,
    reasons=[
        "planning_keyword: plan",
        "risk_keyword: migration",
        "architecture_domain: auth",
    ],
)
```

This object should be created without DB access, network calls, or provider calls.

## Intent Categories

### `trivial`

Examples:

- hello
- ping
- smoke test
- simple API test prompts

Routing preference:

- `fast`

### `light`

Examples:

- short translation
- grammar fix
- rewrite
- short summary
- simple explanation

Routing preference:

- `fast`
- fallback to `general`

### `standard`

Examples:

- normal Q&A
- everyday explanation
- moderate comparison
- normal recommendation

Routing preference:

- `general`
- use `fast` only when confidence is high and no risk markers exist

### `planning`

Examples:

- implementation plan
- roadmap
- architecture proposal
- migration strategy
- approach selection

Routing preference:

- minimum `general`
- prefer `reasoning` when risk, architecture, or production markers exist

### `analysis`

Examples:

- tradeoff analysis
- compare options
- evaluate risks
- investigate problem
- optimize system

Routing preference:

- `reasoning`
- allow `general` for low-risk analysis

### `code`

Examples:

- debug
- refactor
- stack trace
- repo work
- file editing
- tools present

Routing preference:

- `code`
- if unavailable, use tool-capable `reasoning/general`

### `critical`

Examples:

- security
- auth
- billing
- payments
- database migration
- production incident
- data loss

Routing preference:

- never `fast`
- minimum `general`
- usually `reasoning` or `code`

## Feature Extraction

The analyzer should scan normalized text once.

Expected complexity:

- Time: `O(n)` where `n` is request text length.
- Memory: `O(1)` plus normalized text and capped reasons list.
- Network: none.
- Provider calls: none.
- LLM calls: none.

Feature examples:

- `has_tools`
- `has_code_block`
- `has_stacktrace`
- `has_file_reference`
- `has_planning_keyword`
- `has_architecture_keyword`
- `has_risk_keyword`
- `has_security_keyword`
- `has_production_keyword`
- `has_comparison_keyword`
- `has_optimization_keyword`
- `has_trivial_keyword`
- `has_light_task_keyword`
- `token_estimate`
- `message_count`

## Keyword Groups

Keyword groups should live in one module and stay small.

Initial groups:

- Planning: `plan`, `roadmap`, `steps`, `implementation`, `migration`, `strategy`
- Architecture: `architecture`, `design`, `scalability`, `gateway`, `auth`, `database`
- Analysis: `analyze`, `compare`, `evaluate`, `tradeoff`, `risk`, `investigate`
- Code: `debug`, `refactor`, `traceback`, `pytest`, `function`, `class`, `import`
- Critical: `security`, `auth`, `payment`, `billing`, `production`, `data loss`
- Trivial: `hello`, `hi`, `ping`, `test`, `smoke`
- Light: `translate`, `rewrite`, `grammar`, `summarize briefly`

Non-English keywords can be added later, but the file should keep ASCII-safe defaults or load localized patterns from config.

## Complexity Score

The score should be additive and capped to `0..100`.

Suggested starting weights:

- trivial marker: `-40`
- light marker: `-20`
- planning marker: `+30`
- architecture marker: `+35`
- analysis marker: `+25`
- code marker: `+30`
- tools present: `+45`
- security/critical marker: `+45`
- production marker: `+35`
- multiple constraints: `+15`
- context `32k+`: `+15`
- context `128k+`: `+30`

Suggested interpretation:

- `0..10`: trivial/light
- `11..35`: standard
- `36..65`: planning/analysis
- `66+`: deep/code/critical

These thresholds should be tuned from Route Preview and real requests.

## Context Buckets

Context bucket is not a hard model limit. It is a route-memory key and coarse compatibility signal.

Initial buckets:

- `small`: `< 8k`
- `medium`: `8k..32k`
- `large`: `32k..128k`
- `huge`: `128k+`

Reasoning:

- Modern models often support much more than 32k.
- Small prompts can still need strong reasoning.
- Route memory must not reuse a model that worked for 2k context on a 150k context request.

Future improvement:

- Store `max_input_tokens`, `max_output_tokens`, and `max_context_tokens` per model.
- Skip models with known insufficient context before provider calls.

## Alias Bucket Rules

### `auto/fast`

- `trivial/light` -> `fast`
- `standard` -> `fast`, fallback to `general`
- `planning/analysis/critical` -> upgrade to `general`
- `code/tools` -> upgrade to `code` if available

### `auto/general`

- `trivial/light` -> `fast` only with high confidence
- `standard` -> `general`
- `planning/analysis` -> `general` or `reasoning`
- `critical` -> `reasoning`
- `code/tools` -> `code`

### `auto/reasoning`

- `trivial` -> `fast` or `general`
- `light` -> `general`
- `standard` -> `general`
- `planning/analysis/critical` -> `reasoning`
- `code/tools` -> `code` or tool-capable `reasoning`

Important floor:

- A short planning, architecture, risk, migration, auth, security, or production prompt must not go to `fast`.
- `auto/reasoning` can use `fast` only for clearly trivial smoke-test prompts.

### `auto/code`

- tools present -> tool-capable code candidates
- stacktrace/repo/refactor -> code candidates
- simple code explanation -> `general` or `code` depending on score
- no code candidates -> tool-capable `general/reasoning`

### `auto/free`

- stay within free candidates or free special routes
- rank by intent inside free candidates
- if no free candidate fits, return a clear diagnostic instead of silently using paid routes

## Route Memory

Route memory stores the last successful model per:

```text
route_alias + profile + context_bucket
```

Suggested fields:

- `route_alias`
- `intent`
- `profile`
- `context_bucket`
- `provider`
- `model`
- `success_count`
- `avg_latency_ms`
- `last_success_at`
- optional `failure_count_since_success`

Behavior:

1. Build candidates from generated aliases.
2. Analyze request.
3. Apply context and capability filters.
4. Look up route memory.
5. If remembered model is still present and healthy, move it to the front.
6. If it fails, continue normal fallback.
7. On success, update memory.

Route memory must not override:

- direct exact model requests
- direct `provider/model` requests
- disabled providers or keys
- cooldown or blocked key state
- known context incompatibility

## Diagnostics

Route Preview and Automatic API Test should show:

- requested alias
- detected intent
- route profile
- complexity score
- context bucket
- token estimate
- selected candidate source:
  - generated alias bucket
  - route memory
  - direct model
- analysis reasons
- skipped candidates and skip reasons

Example:

```text
Intent: planning
Profile: reasoning
Complexity: 72
Context bucket: small
Reasons: planning_keyword: plan, architecture_keyword: auth, risk_keyword: migration
Route memory: miss
Selected bucket: auto/text/reasoning
```

## Performance Budget

Target overhead per request:

- Analyzer CPU: under 1 ms for normal prompts.
- Analyzer memory: one normalized string plus capped reasons list.
- Route memory lookup: one indexed SQLite read only for aliases.
- Route memory write: one SQLite upsert only on success.
- No extra HTTP calls.
- No extra provider calls.
- No extra background jobs.

Large prompt behavior:

- Single pass over text.
- Avoid expensive regex where substring checks are enough.
- Cap diagnostic reasons to about 10.

## Future Config Surface

Initial implementation can use safe defaults.

Later config:

```yaml
routing:
  adaptive:
    enabled: true
    route_memory: true
    memory_ttl_hours: 168
    diagnostics: true
```

Later per-model context override:

```yaml
model_capabilities:
  context_limits:
    - provider: openrouter
      model_pattern: "openai/gpt-5.4-nano"
      max_context_tokens: 128000
```

## Implementation Plan

### Step 1. Request Analyzer

Create:

- `app/router/request_analyzer.py`

Responsibilities:

- normalize request text
- estimate tokens
- extract features
- classify intent/profile
- return score and reasons

### Step 2. Planner Integration

Update planner to consume `RequestRouteAnalysis`.

Responsibilities:

- map profile to generated alias bucket
- enforce alias floors
- preserve direct model behavior

### Step 3. Route Memory Integration

Use memory only after candidate generation and filtering.

Responsibilities:

- key by `alias + profile + context_bucket`
- prefer remembered model if still valid
- update on success
- ignore for direct model requests

### Step 4. Context Limits

Add optional context metadata per model.

Responsibilities:

- parse limits from provider catalogs where available
- store limits in inventory
- skip candidates that cannot fit the request
- show `context_too_large` diagnostics

### Step 5. Diagnostics and CLI

Expose analyzer output in:

- Route Preview
- Automatic API Test
- Troubleshooting output
- optional debug logs

### Step 6. Tests

Required tests:

- short planning prompt does not route to tiny fast model
- smoke test can route to fast
- `auto/reasoning` keeps reasoning floor for planning/analysis
- tools route to code/tool-capable models
- route memory applies only for same profile and context bucket
- route memory does not override direct model requests
- context-too-large skips candidate when limits are known
- diagnostics include reasons

## Risks and Mitigations

### Keyword heuristics are imperfect

Mitigation:

- conservative fallback to `general`
- diagnostics show reasons
- manual overrides later

### False positives into expensive models

Mitigation:

- keep `critical/reasoning` thresholds high
- use `general` for ambiguous short prompts
- keep `auto/free` cost-constrained

### Route memory locks into a bad model

Mitigation:

- memory only reorders candidates
- fallback still works
- future TTL and failure counters

### Large prompts slow analysis

Mitigation:

- single-pass scan
- no heavy NLP dependencies
- cap diagnostics
- cheap token estimate

## Target Outcome

After implementation:

- Smoke tests stay fast and cheap.
- Short but complex planning prompts do not go to tiny models.
- Long context routes to models that can plausibly handle it.
- Repeated similar requests reuse the last successful model.
- Users can inspect why a model was selected.
- The system remains lightweight enough for weak VPS hardware.
