# Provider Model Notes

## Purpose

This document records provider-specific observations that inform model discovery, filtering, classification, and generated alias design.

It is not the architecture source of truth. It is a working knowledge base for real provider inventories, naming patterns, known exclusions, and special routes.

This file should be updated when provider catalogs change or when new model families are observed in the field.

## Rules For This Document

- Record only provider-specific knowledge.
- Prefer practical routing notes over marketing descriptions.
- Separate discovered models from provider special routes.
- Mark uncertain assumptions explicitly.
- Do not treat this file as a static alias list.

## Gemini

### Current Inventory Characteristics

Gemini inventories are noisy and include many non-chat model families in the same catalog.

Observed categories in the current catalog:

- text/chat families:
  - `gemini-2.5-flash`
  - `gemini-2.5-pro`
  - `gemini-2.0-flash`
  - `gemini-2.0-flash-lite`
  - `gemini-3-pro-preview`
  - `gemini-3-flash-preview`
  - `gemini-3.1-pro-preview`
  - `gemini-3.1-flash-lite-preview`
  - `gemma-3-*it`
  - `gemma-3n-*it`
  - `gemma-4-*it`
- non-text or mixed-modality families:
  - `embedding`
  - `imagen`
  - `veo`
  - `lyria`
  - `tts`
  - `live`
  - `robotics`
  - `computer-use`
  - `deep-research`

### Initial Text-Safe Candidates

These should be considered likely initial text candidates for inventory filtering:

- `gemini-2.5-flash`
- `gemini-2.5-pro`
- `gemini-2.0-flash`
- `gemini-2.0-flash-001`
- `gemini-2.0-flash-lite`
- `gemini-2.0-flash-lite-001`
- `gemini-2.5-flash-lite`
- `gemini-3-flash-preview`
- `gemini-3-pro-preview`
- `gemini-3.1-flash-lite-preview`
- `gemini-3.1-pro-preview`
- `gemini-3.1-pro-preview-customtools`
- `gemma-3-1b-it`
- `gemma-3-4b-it`
- `gemma-3-12b-it`
- `gemma-3-27b-it`
- `gemma-3n-e2b-it`
- `gemma-3n-e4b-it`
- `gemma-4-26b-a4b-it`
- `gemma-4-31b-it`

### Initial Exclusions For Text Routing

These should be excluded from the first-stage text alias system:

- any model containing `embedding`
- any model containing `image`
- any model containing `audio`
- any model containing `tts`
- any model containing `generate`
- any model containing `veo`
- any model containing `imagen`
- any model containing `lyria`
- any model containing `robotics`
- any model containing `computer-use`
- any model containing `live`
- any model containing `research`
- `aqa`

### Initial Category Hints

- fast:
  - `gemini-2.5-flash`
  - `gemini-2.5-flash-lite`
  - `gemini-2.0-flash-lite`
  - `gemini-3.1-flash-lite-preview`
- general:
  - `gemini-2.0-flash`
  - `gemini-2.5-flash`
  - `gemini-3-flash-preview`
- reasoning:
  - `gemini-2.5-pro`
  - `gemini-3-pro-preview`
  - `gemini-3.1-pro-preview`
- code:
  - no strong dedicated code family is currently evident from Gemini naming alone

### Open Questions

- which Gemini text models reliably support the exact OpenAI-compatible chat payload shape we proxy
- whether `customtools` variants should be preferred only for tool-capable routing
- how free-tier eligibility should be detected without brittle guesses

## GitHub Models

### Current Status

Current inventory is unavailable because the provided token does not have the required `models` permission.

Observed error:

- `401 unauthorized`
- message indicates `The models permission is required to access this endpoint`

### Implication

GitHub should currently be excluded from generated inventory and alias generation until the token has correct scope.

### Future Expectations

Once permission is fixed, GitHub should likely provide:

- text model ids in `publisher/model` format
- a cleaner catalog than Gemini
- strong coding and reasoning candidates

### Open Questions

- whether GitHub exposes enough metadata for filtering or whether name-based classification will still be required
- whether GitHub offers a usable special-route concept analogous to OpenRouter

## OpenRouter

### Current Inventory Characteristics

OpenRouter inventories are large and include:

- real routed provider models in `provider/model` format
- explicit free variants with `:free`
- special provider routes such as `openrouter/free`
- meta-routes such as `openrouter/auto`
- non-text or utility routes

### Important Distinction

These are not the same class of entity:

- discovered ordinary models:
  - `openai/gpt-5.4-mini`
  - `google/gemini-2.5-flash`
  - `anthropic/claude-haiku-4.5`
- special routes:
  - `openrouter/free`
  - `openrouter/auto`
- likely non-standard routes:
  - `switchpoint/router`
  - `openrouter/bodybuilder`

### Initial Text-Safe Signals

Likely useful text candidates include families such as:

- `openai/*`
- `anthropic/*`
- `google/gemini-*`
- `google/gemma-*`
- `qwen/*`
- `mistralai/*`
- `deepseek/*`
- `x-ai/*`
- `moonshotai/*`
- `cohere/*`
- `amazon/nova-*`

This still requires filtering because OpenRouter also includes media, search, safeguards, and other special-purpose routes.

### Free Signals

Strong free hints:

- model ids ending with `:free`
- `openrouter/free` as a provider special route

These should not be treated as equivalent:

- `provider/model:free` is a discovered model variant
- `openrouter/free` is a provider-defined special route

### Initial Exclusions For Text Routing

For the first-stage text alias system, likely exclude names containing:

- `audio`
- `image`
- `search`
- `research`
- `router`
- `guard`
- `safeguard`
- `bodybuilder`

Some of these exclusions may need later refinement.

### Initial Category Hints

- free:
  - all discovered models with `:free`
  - optionally `openrouter/free` as special route support
- fast:
  - `nano`
  - `mini`
  - `lite`
  - `flash`
  - `haiku`
  - `small`
- reasoning:
  - `pro`
  - `opus`
  - `sonnet`
  - `thinking`
  - `o3`
  - `o4`
  - `gpt-5`
  - `deepseek-r1`
- code:
  - `codex`
  - `coder`
  - `codestral`
  - `devstral`
  - `mercury-coder`
  - `grok-code`

### Known Special Routes

- `openrouter/free`
- `openrouter/auto`

### Open Questions

- whether `openrouter/auto` should ever be included in generated global aliases
- whether special routes should be visible but disabled by default
- how aggressively to prefer `:free` models over stronger paid models in mixed aliases

## Provider-Agnostic Category Rules

These rules are tentative and should be implemented as heuristics plus overrides, not as rigid truth.

### Fast Hints

- `nano`
- `mini`
- `lite`
- `flash`
- `haiku`
- `small`

### Reasoning Hints

- `pro`
- `opus`
- `sonnet`
- `thinking`
- `reasoning`
- `o1`
- `o3`
- `o4`

### Code Hints

- `codex`
- `coder`
- `codestral`
- `devstral`
- `mercury-coder`
- `grok-code`

### Media Or Non-Text Exclusion Hints

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

## Immediate Usage In Implementation

The first implementation should use this file as a human-maintained reference for:

- provider normalization rules
- first-stage exclusion rules
- initial category heuristics
- special-route handling decisions

This file is not intended to be parsed by code in the first stage.
