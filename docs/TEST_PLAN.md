# Test Plan

This page defines the practical verification surface for SimpleOpenRoad. For user-facing diagnostics, see [Troubleshooting](TROUBLESHOOTING.md). For release checks, see [Release Process](RELEASE.md).

## Fast Local Checks

Use these after focused code or docs changes:

```bash
python -m py_compile app/cli/app.py app/router/engine.py
pytest tests/unit/test_config_loader.py tests/unit/test_runtime_behaviors.py -q
```

For documentation-only changes:

```bash
python - <<'PY'
from app.config.loader import load_gateway_config
cfg = load_gateway_config('config/config.example.yaml')
print(','.join(cfg.providers.keys()))
PY
```

## Unit Test Areas

| Area | Coverage |
|---|---|
| Config loader | YAML validation, env expansion, duplicate key IDs, routing defaults, quarantine config. |
| Provider adapters | Payload transformation, auth headers, model listing, error normalization. |
| Inventory | Model normalization, capability classification, media/text filtering, generated aliases. |
| Router | Alias resolution, direct model routing, request analysis, context filtering, route memory, model quarantine. |
| Runtime behavior | Key cooldowns, failure counters, fallback ordering, route diagnostics. |
| Streaming | SSE normalization and provider stream translation. |
| CLI | Panel flows, config edits, key operations, provider validation output. |

Representative files:

- `tests/unit/test_config_loader.py`
- `tests/unit/test_inventory_aliases.py`
- `tests/unit/test_inventory_classifier.py`
- `tests/unit/test_runtime_behaviors.py`
- `tests/unit/test_openai_compatible_adapter.py`
- `tests/unit/test_cloudflare_workers_ai_adapter.py`
- `tests/unit/test_together_adapter.py`
- `tests/unit/test_cli_app.py`

## Integration Test Areas

| Area | Coverage |
|---|---|
| API gateway flow | `/v1/chat/completions`, auth, provider forwarding, normalized responses. |
| Health API | Public health endpoint behavior. |
| Failover | Mocked provider failures across keys/providers. |
| Streaming | Streaming response path through FastAPI. |

Representative files:

- `tests/integration/test_api_gateway_flow.py`
- `tests/integration/test_api_health.py`

## Provider-Specific Scenarios

These are best verified with mocks first, then with manual provider tests when credentials are available.

| Provider | Important Cases |
|---|---|
| Gemini | Native payload translation, noisy model catalog filtering, non-text model exclusion. |
| GitHub Models | Token permission failures, OpenAI-compatible chat path, catalog handling. |
| Groq | OpenAI-compatible chat and streaming. |
| Cloudflare Workers AI | Per-key `account_id`, `@cf/...` model names, UUID catalog filtering, text task filtering. |
| OpenRouter | `:free` models, `openrouter/free`, free-only behavior, paid fallback rules. |
| Together AI | Top-level model arrays, media model filtering, paid/credit failures, model quarantine. |
| Cerebras | OpenAI-compatible chat path and error mapping. |

## Manual Smoke Tests

Use the terminal panel:

```bash
sor
```

Recommended manual checks:

- Add or validate at least one provider key.
- Refresh inventory.
- Run automatic API test for `auto/fast`.
- Run automatic API test for `auto/general`.
- Preview route diagnostics for `auto/free-cheap` when free-capable providers are configured.
- Confirm quarantined models are skipped after repeated failures.

Equivalent CLI commands:

```bash
sor config validate
sor providers test
sor providers inventory --refresh
sor routes preview --model auto/general
```

## Release Verification

Before publishing a release:

```bash
pytest -q
python -m build
```

Also verify:

- `README.md` quick start matches the installer behavior.
- `config/config.example.yaml` loads successfully.
- `sor update` instructions in [Release Process](RELEASE.md) and [Admin Guide](ADMIN_GUIDE.md) are aligned.
- Linux release archive names match the installer convention.

## Known External Risks

- Provider catalogs change without notice.
- Provider billing state can make a technically valid key fail at runtime.
- Free-tier routes can disappear or become rate-limited.
- Some providers expose media, embedding, moderation, or task-specific models in the same catalog as chat models.
