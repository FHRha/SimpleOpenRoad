# Test Plan

## Unit Tests
- Config loader and validation:
  - valid/invalid YAML
  - duplicate key IDs
  - env var expansion
- Router internals:
  - alias resolution
  - selection strategy ordering
  - error classification and policy actions
- Key registry:
  - cooldown eligibility
  - success/failure state transitions

## Integration Tests
- API endpoint behavior with mocked adapters:
  - `/v1/chat/completions`
  - `/v1/responses`
  - streaming path
- Failover scenarios:
  - 401 invalid key -> switch key/provider
  - 429 rate limit -> retry then switch
  - 5xx -> retry then provider fallback
- Admin endpoints and auth checks.

## CLI Tests
- command parsing and outputs
- config edits for keys/routes
- doctor/config validate flow

## Provider Adapter Mock Tests
- payload transformation correctness
- response normalization
- error mapping
