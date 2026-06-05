# Review: W14 production readiness and ops hardening

Date: 2026-06-05
Reviewed commits:

```text
afb96f9 feat(W14.1+W14.3): CI gates, make ci, repo hygiene, profile validation/dry-run API
5e57560 feat(W14.2+W14.3+W14.5): API token auth, profile validation/dry-run, runbooks
80eacbf feat(W14.4+W14.6): trace artifact listing, readability fine (all files <250 lines)
```

Spec: `source/codex/tz-w14-production-readiness-and-ops-hardening.md`

## Verdict

Partially accepted, not fully done yet.

W14 added useful infrastructure and most sub-sections are materially implemented:

- CI workflow exists.
- `make ci` exists.
- repo hygiene script exists.
- token auth middleware exists.
- agent profile list/get/validate/dry-run endpoints exist.
- runbooks exist.
- trace now includes artifact listing from evidence path.

However, W14 should not be considered fully accepted yet. There are several gaps against the written W14 spec, especially around API auth policy, trace observability completeness, profile validation rigor, and evidence for CI actually running.

---

## Accepted / mostly accepted

### W14.1 — CI gates and hygiene

Mostly accepted.

Implemented:

```text
.github/workflows/ci.yml
make ci
scripts/ci_repo_hygiene.py
```

CI jobs include tests, GraceLint, docs-check, and repo hygiene. Repo hygiene checks tracked `agents/`, legacy CLI entrypoints, and `src/prefect_grace` package return.

Limitations:

- Connector returned no GitHub workflow runs for the latest W14 commit during this review, so CI success could not be independently verified from GitHub Actions.
- Repo hygiene currently covers the main old-problem cases but does not visibly cover all W14 spec checks, such as completed-wave allowlist expiry.

Required follow-up:

- Provide or wait for GitHub Actions evidence, or include local `make ci` output in the implementation evidence.
- Extend `ci_repo_hygiene.py` to check allowlist expiry for completed waves W0-W13 if not already covered elsewhere.

### W14.2 — API token auth

Partially accepted.

Implemented:

```text
src/grace_control/api/auth.py
AuthMiddleware
GRACE_API_AUTH_ENABLED
GRACE_API_TOKEN
GRACE_API_ALLOW_UNAUTHENTICATED_LOCALHOST
Bearer token
X-GRACE-API-Token
401 structured response
```

Tests cover default auth-off behavior, missing/wrong token, correct Bearer token, health public, and X-GRACE token.

Issues:

1. `/openapi.json` is always public in `_PUBLIC_PATHS`, even when `auth_enabled=true`. W14 spec recommended protecting OpenAPI when auth is enabled unless explicitly allowed.
2. `auth_app` test fixture mutates global `settings` object and does not visibly restore values. This can leak across tests, even if currently passing.
3. The middleware uses `allow_localhost=True` default bypass. This is fine for local dev, but docs/tests should clearly show remote hardening config with `allow_unauthenticated_localhost=false`.

Required follow-up:

- Add a setting for `api_auth_public_openapi` or remove `/openapi.json` from public paths when auth is enabled.
- Add tests for `/openapi.json` behavior under auth enabled.
- Avoid global settings mutation in tests, or restore via monkeypatch/new settings object.

### W14.3 — Agent profile validation and dry-run

Partially accepted.

Implemented endpoints:

```text
GET  /api/agents/profiles
GET  /api/agents/profiles/{executor_id}
POST /api/agents/profiles/{executor_id}/validate
POST /api/agents/profiles/{executor_id}/dry-run
```

Implemented validator:

```text
AgentProfileValidator
command shape validation
timeout validation
input mode validation
optional executable check
command rendering
cwd rendering
env preview
```

Issues:

1. `list_profiles()` returns key `data`, while W14 spec expected a clearer `profiles` envelope. This is not fatal, but it is an API contract mismatch.
2. Missing env vars are not clearly treated as errors. `AgentEnvBuilder` expands env, but the validator does not visibly distinguish required vs optional env references.
3. `check_executable=true` appends a warning, not an error. That may be acceptable, but the spec said validation should fail bad profile config before runtime. If executable existence is optional, this should be documented explicitly.
4. Dry-run validates/renders but does not provide explicit `would_execute=false` top-level route contract matching the spec envelope. It is present inside returned validator data, but the API envelope is `data`.

Required follow-up:

- Decide/standardize response envelope: `profiles` vs `data`.
- Add tests for missing required env var behavior.
- Document executable check as warning or make it an error when `check_executable=true`.

### W14.4 — Trace observability

Partially accepted.

Implemented:

- `TraceService._run_to_dict()` now includes `artifacts` listing when `evidence_path` exists.

Issue:

W14.4 spec required more than artifact names. It required operator-visible execution metadata:

```text
executor_id
backend
model
effort
exit_code
domain_status
stdout/stderr/command artifact names
```

The latest W14.4 commit only adds:

```python
if r.evidence_path:
    d["artifacts"] = [str(f.relative_to(ep)) for f in ep.iterdir() if f.is_file()]
```

That is useful, but not enough to satisfy W14.4. If `result_json` already contains some fields and `_run_to_dict(with_result=True)` exposes them elsewhere, that should be made explicit and tested. Otherwise W14.4 remains partial.

Required follow-up:

- Ensure trace run dict includes executor/model/effort/backend/exit_code/domain_status where available.
- Add tests proving trace response includes those fields for a CLI run.
- Dashboard should show at least executor/model/status/artifact links or document that UI part is deferred.

### W14.5 — Runbooks

Mostly accepted.

Added runbooks:

```text
RUNBOOK_LOCAL_DEV.md
RUNBOOK_SERVER_DEPLOY.md
RUNBOOK_DEBUG_PACKET.md
```

Issue:

The W14 spec also asked for:

```text
RUNBOOK_AGENT_PROFILES.md
RUNBOOK_SELF_EVOLUTION.md
```

If those are not present, W14.5 is incomplete against the spec.

Required follow-up:

- Add missing runbooks or update W14 spec/review to explicitly defer them.
- Ensure README links all W14 runbooks.

### W14.6 — Readability

Not enough evidence for full acceptance.

The claim “all files <250 lines” may be true, but the observed W14.6 commit only changes trace artifact listing. It does not demonstrate the specified readability helper extraction for:

```text
packet_executor.py
evidence_service.py
agent_run_service.py
```

If file sizes are now under 250 and GRC108 allowlist is gone/reduced, that is good, but it should be evidenced.

Required follow-up:

- Provide file-size evidence or add a repo hygiene/GraceLint rule for file-size target.
- Remove GRC108 allowlist entries where practical, or document why they remain.

---

# Blockers before W14 final acceptance

## P1-1. OpenAPI auth policy mismatch

`/openapi.json` is public even when auth is enabled. W14 spec recommended protecting OpenAPI when auth is enabled unless explicitly allowed.

Fix:

```text
api_auth_public_openapi: bool = false
```

or remove `/openapi.json` from `_PUBLIC_PATHS` when auth is enabled.

Tests:

```text
auth enabled + missing token + /openapi.json => 401 unless public_openapi=true
auth enabled + token + /openapi.json => 200
```

## P1-2. Trace observability lacks required executor metadata

Artifacts listing alone is not enough for W14.4.

Fix:

Trace run dict should include, where available:

```text
executor_id
backend
model
effort
exit_code
domain_status
stdout_artifact
stderr_artifact
command_artifact
```

Tests should prove these appear for CLI runs.

## P1-3. Missing runbooks from W14.5

Add or explicitly defer:

```text
docs/grace/RUNBOOK_AGENT_PROFILES.md
docs/grace/RUNBOOK_SELF_EVOLUTION.md
```

## P1-4. CI success not independently verified

Connector found no workflow runs for reviewed W14 commit. This may be a connector limitation or workflow trigger issue, but W14 final acceptance should include evidence:

```text
GitHub Actions green
or local make ci output attached in evidence summary
```

---

# P2 improvements

## P2-1. Auth tests mutate global settings

Tests should avoid leaking mutation of imported singleton settings. Prefer a fresh `GraceSettings` object or restore fields with monkeypatch/finalizer.

## P2-2. Profile API envelope mismatch

Spec expected `profiles`, implementation returns `data`. Either is fine if documented, but choose one and regenerate OpenAPI/docs.

## P2-3. AgentProfileValidator env validation is shallow

Validator should differentiate:

```text
missing required env
optional env
redacted env preview
```

---

## Required next patch

Title:

```text
fix(W14): close auth, trace metadata, runbook, and CI evidence gaps
```

Scope:

```text
src/grace_control/api/auth.py
src/grace_control/config/settings.py
src/grace_control/services/trace_service.py
src/grace_control/services/agent_profile_validator.py
src/grace_control/api/routers/agents.py
docs/grace/RUNBOOK_AGENT_PROFILES.md
docs/grace/RUNBOOK_SELF_EVOLUTION.md
docs/grace/API_SECURITY.md
docs/grace/TRACE_AND_OBSERVABILITY.md
tests/grace_control/api/test_auth.py
tests/grace_control/api/test_trace_api.py
tests/grace_control/agent/test_agent_profile_validator.py
```

Acceptance:

1. Auth-enabled `/openapi.json` behavior is explicit and tested.
2. Trace API exposes executor/model/effort/backend/status/artifact fields for CLI runs.
3. Missing W14 runbooks are added or explicitly deferred with reason.
4. CI status is available from GitHub Actions or local `make ci` evidence is attached.
5. Profile validation env behavior is documented/tested.
6. Test suite remains green.

---

## Status

```text
W14.1: mostly accepted, pending CI evidence / expiry hygiene check
W14.2: partial, auth policy gap
W14.3: partial, env validation/API envelope gaps
W14.4: partial, artifact listing only
W14.5: partial, missing runbooks
W14.6: needs evidence

Overall W14: not yet final accepted
```
