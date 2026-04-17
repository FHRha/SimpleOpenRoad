# Deployment

This guide covers running SimpleOpenRoad as a small self-hosted gateway on a Linux server.

For first-time setup, start with [Getting Started](GETTING_STARTED.md). For update/release details, see [Release Process](RELEASE.md).

## Recommended Production Shape

```text
Client / IDE / agent
  -> HTTPS reverse proxy
  -> SimpleOpenRoad on 127.0.0.1:12345
  -> provider APIs
```

Recommended boundaries:

- Bind SimpleOpenRoad to localhost when it sits behind Nginx, Caddy, or another reverse proxy.
- Expose only the user API publicly if needed.
- Restrict admin endpoints by network ACL, VPN, or firewall.
- Store provider keys only in `config/config.yaml`, not in client tools.
- Give clients only `MASTER_API_KEY`.

## Install From Release

```bash
curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash
```

Open the panel:

```bash
sor
```

Then configure:

```text
Providers and keys -> Add provider key
Gateway -> API access token and test
Service -> Install service
```

## Run As a Service

System service example:

```bash
sudo sor service install --mode system --config-path /opt/simple-open-road/config/config.yaml
sudo sor service status --mode system
sudo sor service logs --mode system --lines 200
```

User service example:

```bash
sor service install --mode user --config-path ~/.local/share/simple-open-road/config/config.yaml
sor service status --mode user
sor service logs --mode user --lines 200
```

Useful service commands:

```bash
sor service start --mode system
sor service stop --mode system
sor service restart --mode system
sor service status --mode system
```

Use `--mode user` instead of `--mode system` for user services.

## Reverse Proxy Notes

SimpleOpenRoad itself can serve HTTP directly. For public access, put it behind a TLS reverse proxy.

Forward:

```text
https://your-domain.example/v1/... -> http://127.0.0.1:12345/v1/...
```

Client settings:

```text
Base URL: https://your-domain.example/v1
API Key:  <MASTER_API_KEY>
Model:    auto/general
```

If you expose admin endpoints, protect them separately. A safer default is to keep admin access local and use SSH for operations.

## Backups

Back up:

```text
.env
config/config.yaml
data/
```

Why:

- `.env` contains gateway access tokens.
- `config/config.yaml` contains provider configuration and provider keys.
- `data/` contains SQLite runtime state, health history, stats, route memory, and model quarantine state.

Do not publish these files.

## Updates

Update to the latest stable release:

```bash
sor update
```

Update to a prerelease:

```bash
sor update --channel prerelease
```

Install a specific version:

```bash
sor update --version v0.3.0
```

Test unreleased `main`:

```bash
sor update --ref main
```

Updates preserve:

- `.env`
- `config/config.yaml`
- provider keys in config
- `data/`

## Health Checks After Deploy

```bash
sor config validate
sor providers test
sor providers inventory --refresh
sor providers consistency
sor routes preview --model auto/general
```

Then run an end-to-end request:

```text
sor -> Gateway -> API access token and test -> Test API request automatically
```

## Uninstall

Remove only the service:

```bash
sor service uninstall --mode system
```

Full package uninstall:

```bash
sor uninstall --full
```

Before full uninstall, back up `.env`, `config/config.yaml`, and `data/` if you may need them later.
