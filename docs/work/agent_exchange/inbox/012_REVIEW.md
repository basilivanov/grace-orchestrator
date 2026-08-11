# Review 012 — Admin Control Center Stage 06

Status: CHANGES REQUIRED

Implementation commit reviewed: `af2e5a6146a8ff46fa9e45368c0607905890a11d`.

The Stage 06 implementation has the right overall shape: mutations are project-local API/domain operations, read/control authorization is server-side, strong confirmation exists, timeout is normalized to unknown outcome without automatic retry, packet retry/cancel/merge reuse existing domain/state/fencing paths, supervisor failures stay failures, OpenAPI mutation mode is gated, and browser/audit DTOs are recursively masked.

Four acceptance blockers remain.

## Required fixes

### 1. Maintenance ownership safety is fail-open for malformed/uncertain lease evidence

`AdminMaintenanceControlService.safe_cleanup_packet_states()` currently returns the original `packet_states` when a lease row is malformed or lacks `packet_id`:

```python
if not isinstance(row, dict):
    return dict(packet_states)
...
if packet_id is None:
    return dict(packet_states)
```

That is not fail-closed. `MaintenanceService` marks a worktree stale whenever its packet state remains terminal-like (`FAILED`, `BLOCKED_FINAL`, etc.). Therefore returning the original terminal states leaves those worktrees eligible for real deletion even though ownership evidence is uncertain.

The new test currently codifies the unsafe behavior:

```python
malformed = {"ordinary": [{"packet_id": None}], ...}
assert service.safe_cleanup_packet_states(states, malformed) == states
```

Required:

- uncertain/malformed ownership must protect resources, never preserve them as cleanup candidates;
- when an uncertain row cannot be attributed safely, fail closed for all affected cleanup candidates (protect all if attribution is impossible);
- DB/lease read failure must likewise make destructive cleanup unavailable or produce an empty safe-candidate set, not infer that there are no live leases;
- add a deterministic real-cleanup acceptance test (`dry_run=False` or equivalent service-level deletion proof) showing a terminal-looking worktree is **not deleted** when lease/ownership evidence is malformed, missing, or unavailable;
- keep normal stale terminal worktree cleanup working when ownership evidence is complete and safe.

### 2. Mutation routing does not enforce registry ↔ runtime identity before changing state

The accepted read path already treats registry/runtime `project_key` or root mismatch as `identity_mismatch`. The Stage 06 mutation path bypasses that protection.

`AdminMutationService._call_project()` resolves the registry context and immediately sends the mutation to that context's configured client. It does not first prove that the contacted runtime identifies as the selected project.

This creates a dangerous misconfiguration case:

```text
registry key alpha -> accidentally points to beta API
POST /api/admin-hub/projects/alpha/controls
=> beta can be mutated
```

The project-local endpoint makes this worse for audit attribution: `_local_identity(body)` trusts the supplied `body.project_key` as the audit label instead of checking the runtime's actual identity. A misbound beta runtime can therefore mutate beta while recording `project_key=alpha`.

Required:

- before any Hub-proxied mutation, verify the selected runtime identity using the accepted registry/runtime identity contract; identity mismatch must produce zero mutation calls;
- project-local control endpoints must verify the supplied project identity against the actual local runtime identity (or derive canonical project identity locally rather than trusting the Hub body);
- a direct authorized local caller must not be able to forge another project's audit `project_key`;
- add a deterministic two-project regression where registry `alpha` is wired to a runtime identifying as `beta`: mutation must be rejected before domain mutation, and no audit may falsely attribute beta state changes to alpha;
- preserve the existing normal selected-project isolation behavior.

### 3. Canonical project-local audit is allowed to fail silently while mutation proceeds

`_record_admin_event()` currently does:

```python
try:
    record_event(...)
except Exception:
    return None
```

Its contract even states that audit failure never blocks the domain action. That conflicts with Stage 06's requirement that **every operator mutation produce project-local canonical audit evidence**.

At minimum, if `admin_action_requested` cannot be persisted, the mutation must not proceed unaudited. If the domain action has already happened and the completed/failed audit write then fails, the API must not return an ordinary fully-audited success; it must surface an explicit audit-integrity failure/attention state (or use an already-existing durable fallback if the repository has one).

Required:

- fail closed before mutation when the requested audit record cannot be persisted;
- never silently swallow requested/completed/failed audit persistence failure;
- make post-action audit failure visible and non-ordinary-success, since the mutation outcome may already have changed state;
- keep audit payloads secret-safe;
- add deterministic tests that force `record_event()` failure before dispatch and prove the domain action is not called, plus a post-action audit failure test proving it is surfaced rather than reported as a normal success.

### 4. OpenAPI mutation loses declared path-parameter values before local dispatch

The Control Center correctly calls `_openapi_request()` and materializes a discovered path, but the mutation branch then calls:

```python
AdminMutationService(...).execute_openapi(
    path=selected_path,
    parameters={**query_params},
    ...
)
```

`query_params` contains only query parameters; declared path values were consumed while materializing `request_path` and are no longer present.

The project-local `_materialize_openapi_request()` expects the original placeholder values in `parameters`. Therefore a discovered mutation such as:

```text
POST /api/items/{item_id}?mode=...
```

cannot execute through the Stage 06 UI/proxy: `item_id` is lost and local materialization fails with a missing path parameter.

The current acceptance test only uses `/api/synthetic-mutation` with no path parameters, so it does not cover this.

Required:

- preserve declared OpenAPI path and query parameter values across the Hub mutation boundary without allowing undeclared selectors;
- safely materialize the exact discovered path and query values exactly once, retaining the Stage 05 same-origin/path protections;
- add an acceptance fixture with a discovered non-GET operation such as `/api/items/{item_id}` plus at least one query parameter;
- prove the authorized + control-mode + confirmed request reaches exactly the materialized local route with the expected path/query values;
- prove missing/undeclared path parameters are rejected before mutation.

## Scope

Do not start Task 013 / Stage 07. Fix only the four Stage 06 issues above and directly exposed regressions.

Re-run the focused Stage 06 acceptance suite plus relevant Task 007–011 isolation/read/UI/explorer regressions and relevant auth/maintenance/packet/merge/supervisor tests. Also run Ruff, `py_compile`, changed/new-file GRACE lint and `git diff --check`.

Then create/update:

`docs/work/agent_exchange/outbox/012_RESUBMISSION.md`

Include the fix commit SHA and concise proof for:

- fail-closed uncertain maintenance ownership;
- mutation runtime-identity enforcement;
- fail-closed/visible canonical audit persistence;
- parameterized OpenAPI mutation execution;
- regression/check results.

Do not start Task 013 until reviewer returns `ACCEPT 012`.
