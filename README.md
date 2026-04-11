# SimpleOpenRoad

SimpleOpenRoad is a self-hosted AI gateway that gives your team one stable OpenAI-style endpoint while routing traffic across multiple providers and keys.

Use it when you want your applications to keep working even if one model, one provider, or one API key starts failing.

## Why teams pick it

- One endpoint for all apps and agents.
- Automatic fallback between keys and providers.
- OpenAI-compatible API, so existing clients keep working.
- Centralized operations: health checks, stats, validation, and admin commands.
- Lightweight stack that runs well on a small VPS.

## What you get

- Unified endpoints for chat and responses.
- Provider adapters for Gemini, GitHub Models, and OpenRouter.
- Multi-key registry with runtime state and cooldown logic.
- Error-aware retry and failover policy.
- CLI and admin API for day-to-day operations.
- Terminal panel via `sor` or `sor panel`; web operations via `/docs` and admin API endpoints.

## Install

### Option A: one-line install from GitHub release (Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash
```

Install a specific version:

```bash
curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash -s -- --version v0.1.0
```

Installer selects release archive automatically by CPU architecture (`x86_64`/`arm64`).

### Option B: local source setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
cp config/config.example.yaml config/config.yaml
sor start --config-path config/config.yaml
```

## First request

The installer generates `MASTER_API_KEY` in `.env`. You can view it or run an automatic API test from the terminal panel with `sor` -> `Gateway` -> `API access token and test`.

For OpenAI-compatible plugins and clients, use:

```text
Base URL: http://<SERVER_IP>:12345/v1
API Key: <MASTER_API_KEY>
Model: auto/smart
```

Use `auto/smart` as the default model name in plugins. It uses a local low-cost heuristic to pick a fast, balanced, strong, or code-oriented candidate based on request size, output budget, and code/reasoning hints. Use `auto/fast` when you explicitly want lightweight models only. Other default aliases are `auto/balanced`, `auto/strong`, and `auto/code`.

You can also request a direct model. Use `provider/model` to force one provider, for example `openrouter/openai/gpt-5.4-mini`, or use an exact model id such as `gpt-5.4-mini` to try that same model id across your configured providers.

```bash
MASTER_API_KEY="$(grep '^MASTER_API_KEY=' .env | cut -d= -f2-)"

curl -sS -X POST "http://127.0.0.1:12345/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${MASTER_API_KEY}" \
  --data-binary @- <<'JSON'
{
    "model": "auto/fast",
    "messages": [{"role": "user", "content": "Hello"}]
}
JSON
```

To fully remove an installed server package:

```bash
sor uninstall --full
```

To update an installed server package while preserving `.env`, `config/config.yaml`, provider keys and `data/`:

```bash
sor update
```

`sor update` installs the latest GitHub Release. To test unreleased changes from the `main` branch:

```bash
sor update --ref main
```

For release updates, you can choose channel `stable` or `prerelease`:

```bash
sor update --channel prerelease
```

## Documentation

- docs/ADMIN_GUIDE.md
- docs/CONFIG_REFERENCE.md
- docs/TROUBLESHOOTING.md
- docs/ARCHITECTURE.md
- docs/RELEASE.md

## Release automation

When you publish a new release in GitHub, Actions automatically builds and attaches the Linux archive asset expected by install.sh.

