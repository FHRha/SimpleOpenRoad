# Getting Started

This guide gets SimpleOpenRoad from zero to a working OpenAI-compatible endpoint.

## 1. Install

### Linux Release Install

```bash
curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash
```

Open the terminal panel:

```bash
sor
```

### Local Source Install

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
cp config/config.example.yaml config/config.yaml
sor start --config-path config/config.yaml
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
Copy-Item config\config.example.yaml config\config.yaml
sor start --config-path config/config.yaml
```

## 2. Add a Provider Key

The easiest path is the interactive panel:

```bash
sor
```

Then:

```text
Providers and keys -> Add provider key
```

Direct CLI. Provider-specific key/token pages are listed in [Providers](PROVIDERS.md).

```bash
sor keys add --provider openrouter --key-id openrouter-main --secret <TOKEN>
```

Cloudflare Workers AI needs an account ID. Store it on the key when using multiple Cloudflare accounts:

```bash
sor keys add \
  --provider cloudflare \
  --key-id cloudflare-main \
  --secret <TOKEN> \
  --account-id <CLOUDFLARE_ACCOUNT_ID>
```

## 3. Validate Providers and Inventory

```bash
sor providers test
sor providers inventory --refresh
sor providers consistency
```

## 4. Run the Automatic API Test

```bash
sor
```

Then:

```text
Gateway -> API access token and test -> Test API request automatically
```

Start with:

```text
Model: auto/general
Mode: simple chat
```

For coding-agent clients, test:

```text
Mode: Cline-like
```

## 5. Configure an OpenAI-Compatible Client

```text
Base URL: http://<SERVER_IP>:12345/v1
API Key:  <MASTER_API_KEY>
Model:    auto/general
```

For Cline-like agents, Continue, curl, streaming checks, and direct model examples, see [Client Configuration](CLIENTS.md).

`MASTER_API_KEY` is in `.env` and can be shown or regenerated from:

```text
sor -> Gateway -> API access token and test
```

## 6. Send a Test Request

```bash
MASTER_API_KEY="$(grep '^MASTER_API_KEY=' .env | cut -d= -f2-)"

curl -sS -X POST "http://127.0.0.1:12345/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${MASTER_API_KEY}" \
  --data-binary @- <<'JSON'
{
  "model": "auto/general",
  "messages": [
    {"role": "user", "content": "Say hello in one sentence."}
  ]
}
JSON
```

## 7. Recommended First Checks

```bash
sor routes preview --model auto/general
sor keys list
sor stats
```

## 8. Common First Issues

No generated aliases:

- Add at least one real provider key.
- Run `sor providers inventory --refresh`.
- Check `sor providers consistency`.

Provider key invalid:

- Verify the provider endpoint.
- Check provider account quota/billing.
- For Cloudflare, confirm the account ID belongs to the token.

`auto/free` unavailable:

- No provider currently exposes a usable free text route in inventory.
- Use `auto/general` or configure an OpenRouter free-capable key.

Model repeatedly fails before a working one:

- Model quarantine will start skipping repeated failures after the configured threshold.
- See `Settings -> Model quarantine settings`.
