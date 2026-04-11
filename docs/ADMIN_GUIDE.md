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
- `2` prints the `MASTER_API_KEY` and a ready-to-run curl example.
- `9` removes old unconfigured placeholder keys from `config.yaml`.
- `10` updates SimpleOpenRoad while preserving `.env`, `config/config.yaml`, provider keys and `data/`.
- `18` performs a full package uninstall.

The panel is grouped by area:
- Gateway: setup summary, API token, doctor, stats.
- Providers and keys: providers, key wizard, key list, validation, placeholder cleanup.
- Service: update, install/start/stop/restart/status/logs.
- Maintenance: service-only uninstall and full package uninstall.

Update package while preserving user settings:
```bash
sor update
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
