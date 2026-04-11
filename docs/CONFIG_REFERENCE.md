# Config Format Reference

## 1. `.env` Example

```env
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=12345
APP_LOG_LEVEL=INFO
APP_CONFIG_PATH=config/config.yaml
APP_DB_PATH=data/gateway.db

MASTER_API_KEY=change-me-user-api-key
ADMIN_API_KEY=change-me-admin-api-key
```

## 2. `config/config.yaml` Example

```yaml
server:
  host: 0.0.0.0
  port: 12345
  request_timeout_seconds: 60
  stream_timeout_seconds: 300

security:
  require_master_key: true
  require_admin_key: true
  mask_secrets_in_logs: true

routing:
  default_strategy: strict_priority
  retry:
    max_attempts_per_candidate: 2
    backoff_base_ms: 200
    backoff_max_ms: 2000
    jitter_ms: 100
  error_policy:
    auth_invalid: switch_key
    auth_forbidden: switch_key
    rate_limit: retry_then_switch_key
    provider_unavailable: retry_then_switch_provider
    network_timeout: retry_then_switch_key
    malformed_response: switch_provider
    unsupported_model: switch_provider

providers:
  gemini:
    enabled: true
    priority: 10
    endpoint: https://generativelanguage.googleapis.com
    timeout_seconds: 40
    keys: []

  github:
    enabled: true
    priority: 20
    endpoint: https://models.inference.ai.azure.com
    timeout_seconds: 45
    keys: []

  openrouter:
    enabled: true
    priority: 30
    endpoint: https://openrouter.ai/api/v1
    timeout_seconds: 45
    headers:
      HTTP-Referer: https://localhost
      X-Title: ai-gateway-router
    keys: []

routes:
  aliases:
    auto/fast:
      strategy: strict_priority
      candidates:
        - provider: gemini
          model: gemini-2.5-flash
        - provider: github
          model: gpt-4.1-mini
        - provider: openrouter
          model: google/gemini-2.5-flash-preview

    auto/fallback:
      strategy: strict_priority
      candidates:
        - provider: github
          model: gpt-4.1-mini
        - provider: openrouter
          model: openai/gpt-4o-mini

storage:
  sqlite_path: data/gateway.db

health:
  check_interval_seconds: 300
  startup_check: true
  check_timeout_seconds: 20

observability:
  json_logs: true
  request_log: true
  router_decision_log: true
  save_attempt_events: true
```

## 3. SQLite Schema (MVP)

```sql
CREATE TABLE IF NOT EXISTS key_runtime_state (
  key_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unknown',
  active INTEGER NOT NULL DEFAULT 1,
  consecutive_errors INTEGER NOT NULL DEFAULT 0,
  cooldown_until TEXT,
  last_check_at TEXT,
  last_success_at TEXT,
  last_error_at TEXT,
  last_error_code TEXT,
  last_error_message TEXT,
  success_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  switch_count INTEGER NOT NULL DEFAULT 0,
  avg_latency_ms REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS health_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  status TEXT NOT NULL,
  latency_ms REAL,
  models_json TEXT,
  error_code TEXT,
  error_message TEXT,
  checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS request_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL,
  route_alias TEXT,
  provider TEXT NOT NULL,
  key_id TEXT NOT NULL,
  model TEXT NOT NULL,
  attempt_index INTEGER NOT NULL,
  outcome TEXT NOT NULL,
  error_class TEXT,
  latency_ms REAL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_stats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bucket_minute TEXT NOT NULL,
  provider TEXT NOT NULL,
  key_id TEXT NOT NULL,
  requests_total INTEGER NOT NULL DEFAULT 0,
  success_total INTEGER NOT NULL DEFAULT 0,
  failure_total INTEGER NOT NULL DEFAULT 0,
  tokens_prompt INTEGER NOT NULL DEFAULT 0,
  tokens_completion INTEGER NOT NULL DEFAULT 0,
  estimated_cost_usd REAL NOT NULL DEFAULT 0,
  avg_latency_ms REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_health_key_time ON health_checks(key_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_attempts_request ON request_attempts(request_id);
CREATE INDEX IF NOT EXISTS idx_usage_bucket ON usage_stats(bucket_minute, provider, key_id);
```
