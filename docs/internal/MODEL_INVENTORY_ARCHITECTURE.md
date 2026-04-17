# Model Inventory Architecture

## Purpose

This document defines the target architecture for provider-driven model discovery, classification, and alias generation in SimpleOpenRoad.

The goal is to replace static hand-maintained model alias chains with a runtime-aware system built from the models that are actually available for the user's configured provider keys.

This architecture must support:

- text/chat routing as the primary scenario
- future image/video/audio model groups
- provider-specific special routes
- manual overrides when provider catalogs are incomplete or misleading
- clear panel UX so users can see what is available and why

## Current Problem

The current alias system is mostly static. That creates several classes of problems:

- aliases may include models that are not available for the user's keys
- aliases may include models that exist in catalogs but do not work for the current API path or payload style
- providers expose mixed catalogs with text, image, video, embedding, TTS, and internal/special routes
- a key can validate successfully while later failing on a chosen model
- free, fast, strong, and code-oriented groups drift over time as providers change catalogs

The replacement system must use discovered provider inventory as the source of truth.

## Design Principles

- Runtime inventory is the primary source of truth.
- Static lists should be removed as the main routing mechanism.
- Provider catalogs must be normalized before they are used.
- Text/chat models must be separated from media and non-chat models.
- Provider-specific meta-routes such as `openrouter/free` must be handled explicitly, not treated as ordinary discovered models.
- Generated aliases must be inspectable by the user.
- Manual override rules must exist because provider metadata is not fully reliable.
- Classification must be lightweight and deterministic enough to run on a small VPS.

## High-Level Flow

1. Discover raw model catalogs from enabled providers with valid keys.
2. Normalize each raw model entry into a common internal structure.
3. Filter models by modality and supported usage.
4. Classify models into categories such as free, fast, general, reasoning, and code.
5. Merge in provider special routes.
6. Apply manual overrides.
7. Generate provider-scoped aliases.
8. Generate global aliases from provider-scoped aliases.
9. Show inventory and aliases in the terminal panel.
10. Refresh inventory on relevant lifecycle events.

## Core Entities

### DiscoveredModel

Represents one raw model exposed by a provider key after normalization.

Suggested fields:

- `provider`
- `model_id`
- `display_name`
- `source_key_id`
- `modality`
- `supports_chat`
- `supports_responses`
- `supports_stream`
- `supports_tools`
- `is_free`
- `is_preview`
- `is_special`
- `is_deprecated`
- `is_text_candidate`
- `excluded_reason`
- `raw_metadata`
- `discovered_at`

### ProviderSpecialRoute

Represents provider-defined meta-routes that are not ordinary models but should still be available for routing.

Examples:

- `openrouter/free`
- `openrouter/auto`

Suggested fields:

- `provider`
- `route_id`
- `modality`
- `supports_chat`
- `supports_tools`
- `category_hints`
- `notes`

### ModelClassification

Represents the local classification result for a discovered model.

Suggested fields:

- `provider`
- `model_id`
- `modality`
- `free_score`
- `fast_score`
- `general_score`
- `reasoning_score`
- `code_score`
- `tool_capable`
- `tool_disabled`
- `classification_tags`
- `classification_reason`

### GeneratedAlias

Represents one generated alias and the ordered candidate list behind it.

Suggested fields:

- `alias_id`
- `scope`
- `modality`
- `category`
- `provider_scope`
- `candidates`
- `generated_at`
- `generation_reason`

### ManualOverride

Represents explicit local rules that alter discovery or classification behavior.

Suggested fields:

- `provider`
- `model_pattern`
- `action`
- `value`
- `reason`

Supported actions should include:

- `force_include`
- `force_exclude`
- `force_modality`
- `force_category`
- `force_tool_capable`
- `force_tool_disabled`

## Modalities

The architecture must explicitly separate model families by modality.

Initial modality list:

- `text`
- `image`
- `video`
- `audio`
- `embedding`
- `other`

The default OpenAI-compatible text gateway should only use `text`.

Media support can be added later without polluting text alias generation.

## Filtering Layer

Before category classification, models must pass a hard pre-filter for the requested modality and usage.

For the initial text implementation, exclude obvious non-text or unsupported model families by metadata or name patterns.

Examples of likely non-text exclusions:

- `embedding`
- `image`
- `audio`
- `tts`
- `generate`
- `veo`
- `imagen`
- `lyria`
- `robotics`
- `computer-use`
- `live`
- `research`

This filter must be centralized and explainable.

## Classification Layer

Classification must be based on a lightweight heuristic scoring model plus manual overrides.

Initial categories for `text`:

- `free`
- `fast`
- `general`
- `reasoning`
- `code`

Suggested interpretation:

- `free`: models/routes intentionally suitable for zero-cost or free-tier usage
- `fast`: low-latency, smaller, cheaper, lightweight models
- `general`: recommended default for ordinary chat and mixed workloads
- `reasoning`: stronger long-context or deeper reasoning models
- `code`: models more suitable for coding and repository work

Suggested classification hints by model name:

- `nano`, `mini`, `lite`, `flash`, `haiku`, `small` -> fast bias
- `pro`, `opus`, `sonnet`, `thinking`, `reasoning`, `o3`, `o4` -> reasoning bias
- `codex`, `coder`, `codestral`, `devstral` -> code bias
- `:free`, explicit provider free routes, known free families -> free bias

These are hints only, not the final source of truth.

## Provider Special Routes

Provider special routes must be handled separately from discovered models.

Initial examples:

- OpenRouter:
  - `openrouter/free`
  - `openrouter/auto`

Rules:

- special routes are not stored as ordinary discovered models
- they can be exposed in UI and routing as a separate class of candidates
- they may be included in generated aliases only by explicit generation rules
- they should remain visible to the user as provider-defined shortcuts

## Alias Structure

Generated aliases should exist at two levels.

### Provider-scoped aliases

Examples:

- `gemini/text/fast`
- `gemini/text/general`
- `gemini/text/reasoning`
- `gemini/text/code`
- `gemini/text/free`
- `openrouter/text/free`

### Global aliases

Examples:

- `auto/text/free`
- `auto/text/fast`
- `auto/text/general`
- `auto/text/reasoning`
- `auto/text/code`

Optional short aliases can be provided as compatibility shims:

- `auto/free` -> `auto/text/free`
- `auto/fast` -> `auto/text/fast`
- `auto/general` -> `auto/text/general`
- `auto/reasoning` -> `auto/text/reasoning`
- `auto/code` -> `auto/text/code`

If short aliases are kept, they must be generated from the same runtime system and not hand-maintained separately.

## Generation Rules

Alias generation must follow these steps:

1. select discovered models that match the target modality
2. exclude disabled or unsupported models
3. apply manual overrides
4. merge provider special routes if configured for that category
5. sort candidates by category-specific score
6. remove duplicate or conflicting entries
7. emit provider aliases
8. build global aliases from provider aliases using provider availability and priority

## Validation and Enrichment

Provider catalogs alone are not sufficient.

We must eventually enrich discovered models with lightweight validation state:

- `listed`
- `chat_ok`
- `stream_ok`
- `tools_ok`
- `responses_ok`

This can be done incrementally:

- phase 1: inventory only
- phase 2: optional lightweight capability probes
- phase 3: runtime success/failure feedback influences future ranking

## Runtime Storage

The system should persist or cache generated state so that it does not need to be rebuilt on every request.

Suggested runtime layers:

- raw discovered provider inventory
- normalized inventory
- classification output
- generated aliases
- last refresh metadata

Inventory refresh should happen on:

- startup
- manual refresh from the panel
- provider key add/remove/update
- config reload
- successful provider key validation

## Panel UX

The terminal panel must expose this system clearly.

Recommended screens:

### Available Models

Shows discovered models with columns such as:

- `#`
- `Provider`
- `Model`
- `Modality`
- `Free`
- `Fast`
- `Reasoning`
- `Code`
- `Tools`
- `Status`

### Generated Aliases

Shows generated aliases with columns such as:

- `Alias`
- `Scope`
- `Category`
- `Candidates`
- `Top candidates`

### Provider Special Routes

Shows provider-defined special routes such as OpenRouter meta-routes.

### Overrides

Shows active local overrides and allows editing them later.

### Refresh Inventory

Manual action to rescan provider catalogs and rebuild generated aliases.

## Configuration Model

The long-term configuration should move away from hardcoded route alias candidate chains and toward:

- discovery settings
- override rules
- special-route generation controls
- optional compatibility alias toggles

Potential future config areas:

- `inventory.providers.<name>.enabled`
- `inventory.providers.<name>.special_routes`
- `inventory.overrides`
- `inventory.short_aliases_enabled`
- `inventory.refresh`

## First Implementation Scope

The first implementation should focus on text routing only.

### Phase 1

- add runtime model inventory discovery
- normalize provider models
- add text pre-filter
- add lightweight classification
- generate provider-scoped text aliases
- generate global text aliases
- add panel views for models and aliases

### Phase 2

- add manual overrides
- add special route support for OpenRouter
- add lightweight capability validation markers
- improve ranking using runtime success history

### Phase 3

- add image/video/audio modality families
- add modality-specific provider aliases
- add richer plugin guidance and export views

## Explicit Non-Goals For The First Stage

- no interactive autocomplete like IDE clients
- no full media request routing in the first stage
- no heavy benchmarking across all models
- no per-request live regeneration of aliases
- no dependence on provider metadata being perfect

## Open Questions

- how much provider metadata is reliable enough to use directly
- whether provider special routes should appear in default global aliases
- how aggressive capability probing should be on small servers
- whether short aliases should remain or be replaced entirely by explicit modality aliases
- how to represent pricing hints when providers do not expose them cleanly
- how to expose direct model selection in the panel without overwhelming users

## Implementation Checklist

- define inventory data structures
- define normalization rules per provider
- define text pre-filter
- define classifier and scoring rules
- define special route registry
- define generated alias builder
- define override model
- add panel inventory screens
- add refresh workflow
- migrate routing to generated aliases
- remove static alias chains after parity is reached

## Rollout By Module

This section maps the architecture into concrete project modules so implementation can proceed in controlled steps.

### Existing Modules That Will Be Touched

- `app/config/models.py`
- `app/config/loader.py`
- `app/providers/base.py`
- `app/providers/registry.py`
- `app/router/alias_resolver.py`
- `app/router/model_planner.py`
- `app/router/engine.py`
- `app/cli/app.py`
- `app/services/admin_service.py`

### New Modules To Add

Suggested initial module layout:

- `app/inventory/models.py`
- `app/inventory/discovery.py`
- `app/inventory/normalizer.py`
- `app/inventory/filtering.py`
- `app/inventory/classifier.py`
- `app/inventory/special_routes.py`
- `app/inventory/aliases.py`
- `app/inventory/cache.py`

Optional later modules:

- `app/inventory/validator.py`
- `app/inventory/overrides.py`
- `app/inventory/presenter.py`

### Data Model Layer

`app/inventory/models.py` should define the internal runtime data structures:

- `DiscoveredModel`
- `ProviderSpecialRoute`
- `ModelClassification`
- `GeneratedAlias`
- `InventorySnapshot`

This layer should be independent from the current routing config format.

### Discovery Layer

`app/inventory/discovery.py` should:

- iterate enabled providers
- skip providers without working keys
- call provider-specific `list_models`
- return raw provider payloads plus normalized inventory records

This is the first place where provider validity and inventory freshness should be recorded.

### Provider Integration

`app/providers/base.py` should eventually expose a richer discovery contract than only `list_models`.

Potential future additions:

- `discover_models()`
- `provider_special_routes()`
- `normalize_model_id()`

For the first stage, `list_models()` can remain the raw source and normalization can happen in `app/inventory/normalizer.py`.

### Normalization Layer

`app/inventory/normalizer.py` should convert raw provider model strings or payloads into `DiscoveredModel`.

Provider-specific rules belong here:

- Gemini model naming and modality hints
- OpenRouter provider/model ids and `:free` suffix handling
- GitHub model ids and future capability hints

This file must be explicit and testable. No hidden heuristics should leak into routing.

### Filtering Layer

`app/inventory/filtering.py` should implement central pre-filters:

- text-only filter
- media-only filter
- exclusion by unsupported family
- exclusion by explicit override

This module should be able to answer:

- why a model is eligible
- why a model is excluded

### Classification Layer

`app/inventory/classifier.py` should assign category scores and tags.

It should be based on:

- normalized model id
- known provider family rules
- free route flags
- preview or special flags
- optional override rules

This layer should not query providers. It should only classify already-discovered inventory.

### Special Routes Layer

`app/inventory/special_routes.py` should register provider-defined meta-routes.

Initial support:

- OpenRouter:
  - `openrouter/free`
  - `openrouter/auto`

This module should keep these routes separate from ordinary discovered models.

### Alias Builder Layer

`app/inventory/aliases.py` should generate:

- provider-scoped aliases
- global aliases
- compatibility short aliases if enabled

It must produce deterministic ordered candidate chains from `InventorySnapshot`.

### Cache Layer

`app/inventory/cache.py` should hold the latest inventory snapshot in memory and optionally persist a serialized copy later.

The cache must support:

- refresh
- read current snapshot
- invalidate on config or key changes

### Config Migration Layer

`app/config/loader.py` currently seeds static alias chains. That logic must be phased out carefully.

Migration plan:

1. keep static aliases as fallback only
2. introduce generated aliases behind a feature switch
3. move routing to generated aliases
4. remove static alias seeding once parity is confirmed

### Routing Layer Changes

`app/router/alias_resolver.py` should stop treating alias candidates as a purely static config artifact.

Target behavior:

- resolve generated aliases first
- optionally fall back to static aliases during migration
- still allow direct `provider/model` usage

`app/router/model_planner.py` should eventually consume classification metadata instead of hardcoded name-pattern scoring for static aliases.

### CLI Layer Changes

`app/cli/app.py` needs new views and workflows:

- refresh inventory
- show available models
- show generated aliases
- show provider special routes
- show exclusion reasons
- later: manage manual overrides

The panel should not require autocomplete. Numbered filtered views are sufficient.

### Admin/API Layer Changes

`app/services/admin_service.py` should expose inventory-oriented methods such as:

- `refresh_inventory()`
- `list_inventory_models()`
- `list_generated_aliases()`
- `list_provider_special_routes()`

Optional future admin API endpoints can be added after the CLI flow is proven.

## Recommended Implementation Order

### Step 1: Inventory Models And Discovery

- add `app/inventory/models.py`
- add `app/inventory/discovery.py`
- collect raw inventory from Gemini and OpenRouter
- skip GitHub until permission issue is resolved

Deliverable:

- a runtime snapshot of discovered provider models

### Step 2: Normalization And Text Filtering

- add `app/inventory/normalizer.py`
- add `app/inventory/filtering.py`
- mark text-eligible models
- record exclusion reasons

Deliverable:

- a clean text candidate pool per provider

### Step 3: Classification And Special Routes

- add `app/inventory/classifier.py`
- add `app/inventory/special_routes.py`
- generate `free`, `fast`, `general`, `reasoning`, `code` scores
- keep OpenRouter special routes separate

Deliverable:

- provider-aware classified inventory

### Step 4: Generated Aliases

- add `app/inventory/aliases.py`
- generate provider-scoped aliases
- generate global aliases
- optionally keep short compatibility aliases

Deliverable:

- generated runtime alias graph ready for routing

### Step 5: Panel Integration

- add inventory browsing views to `app/cli/app.py`
- add refresh action
- add generated alias preview

Deliverable:

- user-visible inspection of the new system

### Step 6: Routing Migration

- update alias resolution
- route through generated aliases by default
- keep static alias fallback temporarily

Deliverable:

- production traffic uses generated aliases

### Step 7: Override System

- add override model and storage shape
- allow force include/exclude/category/tool flags
- reflect override effects in the panel

Deliverable:

- operator control when provider catalogs are misleading

### Step 8: Capability Enrichment

- record lightweight chat/tool/stream success signals
- improve ranking using observed runtime behavior

Deliverable:

- smarter alias quality over time

## Persistence Strategy

Initial implementation can keep inventory in memory and rebuild it on startup or explicit refresh.

Later persistence options:

- lightweight JSON snapshot under `data/`
- SQLite tables for discovered inventory and alias snapshots

Recommended first approach:

- in-memory snapshot
- optional export/debug print for diagnostics

## Testing Strategy

Tests should be added per layer instead of only at end-to-end level.

Recommended test files:

- `tests/unit/test_inventory_normalizer.py`
- `tests/unit/test_inventory_filtering.py`
- `tests/unit/test_inventory_classifier.py`
- `tests/unit/test_inventory_aliases.py`
- `tests/unit/test_inventory_special_routes.py`
- `tests/unit/test_cli_inventory_views.py`

Existing routing and CLI tests should be extended only after unit coverage exists for the new inventory modules.

## Documentation Strategy

This architecture document is the source for the system design.

Provider-specific model notes and observed catalog rules should live in a separate companion document:

- `docs/internal/PROVIDER_MODEL_NOTES.md`

That companion file should contain:

- current provider observations
- known text-safe model families
- known exclusions
- known special routes
- open questions per provider
