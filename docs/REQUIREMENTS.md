# AI Gateway Router — Requirements Formalization

## 1. Product Goal
Build a self-hosted AI gateway/router with one unified API endpoint layer (OpenAI-style) that can transparently route requests across multiple LLM providers and multiple keys per provider.

## 2. Core Functional Requirements

### 2.1 Unified API
- Provide OpenAI-like endpoints for client compatibility:
  - `POST /v1/chat/completions`
  - `POST /v1/responses`
  - `GET /health`
  - `GET /providers`
  - `GET /keys`
  - `POST /admin/validate-key`
  - `POST /admin/reload-config`
- Keep request/response format close to OpenAI API where possible.

### 2.2 Multi-Provider Support via Adapters
Initial providers:
- Gemini API
- GitHub Models
- OpenRouter

Architecture must support easy extension for:
- OpenAI
- Anthropic
- Groq
- Hugging Face
- Any OpenAI-compatible endpoint

### 2.3 Multi-Key Support per Provider
Each key has metadata and control fields:
- `id` / `alias`
- `provider`
- secret key value
- active status
- priority
- weight
- limits/tags
- cooldown policy
- max retries
- max consecutive errors
- `last_check`, `last_success`, `last_error`
- usage counters when available

### 2.4 Routing and Selection Strategies
Minimum required now:
- strict priority
- key fallback
- provider fallback

Architecture-ready (phase 2+):
- weighted round-robin
- random by weight
- fallback chain
- least recently used
- least errors

### 2.5 Error-Aware Auto Failover
Differentiate and react to:
- `401` invalid key
- `403` forbidden
- `429` rate limit
- `5xx` provider unavailable
- network timeout
- malformed response
- unsupported model

Behavior must be configurable:
- retry on same key?
- cooldown duration
- switch to next key/provider

### 2.6 Key Validation and Health Checks
- Validate key on add
- Validate by CLI on demand
- Scheduled background checks
- Provider-specific health-check implementations under one common abstraction
- Persist key states: `valid`, `invalid`, `degraded`, `blocked`

### 2.7 Configuration
- `.env` for secrets and runtime basics
- `config.yaml` for providers/keys/routes/limits/policies
- reload config without full app rewrite/redeploy

### 2.8 CLI Administration
Required command groups:
- init/start/doctor
- providers: list/test
- keys: list/add/remove/validate/enable/disable
- routes: list/set-priority
- config: edit/validate/reload
- logs: tail
- stats/health

Plus minimal interactive mode for common operations.

### 2.9 Observability
- structured logs
- request logs
- error logs
- routing decisions and failover logs
- key/provider degradation logs
- health-check logs
- stats: errors/successes/switches/latency/basic token & cost counters

### 2.10 Persistence
Minimum:
- SQLite for runtime state and statistics
- File config for declarative setup

Persist:
- providers
- keys
- routes/aliases
- health status
- stats
- log metadata (not full bulky logs)

### 2.11 Model Alias Routing
Support:
- explicit provider model (e.g. `gemini/gemini-2.5-flash`)
- auto aliases (e.g. `auto/smart`, `auto/fast`, `auto/balanced`, `auto/strong`, `auto/code`)

Server maps alias -> ordered provider/model candidates with fallback chain.
Adaptive aliases can reorder candidates locally using request-size and task-shape heuristics without an extra model call.

### 2.12 Streaming
Design and implement streaming path where provider supports it.

### 2.13 Security
- gateway master API key (for user-facing API)
- admin isolation (admin token/secret)
- secret masking in logs
- no plaintext key leaks in responses/logs
- safe key persistence with minimal exposure

### 2.14 Performance Constraints
- lightweight dependencies
- low memory footprint
- suitable for weak Linux VPS
- no unnecessary infrastructure

## 3. Non-Functional Requirements
- Clean modular architecture
- Strong typing
- Extensible provider and routing layers
- Good diagnostics and testability
- Practical documentation for operations

## 4. Scope Decision (MVP vs Phase 2)

### MVP (implemented now)
- FastAPI server + OpenAI-style endpoints
- 3 providers (Gemini, GitHub Models, OpenRouter)
- Priority routing with key/provider fallback
- Error classification + retry/fallback policy
- Key health-check + validation
- SQLite state and stats
- Typer CLI for core admin flows
- Structured JSON logging
- Config reload endpoint and CLI command

### Phase 2 (future-ready hooks)
- Advanced balancing strategies (WRR/LRU/least-errors)
- Rate limits for gateway clients
- multi-tenant gateway API keys/quotas
- region-aware routing
- web dashboard
- richer cost/token accounting
