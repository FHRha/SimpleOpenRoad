# Troubleshooting

Use the terminal panel first when possible:

```bash
sor
```

Most routing issues can be narrowed down with these commands. For the routing model behind these diagnostics, see [Routing and Model Selection](ROUTING.md).

```bash
sor providers test
sor providers inventory --refresh
sor providers consistency
sor routes preview --model auto/general
```

## User endpoints return 401

- Check `MASTER_API_KEY` in `.env`.
- Pass `x-api-key: <MASTER_API_KEY>` or `Authorization: Bearer <MASTER_API_KEY>`.
- Confirm `security.require_master_key`.

## Admin endpoints return 401

- Check `ADMIN_API_KEY` in `.env`.
- Pass `x-admin-key: <ADMIN_API_KEY>` or `Authorization: Bearer <ADMIN_API_KEY>`.
- Confirm `security.require_admin_key`.

## Provider key is invalid

- Run `sor keys validate --provider <name> --key-id <id>`.
- Check the provider endpoint URL.
- Check provider quota, billing, and account restrictions.
- For Cloudflare Workers AI, check the key-level or provider-level `account_id`.

## Cloudflare returns auth errors or HTTP 400

- Cloudflare Workers AI URLs require the correct account ID.
- Prefer key-level `account_id` when using multiple Cloudflare accounts.
- Run `sor providers inventory --refresh`.
- Confirm discovered model IDs look like `@cf/...`, not UUIDs.
- Run `sor providers consistency` to compare key health and inventory state.

## Together returns HTTP 402

Together `402` usually means billing, credits, or model access is unavailable for that account.

What to do:

- Use `auto/general` or `auto/fast` and let model quarantine skip repeatedly failing models.
- If specific families always fail, add a model quarantine override such as `provider: together`, `model_pattern: "nvidia/*"`.
- Check whether the account has credits for the selected model.

`auto/free-cheap` is only generated when a provider has real free candidates. Paid-only Together models should not create that alias.

## Route switching is not happening as expected

- Check `routing.error_policy`.
- Check key runtime status with `sor keys list`.
- Confirm effective candidate order with `sor routes preview`.
- Check `Route memory`: a `hit` only reorders candidates; fallback still continues if that model fails.
- Check for `model_quarantined`: quarantined models are skipped before provider calls.

## No route candidates available

- At least one provider must be `enabled: true`.
- At least one real key must be configured and active.
- Placeholder values like `${GEMINI_API_KEY_MAIN}` are ignored.
- Refresh inventory: `sor providers inventory --refresh`.
- Preview the route: `sor routes preview --model <alias>`.

## Candidate skipped with `context_too_large`

- The request estimate is larger than the model's known context limit.
- Use a larger-context alias/model.
- Reduce prompt/history size.
- Refresh inventory if provider metadata changed.

## Candidate skipped with `model_quarantined`

The same `provider/model` failed repeatedly and is temporarily skipped.

Defaults:

- Threshold: 3 consecutive failures.
- `rate_limit`: 30 minutes.
- `unsupported_model`: 24 hours.
- `malformed_response`: 6 hours.

Change or reset from:

```text
sor -> Settings -> Model quarantine settings
```

## Unexpected weak or strong model selection

- Check `Request Route Analysis` in route preview or automatic test output.
- Short prompts usually route to `fast`.
- `auto/reasoning` can still use fast/general models for trivial smoke-test prompts.
- Direct `provider/model` requests bypass adaptive bucket switching.

## Route memory looks wrong

Statuses:

- `miss`: no remembered model for this alias/profile/context bucket.
- `hit`: remembered model is valid and moved forward.
- `stale`: remembered model is no longer in the candidate list.
- `ignored_direct`: direct model request; route memory does not apply.

Route memory is keyed by:

```text
alias + profile + context_bucket
```

## Config reload fails

- Run `sor config validate`.
- Check YAML indentation.
- Check duplicate key IDs.
- Ensure env variables referenced as `${VAR}` are set.

## High latency

- Reduce provider timeout values.
- Tune retry settings.
- Lower `routing.retry.max_attempts_per_candidate`.
- Let model quarantine skip repeated failures.
- Prefer `auto/fast` for simple prompts.
