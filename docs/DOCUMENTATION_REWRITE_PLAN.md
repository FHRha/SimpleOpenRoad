# Documentation Rewrite Plan

This plan tracks the documentation cleanup so the project is easier to understand, install, operate, and evaluate.

## Goals

- Make the README present the project clearly in the first 30 seconds.
- Move from implementation notes to user-facing guides.
- Explain the core value: one OpenAI-compatible endpoint with provider failover, multi-key routing, generated aliases, inventory, diagnostics, and model quarantine.
- Keep operational commands copy-pasteable.
- Preserve deeper architecture notes, but separate them from user docs.

## Target Structure

Primary user docs:

- `README.md` - product overview, quick start, common usage, docs index.
- `docs/GETTING_STARTED.md` - first install, first provider key, first request, first automatic test.
- `docs/CLIENTS.md` - OpenAI-compatible client settings, Cline-like agents, curl and streaming examples.
- `docs/DEPLOYMENT.md` - production install, service, reverse proxy, backups, updates.
- `docs/PROVIDERS.md` - provider support matrix and provider-specific notes.
- `docs/ROUTING.md` - aliases, direct model routing, adaptive routing, route memory, free routes, model quarantine.
- `docs/CONFIG_REFERENCE.md` - current YAML/env reference.
- `docs/ADMIN_GUIDE.md` - operator commands and terminal panel.
- `docs/TROUBLESHOOTING.md` - practical failure modes and diagnostics.
- `docs/ARCHITECTURE.md` - high-level internals.

Internal/historical docs:

- `docs/internal/CLINE_FREE_ROUTING_FIX_PLAN.md`
- `docs/internal/IMPLEMENTATION_PLAN.md`
- `docs/internal/PROVIDER_EXPANSION_PLAN.md`
- `docs/internal/GITHUB_DEGRADED_TRIAGE.md`
- `docs/internal/ADAPTIVE_ROUTING_ARCHITECTURE.md`
- `docs/internal/MODEL_INVENTORY_ARCHITECTURE.md`
- `docs/internal/PROVIDER_MODEL_NOTES.md`
- `docs/internal/REQUIREMENTS.md`

## Work Order

1. Rewrite `README.md` around the product story and a clean quick start.
2. Add `docs/GETTING_STARTED.md` for the first working setup.
3. Add `docs/PROVIDERS.md` for provider capabilities and provider-specific configuration.
4. Add `docs/ROUTING.md` for aliases, failover, inventory, and model quarantine.
5. Update `docs/CONFIG_REFERENCE.md` to match the current config schema.
6. Update `docs/TROUBLESHOOTING.md` with real diagnostics: Together `402`, Cloudflare account IDs, generated aliases, quarantined models.
7. Move internal planning documents into `docs/internal/` once public docs are stable. Done.

## Presentation Rules

- Prefer short sections and tables over long prose.
- Every major feature needs a concrete command or config example.
- Avoid implementation-only language in the README.
- Keep old architecture details in deeper docs, not in the landing page.
- Mention limitations honestly, especially provider-specific billing and model availability.

## Current Pass

- Create this plan.
- Rewrite `README.md`.
- Add first-pass `GETTING_STARTED`, `PROVIDERS`, and `ROUTING` docs.
- Fix config example indentation for `routing.free_alias` and `routing.model_quarantine`.
- Update `PROJECT_STRUCTURE.md` and `TEST_PLAN.md` as maintainer docs.
- Move historical implementation notes into `docs/internal/`.
- Add `CLIENTS.md` for OpenAI-compatible client setup.
- Add `DEPLOYMENT.md` for server operations.
