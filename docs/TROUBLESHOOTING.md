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

## Route switching is not happening as expected
- Verify `routing.error_policy` in config.
- Check key runtime status (`sor keys list`) for cooldown/blocking.
- Confirm effective candidate order with `sor routes preview`.
- Check `Route memory` in Route Preview. A `hit` only reorders candidates; fallback still continues if that model fails.
- `ignored_direct` means the request used a direct model instead of an alias, so route memory is intentionally not used.
- If old placeholder keys appear, run `sor keys list --all` and clean them from the panel with `sor` -> option `9`.

## No route candidates available
- At least one provider must be `enabled: true`.
- At least one key must be active and not in cooldown.
- Verify route aliases point to existing providers/models.
- Placeholder values like `${GEMINI_API_KEY_MAIN}` are ignored by routing; add real provider keys with `sor keys wizard`.
- Run `sor routes preview` for the same alias/model and inspect:
- `Request Route Analysis`: detected intent, profile, token estimate, and reasons.
- `Effective Candidate Order`: final order after adaptive routing, context filtering, and route memory.
- `Candidate preview`: full non-truncated status/reason for each candidate.

## Candidate skipped with `context_too_large`
- The model has a known context limit from provider inventory and the request estimate is larger.
- Route Preview shows the comparison as `token_estimate > max_context_tokens`.
- Use an alias with larger-context models, reduce prompt/history size, or refresh inventory if provider metadata changed.
- Unknown context limits are not filtered; SOR only skips when a limit is known.

## Unexpected weak or strong model selection
- Check `Request Route Analysis` first. Short prompts can still be classified as planning, analysis, code, or critical.
- `auto/reasoning` can use fast/general models only for trivial smoke-test prompts.
- `auto/free` stays inside free/special free routes and does not silently upgrade to paid candidates.
- Direct model requests bypass adaptive bucket switching. Use `provider/model` when you need an exact model.

## Route memory looks wrong
- `miss`: no remembered model for the current alias/profile/context bucket.
- `hit`: remembered model is still valid and was moved to the front.
- `stale`: remembered model is no longer in the current candidate list and is ignored.
- `ignored_direct`: direct model request; memory is not used.
- Route memory is keyed by `alias + profile + context_bucket`, so a model remembered for a small fast request is not reused for a large reasoning request.

## Config reload fails
- Run `sor config validate` first.
- Check YAML syntax and duplicate key IDs.
- Ensure env variables referenced as `${VAR}` are set.

## High latency
- Reduce provider timeout values.
- Tune retry settings (`backoff_base_ms`, `max_attempts_per_candidate`).
- Reorder alias candidates to favor low-latency models.
