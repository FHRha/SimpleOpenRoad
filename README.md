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

## Documentation

- docs/ADMIN_GUIDE.md
- docs/CONFIG_REFERENCE.md
- docs/TROUBLESHOOTING.md
- docs/ARCHITECTURE.md
- docs/RELEASE.md

## Release automation

When you publish a new release in GitHub, Actions automatically builds and attaches the Linux archive asset expected by install.sh.

