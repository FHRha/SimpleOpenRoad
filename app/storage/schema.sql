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
  avg_latency_ms REAL NOT NULL DEFAULT 0,
  UNIQUE(bucket_minute, provider, key_id)
);

CREATE TABLE IF NOT EXISTS route_model_memory (
  route_alias TEXT NOT NULL,
  profile TEXT NOT NULL,
  context_bucket TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  success_count INTEGER NOT NULL DEFAULT 0,
  avg_latency_ms REAL NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(route_alias, profile, context_bucket)
);

CREATE TABLE IF NOT EXISTS model_runtime_state (
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  quarantined_until TEXT,
  last_success_at TEXT,
  last_error_at TEXT,
  last_error_class TEXT,
  last_error_message TEXT,
  success_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  avg_latency_ms REAL NOT NULL DEFAULT 0,
  PRIMARY KEY(provider, model)
);

CREATE INDEX IF NOT EXISTS idx_health_key_time ON health_checks(key_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_attempts_request ON request_attempts(request_id);
CREATE INDEX IF NOT EXISTS idx_usage_bucket ON usage_stats(bucket_minute, provider, key_id);
CREATE INDEX IF NOT EXISTS idx_route_memory_alias ON route_model_memory(route_alias, profile, context_bucket);
CREATE INDEX IF NOT EXISTS idx_model_runtime_quarantine ON model_runtime_state(provider, model, quarantined_until);
