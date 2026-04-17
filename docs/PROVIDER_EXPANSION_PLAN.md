# Provider Expansion Plan

## Goal

Add the next provider wave to SimpleOpenRoad without fragmenting the architecture:

- Groq
- Together AI
- Cloudflare Workers AI
- Cerebras Inference

The target outcome is:

- provider keys can be added and validated through the existing CLI
- provider catalogs participate in inventory refresh
- generated aliases include newly discovered models automatically
- OpenAI-compatible gateway routes can use these providers without provider-specific hacks in routing

## Scope

This plan covers:

- provider adapter architecture
- implementation order
- file-level change map
- provider-specific risks
- acceptance checks

This plan does not yet cover:

- rewriting README/docs for end users
- adding paid-vs-trial economics logic beyond current free/fast/general classification
- advanced provider-specific media support unless inventory proves it usable

## Current State

Current provider architecture:

- `gemini` uses a custom native adapter
- `openrouter` uses the shared OpenAI-compatible adapter
- `github` uses the shared OpenAI-compatible adapter with path/header overrides

Current extension points:

- provider contract: [app/providers/base.py](E:/Code/SimpleOpenRoad/app/providers/base.py)
- shared OpenAI-compatible transport: [app/providers/openai_compatible.py](E:/Code/SimpleOpenRoad/app/providers/openai_compatible.py)
- provider registry: [app/providers/registry.py](E:/Code/SimpleOpenRoad/app/providers/registry.py)
- runtime inventory discovery: [app/inventory/discovery.py](E:/Code/SimpleOpenRoad/app/inventory/discovery.py)
- model normalization: [app/inventory/normalizer.py](E:/Code/SimpleOpenRoad/app/inventory/normalizer.py)
- special provider routes: [app/inventory/special_routes.py](E:/Code/SimpleOpenRoad/app/inventory/special_routes.py)
- gateway config models: [app/config/models.py](E:/Code/SimpleOpenRoad/app/config/models.py)
- terminal management UI: [app/cli/app.py](E:/Code/SimpleOpenRoad/app/cli/app.py)

## Provider Classification

Planned classification for this wave:

### Group A: OpenAI-compatible first

These should be implemented first as thin adapters over the shared transport:

- Groq
- Together AI
- Cerebras Inference

Expected implementation shape:

- custom provider name
- default endpoint
- optional header overrides
- optional path overrides
- shared error handling and streaming path from `OpenAICompatibleAdapter`

### Group B: Verify-first provider

- Cloudflare Workers AI

Expected implementation shape:

- either a thin OpenAI-compatible adapter if the API surface matches cleanly
- or a dedicated custom adapter if request/response/catalog shape differs materially

Rule:

- do not force Cloudflare into the shared adapter if it introduces conditionals that pollute the common path

## Architectural Rules

To keep this maintainable, the rollout should follow these rules:

1. Routing must not gain provider-specific heuristics for these integrations.
2. Inventory must remain the source of truth for generated aliases.
3. CLI must work through shared services, not direct provider branches.
4. New providers should expose model metadata through `list_model_records`, not only `list_models`.
5. Provider-specific special routes must be added only if the provider actually exposes stable route-level endpoints.
6. If a provider is only partially compatible, isolate the incompatibility inside its adapter.

## Implementation Order

### Phase 1: Core provider registration

Add provider modules and register them:

- `app/providers/groq.py`
- `app/providers/together.py`
- `app/providers/cerebras.py`
- `app/providers/cloudflare_workers_ai.py`
- update [app/providers/registry.py](E:/Code/SimpleOpenRoad/app/providers/registry.py)

Expected result:

- config can contain these provider names
- runtime registry creates adapters for enabled providers

### Phase 2: Thin OpenAI-compatible adapters

Implement these first:

- `GroqAdapter(OpenAICompatibleAdapter)`
- `TogetherAdapter(OpenAICompatibleAdapter)`
- `CerebrasAdapter(OpenAICompatibleAdapter)`

For each adapter define:

- `provider_name`
- endpoint normalization behavior
- path overrides if needed
- extra headers if needed

Expected result:

- `chat_completions`
- `responses` if supported
- `stream_chat_completions`
- `validate_key`
- `list_model_records`

### Phase 3: Cloudflare API verification layer

Before coding the final adapter:

- verify auth format
- verify model catalog endpoint
- verify chat endpoint shape
- verify whether streaming is truly supported in the same form we already normalize

Decision point:

- if compatible enough, implement a thin adapter
- if not, implement a dedicated adapter with internal normalization

Expected result:

- Cloudflare support is cleanly isolated and does not contaminate shared transport logic

### Phase 4: Inventory and normalization hardening

Expand normalization so the new providers contribute useful routing metadata:

- better token limit extraction
- better free/trial/free-tier detection where discoverable
- better tool capability extraction from metadata
- better modality mapping from provider catalogs

Files likely to change:

- [app/inventory/normalizer.py](E:/Code/SimpleOpenRoad/app/inventory/normalizer.py)
- [app/inventory/classifier.py](E:/Code/SimpleOpenRoad/app/inventory/classifier.py)
- [app/inventory/validator.py](E:/Code/SimpleOpenRoad/app/inventory/validator.py)

Expected result:

- generated aliases are relevant instead of just technically populated

### Phase 5: CLI and provider onboarding

Extend terminal UX so the new providers are first-class citizens:

- provider selection menus
- default endpoint presets
- validation output
- inventory refresh visibility

Files likely to change:

- [app/cli/app.py](E:/Code/SimpleOpenRoad/app/cli/app.py)
- `config/config.example.yaml`

Expected result:

- user can add keys for all new providers without editing YAML manually

### Phase 6: Tests

Add provider-specific test coverage:

- unit tests for each adapter
- unit tests for model catalog parsing
- unit tests for error classification
- inventory discovery tests with representative model records
- CLI smoke tests for validation/inventory output

Files likely to add:

- `tests/unit/test_groq_adapter.py`
- `tests/unit/test_together_adapter.py`
- `tests/unit/test_cerebras_adapter.py`
- `tests/unit/test_cloudflare_workers_ai_adapter.py`

Files likely to extend:

- `tests/unit/test_inventory_discovery.py`
- `tests/unit/test_cli_app.py`
- `tests/integration/test_api_gateway_flow.py`

## File-Level Change Map

### Required

- [app/providers/registry.py](E:/Code/SimpleOpenRoad/app/providers/registry.py)
- [app/providers/openai_compatible.py](E:/Code/SimpleOpenRoad/app/providers/openai_compatible.py)
- [app/config/models.py](E:/Code/SimpleOpenRoad/app/config/models.py)
- [app/cli/app.py](E:/Code/SimpleOpenRoad/app/cli/app.py)
- [app/inventory/normalizer.py](E:/Code/SimpleOpenRoad/app/inventory/normalizer.py)
- [config/config.example.yaml](E:/Code/SimpleOpenRoad/config/config.example.yaml)

### New adapter files

- [app/providers/groq.py](E:/Code/SimpleOpenRoad/app/providers/groq.py)
- [app/providers/together.py](E:/Code/SimpleOpenRoad/app/providers/together.py)
- [app/providers/cerebras.py](E:/Code/SimpleOpenRoad/app/providers/cerebras.py)
- [app/providers/cloudflare_workers_ai.py](E:/Code/SimpleOpenRoad/app/providers/cloudflare_workers_ai.py)

### Possibly required

- [app/inventory/special_routes.py](E:/Code/SimpleOpenRoad/app/inventory/special_routes.py)
- [app/inventory/classifier.py](E:/Code/SimpleOpenRoad/app/inventory/classifier.py)
- [app/inventory/discovery.py](E:/Code/SimpleOpenRoad/app/inventory/discovery.py)
- [app/core/errors.py](E:/Code/SimpleOpenRoad/app/core/errors.py)

## Provider-Specific Notes

### Groq

Target:

- very fast text inference
- likely strong fit for `fast` and maybe `code` categories depending on exposed models

Watch for:

- exact models endpoint shape
- whether `responses` is supported or only chat
- streaming semantics

Expected first use in routing:

- `auto/fast`
- provider-scoped `groq/text/fast`

### Together AI

Target:

- broad model catalog
- likely useful for `general`, `code`, `reasoning`, possibly some free/trial coverage

Watch for:

- catalog metadata quality
- whether free/trial status can be detected safely
- token limit fields

Expected first use in routing:

- `auto/general`
- `auto/code`
- provider-scoped aliases

### Cerebras Inference

Target:

- low-latency text inference
- likely useful for `fast` and `general`

Watch for:

- path compatibility with the shared transport
- availability of a proper models endpoint
- exact error response shape

Expected first use in routing:

- `auto/fast`
- `auto/general`

### Cloudflare Workers AI

Target:

- additional route diversity
- potentially useful for edge-hosted low-cost models

Watch for:

- non-standard request format
- different auth style
- different streaming semantics
- model naming and metadata shape

Expected first use in routing:

- only after compatibility is confirmed

## Acceptance Criteria

The rollout is complete for a provider when all of these are true:

1. A key can be added in the CLI.
2. `keys validate` returns a sane status.
3. `providers inventory --refresh` shows discovered models.
4. Provider models appear in generated aliases when relevant.
5. `routes preview` can show candidates from that provider.
6. Automatic API test can successfully hit at least one model.
7. Errors are returned in the existing user-facing format.

## Proposed Rollout Sequence

Recommended implementation sequence:

1. Groq
2. Together AI
3. Cerebras Inference
4. Cloudflare Workers AI

Reasoning:

- the first three are the most likely to fit the existing OpenAI-compatible architecture
- Cloudflare is the highest risk for adapter divergence and should not block the simpler wins

## Concrete Work Breakdown

### Step 1

Add provider names, adapter files, and registry wiring.

Deliverable:

- app starts with these providers configured and does not ignore them as unknown

### Step 2

Implement Groq adapter and tests.

Deliverable:

- Groq key validation
- Groq inventory discovery
- Groq API test success path

### Step 3

Implement Together adapter and tests.

Deliverable:

- Together key validation
- Together inventory discovery
- Together API test success path

### Step 4

Implement Cerebras adapter and tests.

Deliverable:

- Cerebras key validation
- Cerebras inventory discovery
- Cerebras API test success path

### Step 5

Verify Cloudflare API surface and decide thin-adapter vs dedicated-adapter path.

Deliverable:

- implementation note recorded in code/tests
- Cloudflare support added without degrading shared transport quality

### Step 6

Tune normalization/classification for all newly added providers.

Deliverable:

- better generated aliases
- more accurate `free`, `fast`, `general`, `reasoning`, `code` placement

## Out of Scope for This Phase

- per-provider billing dashboards
- provider-specific prompt transformations beyond adapter minimum
- custom multimodal UX for image/audio/video providers
- replacing current alias architecture

## Notes for Implementation

Do not start with Cloudflare-first.

Do not hardcode model names into routes as a substitute for inventory support.

Do not special-case provider behavior in the router when it can live inside the adapter.

Do not mark models as free unless the provider catalog or stable provider contract makes that reasonably trustworthy.
