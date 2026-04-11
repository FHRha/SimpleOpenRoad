# Admin Guide

## 1. Initialize
```bash
sor init --config-path config/config.yaml
```

## 2. Validate Setup
```bash
sor doctor --config-path config/config.yaml
sor config validate --config-path config/config.yaml
```

## 3. Provider and Key Operations

List providers:
```bash
sor providers list
```

Test providers/keys:
```bash
sor providers test
```

List keys:
```bash
sor keys list
```

Show placeholder/unconfigured keys too:
```bash
sor keys list --all
```

Add key:
```bash
sor keys add --provider github --key-id github-backup --secret <TOKEN>
```

`key-id` is a local identifier for logs, stats, health checks and remove/enable/disable commands. It is not sent to the provider. Use names like `openrouter-main`, `gemini-backup-1`, or `github-work`.

Remove key:
```bash
sor keys remove --key-id github-backup
```

Disable / enable key runtime state:
```bash
sor keys disable --key-id github-main
sor keys enable --key-id github-main
```

Validate all keys:
```bash
sor keys validate
```

Validate one key:
```bash
sor keys validate --provider github --key-id github-main
```

## 4. Routing Operations
List aliases:
```bash
sor routes list
```

Adjust candidate priority in alias chain:
```bash
sor routes set-priority --alias auto/fast --candidate github/gpt-4.1-mini --position 1
```

## 5. Runtime Operations
Reload config:
```bash
sor config reload
```

Check runtime stats:
```bash
sor stats
```

Run health check batch:
```bash
sor health
```

Run in background as service (Linux + systemd):
```bash
sudo sor service install --mode system --config-path /opt/simple-open-road/config/config.yaml
sudo sor service status --mode system
sudo sor service logs --mode system --lines 200
```

Terminal panel:
```bash
sor
```

Explicit panel command:
```bash
sor panel --config-path config/config.yaml
```

In the terminal panel:
- `0` exits the panel.
- Choose a section first, then use `0` inside a section to go back.
- Gateway -> API access token and test shows `MASTER_API_KEY`, can regenerate it, and can run an automatic local test request.
- Providers and keys -> Remove provider key deletes a configured provider key from `config.yaml`.
- Providers and keys -> Clean unconfigured placeholder keys removes old placeholder keys from `config.yaml`.
- Service -> Update SimpleOpenRoad preserves `.env`, `config/config.yaml`, provider keys and `data/`.
- Maintenance -> Full uninstall package removes the installed package.

The panel is grouped by area:
- Gateway: setup summary, API token/test, doctor, stats.
- Providers and keys: providers, key wizard, key list, validation, key removal, placeholder cleanup.
- Service: update, install/start/stop/restart/status/logs.
- Maintenance: service-only uninstall and full package uninstall.

Update package while preserving user settings:
```bash
sor update
```

Choose release channel:
```bash
sor update --channel stable
sor update --channel prerelease
```

Test unreleased changes from the main branch:
```bash
sor update --ref main
```

Update to a specific release:
```bash
sor update --version v0.1.1
```

Full package uninstall:
```bash
sor uninstall --full
```

## 6. Admin API
User API header:
- `x-api-key: <MASTER_API_KEY>`
- `Authorization: Bearer <MASTER_API_KEY>`

OpenAI-compatible plugin settings:
- Base URL: `http://<SERVER_IP>:12345/v1`
- Default model: `auto/smart`
- Other default aliases: `auto/fast`, `auto/balanced`, `auto/strong`, `auto/code`
- `auto/smart` uses a local heuristic, not an extra LLM request, to pick a candidate by request size, output budget, and code/reasoning hints.
- Direct model format: `provider/model` or an exact model id such as `gpt-5.4-mini`

Admin header:
- `x-admin-key: <ADMIN_API_KEY>`

Validate key endpoint:
```http
POST /admin/validate-key
```

Reload config endpoint:
```http
POST /admin/reload-config
```

## 7. Production Recommendations
- Run behind reverse proxy (Nginx/Caddy).
- Restrict admin endpoints by network ACL.
- Rotate provider keys regularly.
- Keep `data/gateway.db` in backup scope.
