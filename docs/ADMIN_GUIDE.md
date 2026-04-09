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
sor panel --config-path config/config.yaml
```

## 6. Admin API
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
