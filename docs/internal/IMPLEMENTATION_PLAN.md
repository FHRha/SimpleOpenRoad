# AI Gateway Router — Detailed Implementation Plan

## Phase 0. Foundation Decisions
- Finalize stack: Python/FastAPI/Typer/Pydantic/HTTPX/SQLite.
- Define MVP boundaries and non-goals.
- Freeze initial provider set: Gemini, GitHub Models, OpenRouter.

Deliverables:
- requirements document
- architecture document
- implementation plan

## Phase 1. Project Skeleton and Tooling
Tasks:
- Create package layout and module boundaries.
- Add `pyproject.toml` with runtime/dev dependencies.
- Configure lint/test tooling (`ruff`, `pytest`).
- Add `.env.example`, `config/config.example.yaml`.

Acceptance:
- Project installs and runs basic command `sor --help`.

## Phase 2. Config System
Tasks:
- Define strict Pydantic models for all config sections.
- Implement loader for `.env` + YAML.
- Implement config validation and error reporting.
- Add config reload service with safe atomic swap.

Acceptance:
- Invalid config fails with actionable diagnostics.
- `sor config validate` works.

## Phase 3. Domain Models and Contracts
Tasks:
- Define DTOs for unified request/response.
- Define provider adapter interface and error classes.
- Define key records, route policy, health result, router decision.

Acceptance:
- All modules compile/import with strict typing.

## Phase 4. Storage Layer (SQLite)
Tasks:
- Implement schema creation/migrations (simple SQL script + bootstrap).
- Repositories for keys, health checks, request attempts, stats.
- Runtime state updater methods.

Acceptance:
- DB initializes on first start.
- CRUD and stat updates verified with tests.

## Phase 5. Registry and Routing Core
Tasks:
- Implement key registry with status and cooldown logic.
- Implement alias resolver (`auto/*` -> candidate list).
- Implement priority strategy and fallback traversal.
- Implement attempt tracker and decision report.

Acceptance:
- Deterministic candidate selection for same input.
- Fallback path behaves as configured.

## Phase 6. Provider Adapters

### 6.1 Shared OpenAI-Compatible Transport
Tasks:
- Build reusable adapter for OpenAI-like APIs.
- Add request/response and stream support.

### 6.2 GitHub Models Adapter
Tasks:
- Configure base URL and auth header semantics.
- Health probe and model listing.

### 6.3 OpenRouter Adapter
Tasks:
- Configure OpenRouter-specific headers/options.
- Health probe and model listing.

### 6.4 Gemini Adapter
Tasks:
- Build Gemini payload translation layer.
- Implement chat and stream adaptation.

Acceptance:
- Provider adapters pass mock integration tests.

## Phase 7. Failover and Retry Engine
Tasks:
- Implement error classifier.
- Implement policy matrix for retry/fallback per error class.
- Add exponential backoff with jitter (bounded).
- Persist failover and switch counters.

Acceptance:
- Simulated 401/429/5xx/timeout routes to expected behavior.

## Phase 8. API Server
Tasks:
- Implement auth middleware for user/admin keys.
- Add endpoints:
  - `/v1/chat/completions`
  - `/v1/responses`
  - `/health`
  - `/providers`
  - `/keys`
  - `/admin/validate-key`
  - `/admin/reload-config`
  - `/admin/stats`
- OpenAI-style error responses and trace IDs.

Acceptance:
- OpenAI-compatible clients can call gateway endpoint.
- Streaming endpoint works for supported adapters.

## Phase 9. Health-Check Subsystem
Tasks:
- Build health orchestrator and scheduler.
- On-demand validation from API and CLI.
- Update status transitions and last-check metadata.

Acceptance:
- Periodic checks run without blocking request path.

## Phase 10. CLI
Tasks:
- Implement command groups:
  - init/start/doctor
  - providers list/test
  - keys list/add/remove/enable/disable/validate
  - routes list/set-priority
  - config validate/reload
  - stats/health/logs tail
  - menu (interactive)
- Add masked output for secrets.

Acceptance:
- Core admin workflows possible without editing raw files.

## Phase 11. Observability and Diagnostics
Tasks:
- Structured JSON logging with request IDs.
- Router decision logs and failover events.
- Aggregated stats views for CLI/admin API.

Acceptance:
- Operator can identify failing key/provider quickly.

## Phase 12. Tests
Tasks:
- Unit tests:
  - config loader
  - error classification
  - key selection and cooldown logic
- Integration tests:
  - API endpoints with mocked adapters
  - retry/fallback scenarios
  - CLI command behavior
- Contract tests for adapter normalization.

Acceptance:
- Reliable test suite for core behavior.

## Phase 13. Documentation
Tasks:
- README quickstart + architecture summary.
- Config reference.
- Admin guide for CLI operations.
- Troubleshooting playbook.

Acceptance:
- New operator can deploy on VPS from docs only.

## Phase 14. Packaging and Deployment
Tasks:
- Add production run instructions (systemd/supervisor example).
- Add env templates and security notes.
- Optional Dockerfile for convenience.

Acceptance:
- Reproducible deployment path documented.

## Sequencing Notes and Compromises
- MVP prioritizes robust failover and maintainable architecture over full strategy matrix.
- Weighted/LRU/least-errors remain extension points with interface hooks prepared now.
- Full cost accounting may be approximate initially due provider differences.

## Milestone Checklist
1. Architecture + plan approved.
2. Skeleton + config + storage ready.
3. Router + adapters + failover working.
4. API + CLI + health-check complete.
5. Tests + docs + operational scripts complete.
