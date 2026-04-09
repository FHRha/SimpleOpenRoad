# AI Gateway Router — Architecture Proposal

## 1. Stack Choice and Rationale

Selected stack: **Python + FastAPI + Typer + Pydantic + HTTPX + SQLite**.

Why this stack:
- FastAPI gives high performance async I/O, built-in OpenAPI, and easy streaming responses.
- Pydantic provides strict config/data validation.
- Typer gives a clear and productive CLI UX.
- HTTPX supports robust async HTTP with timeout/retry control.
- SQLite is simple, local, durable, and ideal for self-hosted VPS scenarios.
- Python implementation cost is lower for a feature-rich MVP with clean architecture.

Trade-off:
- Node.js/TypeScript could provide stronger compile-time typing for some teams.
- Python chosen due lower implementation complexity and strong ecosystem for API + CLI + validation.

## 2. System Context

Client tools (Cline/Continue/scripts) call the gateway's OpenAI-style endpoints.
Gateway resolves route policy -> selects provider+key -> forwards request -> normalizes response.
On failure, gateway applies retry/fallback policies and emits structured diagnostics.

## 3. High-Level Component Architecture

1. API Layer (`app/api`)
- OpenAI-compatible endpoints and admin endpoints.
- Auth checks (master key for user API, admin key for admin API).
- Request normalization into internal DTOs.

2. Router Engine (`app/router`)
- Decides provider/model/key for each attempt.
- Applies selection strategy and failover policy.
- Produces `RouterDecision` metadata.

3. Provider Adapter Layer (`app/providers`)
- Common interface `ProviderAdapter`.
- Concrete adapters:
  - Gemini
  - GitHub Models (OpenAI-compatible transport)
  - OpenRouter (OpenAI-compatible transport)
- Converts internal request/response into provider-specific payloads.

4. Key Registry + Runtime State (`app/registry`, `app/state`)
- Tracks keys, status, cooldown, counters, recent errors.
- Computes key eligibility for selection.
- Persists updates to SQLite.

5. Health Subsystem (`app/health`)
- On-demand validation.
- Scheduled background checks.
- Provider-specific checks via adapter contract.

6. Config Subsystem (`app/config`)
- Loads `.env` + `config.yaml`.
- Validates with Pydantic models.
- Supports reload through admin endpoint and CLI.

7. Storage Layer (`app/storage`)
- SQLite repositories for keys/health/stats/events.
- Small normalized schema + append-only events for diagnostics.

8. Observability (`app/observability`)
- Structured JSON logging.
- Router/failover event logging.
- Metrics and stats service (DB-backed aggregates).

9. CLI Layer (`app/cli`)
- Admin operations for keys/providers/routes/config/health/stats.
- Interactive helper for common setup actions.

## 4. Internal Data Flow

### 4.1 Request Flow
1. API endpoint receives request + auth.
2. Request converted into internal `UnifiedLLMRequest`.
3. Router resolves model alias -> ordered candidate list.
4. Key selector chooses active key for first candidate.
5. Adapter sends request to provider.
6. On success: normalize response to OpenAI-like schema, update stats.
7. On failure: classify error -> retry/fallback decision -> next attempt.
8. If all candidates fail: return normalized gateway error with trace ID.

### 4.2 Health Flow
1. Scheduler triggers periodic checks per key.
2. Adapter-specific `validate_key` runs lightweight probe.
3. Status and model availability persisted.
4. Registry updates key state (`valid`, `degraded`, etc.).

## 5. Provider Adapter Layer Design

### 5.1 Interface Contract
Core methods:
- `name()`
- `list_models(key_record)`
- `chat_completions(request, key_record, stream)`
- `responses(request, key_record, stream)`
- `validate_key(key_record)`
- `normalize_error(provider_response)`

### 5.2 Shared OpenAI-Compatible Adapter Base
- Handles providers with OpenAI-like APIs (GitHub Models, OpenRouter).
- Shared serialization, auth headers, stream handling.

### 5.3 Gemini Adapter
- Handles Gemini endpoints and payload translation.
- Maps role/content structure into Gemini format and back.

## 6. Router/Fallback Engine Design

### 6.1 Routing Inputs
- requested model (explicit or alias)
- route profile (default/admin-specified)
- runtime health of keys/providers
- per-request metadata (timeout, stream)

### 6.2 Decision Layers
1. Alias resolver: `auto/*` -> ordered candidate models.
2. Candidate filter: remove inactive/blocked/cooldown keys.
3. Key selection strategy (MVP: strict priority).
4. Retry policy per classified error.
5. Fallback policy key -> provider.

### 6.3 MVP Policy Behavior
- Select top-priority healthy key for first candidate.
- Retry on transient errors (timeout, 429, 5xx) up to policy limits.
- If key exhausted or non-retriable error: move to next key.
- If provider keys exhausted: move to next provider candidate.

## 7. Key Registry Design

Registry responsibilities:
- maintain in-memory view of config + runtime overrides
- expose key eligibility checks
- record success/failure events
- handle cooldown timers and consecutive error thresholds

State fields:
- `status`, `active`
- `consecutive_errors`
- `cooldown_until`
- `last_success_at`, `last_error_at`, `last_error_code`
- counters (`success_count`, `failure_count`, `switch_count`, `avg_latency_ms`)

## 8. Health-Check Subsystem

Health-check abstraction:
- `HealthChecker` orchestrator calls provider adapter probe methods.

Result model:
- `valid`: key passes request and can serve target models
- `degraded`: key works but with limitations or repeated transient failures
- `invalid`: auth/permission failure
- `blocked`: disabled by policy or manual admin action

Schedules:
- startup warm check (optional quick mode)
- periodic checks (config interval)
- on-demand checks from CLI/admin endpoint

## 9. Config and State Strategy

### 9.1 Config Sources
1. `.env` for secrets and environment defaults
2. `config/config.yaml` as canonical declarative config
3. SQLite for runtime state/statistics and mutable key state

### 9.2 Merge Policy
- File config is source of truth for static topology.
- Runtime DB stores mutable operational fields.
- On reload: validate full config, then atomically swap in-memory runtime config.

## 10. Security Architecture

- User API authentication via `X-API-Key` (`MASTER_API_KEY`).
- Admin endpoints via separate `X-Admin-Key`.
- Secrets masked in logs and serialized outputs.
- CLI never prints full secret keys.
- Optional bind to localhost and reverse proxy TLS in production.

## 11. API Surface (MVP)

User endpoints:
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `GET /health`
- `GET /providers`

Admin endpoints:
- `GET /keys`
- `POST /admin/validate-key`
- `POST /admin/reload-config`
- `GET /admin/stats`

## 12. CLI Architecture

Command groups:
- `sor init`
- `sor start`
- `sor doctor`
- `sor providers list|test`
- `sor keys list|add|remove|enable|disable|validate`
- `sor routes list|set-priority`
- `sor config validate|reload`
- `sor logs tail`
- `sor stats`
- `sor health`
- `sor menu` (interactive)

CLI interacts with:
- local config files
- local SQLite
- running server admin API for online operations

## 13. Contracts and Interfaces

### 13.1 `ProviderAdapter`
- Responsibilities: provider-specific request transform, auth, error normalize, health probes.
- Input/Output: internal DTOs only, no direct endpoint DTO leakage.

### 13.2 `KeyRecord`
- Immutable config fields + mutable runtime fields.

### 13.3 `RoutePolicy`
- alias mapping and fallback chain + strategy parameters.

### 13.4 `HealthCheckResult`
- status, detected models, latency, error summary, timestamp.

### 13.5 `RouterDecision`
- request id, selected alias, attempts, selected key/provider, fallback trail.

### 13.6 `RequestContext`
- trace id, client id, timeout, stream flag, profile.

### 13.7 `FailoverResult`
- success/final error, attempt history, terminal classification.

### 13.8 `CLICommandModule`
- self-contained command registration units with shared service container.

## 14. Error Classification and Decision Model

Error classes:
- `AUTH_INVALID` (401)
- `AUTH_FORBIDDEN` (403)
- `RATE_LIMIT` (429)
- `PROVIDER_UNAVAILABLE` (5xx)
- `NETWORK_TIMEOUT`
- `MALFORMED_RESPONSE`
- `UNSUPPORTED_MODEL`
- `UNKNOWN`

Decision defaults (MVP):
- `AUTH_INVALID`: mark key invalid, no same-key retry, next key/provider
- `AUTH_FORBIDDEN`: degrade key, no same-key retry
- `RATE_LIMIT`: apply cooldown, retry same key once then next key
- `PROVIDER_UNAVAILABLE`: retry same key with backoff then next key/provider
- `NETWORK_TIMEOUT`: retry same key with short backoff
- `MALFORMED_RESPONSE`: retry once then switch provider
- `UNSUPPORTED_MODEL`: immediate next route candidate/provider

## 15. Extensibility Considerations

Prepared for future:
- add new provider by implementing adapter and registering it
- add new strategy by extending `SelectionStrategy` interface
- add client-level rate limiting and quotas at API middleware
- add web dashboard over existing admin service layer
- add region-aware routing by extending candidate scoring
