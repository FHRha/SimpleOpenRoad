# Project Structure

This page is a maintainer-oriented map of the repository. For runtime behavior, see [Architecture](ARCHITECTURE.md) and [Routing and Model Selection](ROUTING.md).

```text
SimpleOpenRoad/
  app/
    api/              FastAPI routes, auth dependencies, OpenAI-compatible schemas.
    cli/              Typer commands and interactive terminal panel.
    config/           Pydantic config models, YAML/env loading, reload support.
    core/             Shared constants, errors, security helpers, utility types.
    health/           Provider/key validation and health-check orchestration.
    inventory/        Provider model discovery, classification, alias generation.
    observability/    Structured logging and metrics helpers.
    providers/        Provider adapters and shared OpenAI-compatible transport.
    registry/         Provider/key registry abstractions.
    router/           Alias resolution, request analysis, selection, failover.
    services/         Orchestration used by API and CLI.
    storage/          SQLite schema, connection helpers, repositories.

  config/
    config.example.yaml

  docs/
    README-linked user and operator documentation.
    internal/         Historical plans, triage notes, and implementation notes.

  scripts/
    Build, install, and release helper scripts.

  tests/
    fixtures/
    integration/
    unit/

  .env.example
  install.sh
  pyproject.toml
  README.md
```

## Provider Adapters

Provider-specific code lives in `app/providers/`.

| File | Purpose |
|---|---|
| `openai_compatible.py` | Shared transport for providers with OpenAI-style APIs. |
| `gemini.py` | Gemini request/response translation. |
| `github_models.py` | GitHub Models catalog and chat adapter. |
| `groq.py` | Groq OpenAI-compatible adapter. |
| `cloudflare_workers_ai.py` | Cloudflare Workers AI adapter with account-scoped requests. |
| `openrouter.py` | OpenRouter adapter and free-route handling. |
| `together.py` | Together AI adapter and catalog normalization. |
| `cerebras.py` | Cerebras OpenAI-compatible adapter. |
| `registry.py` | Provider adapter registration. |

## Routing and Inventory

Routing and inventory are intentionally separate.

| Area | Main Files | Responsibility |
|---|---|---|
| Inventory | `app/inventory/*` | Discover provider models, normalize metadata, classify models, build generated aliases. |
| Routing | `app/router/*` | Resolve requested model, analyze request shape, order candidates, apply route memory, retries, failover, and quarantine. |
| Runtime state | `app/storage/repositories/*` | Persist key state, attempts, usage stats, route memory, and model quarantine. |

Generated aliases such as `auto/fast` and `auto/general` come from inventory. Runtime decisions such as skipping a quarantined model happen in the router.

## Storage

SQLite is the local runtime store. The schema is in `app/storage/schema.sql`.

Important repository files:

| Repository | Stores |
|---|---|
| `keys_repo.py` | Key runtime state, cooldowns, health status. |
| `health_repo.py` | Health-check history. |
| `attempts_repo.py` | Request attempt diagnostics. |
| `stats_repo.py` | Usage and latency aggregates. |
| `route_memory_repo.py` | Successful model memory per alias/profile/context bucket. |
| `model_runtime_repo.py` | Model failure counters and quarantine windows. |

## Documentation Layout

Public/user docs:

- [README](../README.md)
- [Getting Started](GETTING_STARTED.md)
- [Providers](PROVIDERS.md)
- [Routing and Model Selection](ROUTING.md)
- [Config Reference](CONFIG_REFERENCE.md)
- [Admin Guide](ADMIN_GUIDE.md)
- [Troubleshooting](TROUBLESHOOTING.md)

Maintainer docs:

- [Architecture](ARCHITECTURE.md)
- [Project Structure](PROJECT_STRUCTURE.md)
- [Test Plan](TEST_PLAN.md)
- [Release Process](RELEASE.md)

Historical and implementation notes belong under `docs/internal/`.
