# TZ 06 — Controls, security, audit and maintenance

Depends on Stages 01-05.

## Objective

Add safe operator mutations to the Control Center without turning the Hub into a privileged arbitrary remote shell.

All mutations must go through project-local domain/API services, respect existing safety/fencing/state-machine rules, require appropriate confirmation and create audit evidence.

## 1. Capability-driven controls

The UI must only enable actions actually supported by the selected project runtime.

Possible actions include, where currently implemented:

```text
retry
resume
stop
cancel
archive
unarchive
merge
cleanup
restart worker(s)
restart API
restart all
supervisor reload
```

Do not implement fake success for existing 501/planned endpoints. Show `Not implemented / unavailable for this runtime`.

Control availability must consider entity state as well as API capability.

## 2. Hub mutation proxy

Admin Hub proxies an operator mutation to exactly one selected project.

Rules:

- no broadcast mutation endpoint by default;
- never retry a mutation automatically after timeout/connection failure unless the project API provides idempotency key semantics proving safety;
- attach/request a unique admin request ID;
- return remote status/error body faithfully in an operator-safe normalized response;
- project key is explicit and immutable for the request.

## 3. No direct DB/state mutation

Forbidden from Hub/UI:

```text
direct UPDATE packet state
direct DELETE lease rows
direct rm -rf worktree
direct git reset/merge command
arbitrary sudo -u project shell
```

Use existing PacketService/MergeService/Maintenance/Supervisor APIs and their fencing/state-machine checks.

If a needed control lacks a domain/API endpoint, add the endpoint in project-local runtime with explicit tests rather than bypassing the domain model.

## 4. Confirmation policy

Read-only GET/API Explorer execution needs no destructive confirmation.

Mutation actions require confirmation according to risk.

Examples:

### Normal confirmation

```text
retry
archive/unarchive
resume
```

### Strong confirmation

```text
stop
cancel
delete if ever supported
cleanup with deletion
restart all
manual merge/recovery operations
```

For strong actions show:

```text
project
entity/action
expected effect
current state
```

For the most destructive entity-scoped action require typing project key or packet ID if reasonable.

Do not make confirmation merely decorative; backend must reject missing confirmation token/intent metadata if the security design uses one.

## 5. OpenAPI Explorer mutations

Stage 05 exposed mutation endpoints as documentation only.

Stage 06 may allow execution under a gated mode:

```text
Enable control actions
```

Requirements:

- only selected project's own discovered OpenAPI path;
- user authorization checked;
- no arbitrary URL/method;
- clearly distinguish read vs mutation;
- confirmation before execution;
- show exact request body excluding masked secrets;
- response status/body shown;
- audit trail created.

Consider denying especially dangerous generic/internal endpoints from API Explorer even when present in OpenAPI and exposing them only via dedicated UI.

## 6. Audit events

Every operator mutation must produce auditable events.

Minimum logical events:

```text
admin_action_requested
admin_action_completed
admin_action_failed
```

Payload fields:

```json
{
  "project_key": "astro",
  "action": "retry",
  "entity_type": "packet",
  "entity_id": "pkt_...",
  "actor": "display-safe identity",
  "request_id": "...",
  "result": "success|failed|unknown_after_timeout",
  "reason": "..."
}
```

Do not log authentication secrets or full fencing tokens.

Prefer project-local Event as canonical audit record because that project owns the mutation. Hub may also keep a Hub audit log if useful, but it does not replace project-local audit.

## 7. Authentication/authorization

Preserve existing AuthMiddleware behavior and explicitly authorize Hub routes.

At minimum distinguish:

```text
read-only operator
control operator/admin
```

if current auth infrastructure supports roles. If roles do not exist, do not invent a weak client-side role switch; document and enforce the strongest available server-side boundary.

Localhost bypass, if existing, must remain explicitly limited to the intended deployment model.

## 8. CSRF/request origin

For cookie/session-authenticated browser mutations apply the framework/current-stack CSRF/origin protection appropriate to the existing auth model.

Do not depend solely on a JavaScript modal for security.

## 9. Secret masking

Effective config/API responses/UI must mask at least:

```text
passwords
API tokens
bot tokens
Authorization headers
cookie/session secrets
private keys
full merge fencing tokens
credentials embedded in URLs
```

Masking should occur server-side before browser DTO creation.

Tests should include nested dict/list config structures and case-insensitive secret key names.

## 10. Maintenance UI

Preserve and extend existing Maintenance safely.

Project-scoped maintenance snapshot should show before action:

```text
worktrees
state directories
stale ordinary leases
parallel leases / stale reservation candidates
merge lease state
accepted abandoned reservations
disk usage
cleanup-protected resources
```

Preferred workflow:

```text
Dry run / snapshot
 -> operator review
 -> Execute cleanup
 -> result
```

Result:

```text
deleted/cleaned
kept
reason kept
errors
bytes freed
```

Never expose a generic `delete path` UI.

Existing safety invariants from safe parallel execution remain mandatory: cleanup must not delete live worktrees, bypass merge fencing or reclaim uncertain ownership fail-open.

## 11. Supervisor controls

Where existing supervisor control API supports it, expose:

```text
status
restart API
restart workers
restart all
reload
cleanup
```

Show current PIDs/worker IDs and resulting state after action.

A failed restart must leave a visible error/attention item; do not show success just because the Hub request was accepted.

## 12. Merge/retry controls

Any manual packet action must use current packet state and current ownership/fencing contract.

Examples:

- cannot merge non-ACCEPTED packet;
- parallel runtime cannot bypass retained parallel-lease fencing;
- retry cannot overwrite live RUNNING ownership;
- stale-base protection remains active;
- merge slot WAIT is shown as wait, not mutation failure requiring blind retry.

Do not duplicate state transition logic in Admin router.

## 13. Offline/unknown outcome handling

Mutation timeout is special: the Hub may not know whether the remote project executed the action.

Return/display:

```text
UNKNOWN OUTCOME — verify project state before retrying
```

Then refresh entity/events before offering the same mutation again.

Do not auto-repeat.

## 14. Tests

Required minimum:

1. read-only operator cannot call control endpoint;
2. authorized operator can execute a safe project-local action;
3. mutation is routed only to selected project;
4. one project's action cannot alter another project;
5. confirmation policy enforced server-side where designed;
6. admin_action requested/completed/failed audit rows emitted;
7. timeout yields unknown outcome and no automatic retry;
8. secrets are masked in config/API Explorer/request display/audit;
9. arbitrary URL/method rejected by API Explorer;
10. known mutation path can execute after control mode + confirmation;
11. planned/501 control renders unavailable, not success;
12. maintenance dry run makes no mutation;
13. maintenance preserves live/uncertain worktree ownership;
14. supervisor restart action reports failure correctly;
15. packet merge/retry UI cannot bypass existing state/fencing rules;
16. CSRF/origin/auth regression appropriate to current auth stack.

Use two projects in mutation isolation tests.

## 15. Acceptance

Stage 06 is complete when the Admin Control Center can perform all supported routine operator actions without direct DB/filesystem/shell bypasses, with clear confirmations, project isolation, server-side authorization and auditable outcomes.
