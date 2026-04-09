# Troubleshooting

## Server returns 401 for user endpoints
- Check `MASTER_API_KEY` in `.env`.
- Pass `x-api-key` header or `Authorization: Bearer ...`.
- Confirm `security.require_master_key` in `config/config.yaml`.

## Server returns 401 for admin endpoints
- Check `ADMIN_API_KEY` in `.env`.
- Pass `x-admin-key` header or bearer token.

## Provider key is always invalid
- Run `sor keys validate --provider <name> --key-id <id>`.
- Check endpoint URL for provider config.
- Check quota and account restrictions.

## Fallback is not happening as expected
- Verify `routing.error_policy` in config.
- Check key runtime status (`sor keys list`) for cooldown/blocking.
- Confirm alias candidate order with `sor routes list`.

## No route candidates available
- At least one provider must be `enabled: true`.
- At least one key must be active and not in cooldown.
- Verify route aliases point to existing providers/models.

## Config reload fails
- Run `sor config validate` first.
- Check YAML syntax and duplicate key IDs.
- Ensure env variables referenced as `${VAR}` are set.

## High latency
- Reduce provider timeout values.
- Tune retry settings (`backoff_base_ms`, `max_attempts_per_candidate`).
- Reorder alias candidates to favor low-latency models.
