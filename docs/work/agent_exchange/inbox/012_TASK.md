# Task 012 — Admin Control Center Stage 06: Controls, Security and Maintenance

Status: READY

Source of truth:
- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_06_CONTROLS_SECURITY_MAINTENANCE.md`
- Admin Control Center master/index documents
- Accepted Tasks 007–011

## Objective

Implement **only Stage 06**: safe project-scoped operator mutations, authorization/security, audit and maintenance controls on top of the accepted multi-project read/explorer architecture.

All mutations must go through the selected project's existing domain/API services and preserve state-machine, ownership, parallel-lease, merge-fencing and stale-base safety. The Hub must never become an arbitrary remote shell, direct DB mutator, generic filesystem deleter or arbitrary Git command runner.

Do **not** start Stage 07 / Task 013.

## Required implementation

### 1. Capability/state-driven controls

Expose only actions actually supported by the selected project runtime and valid for the current entity state. Where existing runtime APIs support them, this may include retry, resume, stop/cancel, archive/unarchive, merge, cleanup, worker/API/all restart and supervisor reload.

- Existing 501/planned endpoints must render `Not implemented / unavailable for this runtime`, never fake success.
- Availability must consider both advertised capability and current entity state.
- Do not duplicate packet transition/fencing logic in Admin routers/templates.

### 2. Single-project mutation proxy

Add a Hub mutation service boundary that targets exactly one explicit immutable `project_key` per request.

- No broadcast mutation endpoint by default.
- Generate/propagate a unique admin request ID.
- Never automatically retry a mutation after timeout/connection failure unless an existing project API explicitly provides safe idempotency-key semantics.
- Normalize remote status/error bodies without losing meaningful project error state.
- Mutation timeout/ambiguous disconnect must return an explicit **UNKNOWN OUTCOME — verify project state before retrying** state and refresh/verify project/entity/events before re-offering blind retry.

### 3. No direct privileged bypasses

Forbidden from Hub/UI implementation:

- direct packet/lease DB UPDATE/DELETE;
- direct project SQLite access;
- direct `rm -rf` or generic delete-path behavior;
- direct `git reset/merge` shell commands;
- arbitrary `sudo -u` / shell execution;
- process-global project switching.

If a control lacks a proper project-local domain/API endpoint, add a narrow project-local endpoint backed by the existing service/domain model with explicit tests; do not bypass it from the Hub.

### 4. Confirmation policy

Implement real server-enforced confirmation appropriate to risk.

Normal confirmation examples: retry, resume, archive/unarchive.

Strong confirmation examples: stop/cancel, destructive cleanup, restart all, manual merge/recovery. Strong confirmation must clearly show project, action/entity, expected effect and current state; for the most destructive entity-scoped actions require typing project key or packet ID where reasonable.

A JavaScript modal alone is not sufficient. Missing/invalid required confirmation intent/token must be rejected server-side.

### 5. OpenAPI Explorer mutation mode

Stage 05 GET behavior remains safe/read-only by default. Stage 06 may add an explicit `Enable control actions` mode for discovered mutations, subject to all of:

- selected project's own safe discovered OpenAPI path only;
- server-side authorization;
- no arbitrary URL/method;
- mutation clearly distinguished from GET;
- confirmation before execution;
- bounded request body/parameters with secrets masked in display;
- response status/body shown safely;
- audit trail emitted;
- especially dangerous generic/internal endpoints may remain denied and available only through dedicated controls.

Preserve the Stage 05 same-origin/path protections and mutation-disabled behavior when control mode is off.

### 6. Audit trail

Every operator mutation must create project-local auditable logical events equivalent to:

- `admin_action_requested`
- `admin_action_completed`
- `admin_action_failed`

Audit data must include project key, action, entity type/id, display-safe actor, request ID, result (`success|failed|unknown_after_timeout`) and reason where applicable.

Never log authentication secrets, cookie/session secrets, credentials or full fencing tokens. A Hub audit log may supplement but never replace the project-local canonical event.

### 7. Authentication/authorization and request-origin safety

Preserve existing AuthMiddleware semantics and explicitly authorize Hub mutation routes.

- At minimum enforce the strongest existing server-side distinction between read-only and control access. If role infrastructure exists, use it; do not invent a client-side role switch.
- Existing localhost bypass must remain constrained to the intended deployment model.
- Apply the current-stack CSRF/origin protection appropriate to cookie/session browser mutations.
- GET/read surfaces must remain unaffected except where necessary to expose capability/authorization state.

### 8. Secret masking

Server-side masking must cover nested dict/list structures and case-insensitive credential-shaped names, including passwords, API/bot tokens, Authorization headers, cookie/session secrets, private keys, full fencing tokens and credentials embedded in URLs.

Mask before browser DTO creation, request display and audit serialization.

### 9. Maintenance workflow

Extend project-scoped Maintenance with a safe workflow:

`Dry run / snapshot -> operator review -> confirmed Execute cleanup -> result`

Snapshot/result should cover where available:

- worktrees;
- state directories;
- stale ordinary leases;
- parallel leases / stale reservation candidates;
- merge lease state;
- accepted abandoned reservations;
- disk usage;
- cleanup-protected resources;
- deleted/cleaned vs kept + reason + errors + bytes freed.

Never expose generic delete-path UI. Cleanup must preserve live/uncertain ownership, active worktrees and fencing invariants fail-closed.

### 10. Supervisor controls

Where current supervisor APIs support them, expose status and safe restart/reload/cleanup actions. Show current PID/worker identity and resulting state.

An accepted Hub request is not sufficient to render success: failed restart/reload must remain visibly failed/attention-worthy after result verification.

### 11. Merge/retry controls

Use current project-local packet/domain services and ownership/fencing contracts.

Examples that must remain impossible:

- merge non-ACCEPTED packet;
- bypass retained parallel-lease fencing;
- retry over live RUNNING ownership;
- bypass stale-base protection;
- treat merge-slot WAIT as mutation failure requiring blind retry.

## Required acceptance tests

At minimum cover deterministically, using **two projects** for mutation isolation:

1. read-only operator cannot invoke a control endpoint;
2. authorized operator can execute a supported safe project-local action;
3. mutation routes only to the selected project;
4. one project's action cannot alter another project;
5. server-side confirmation policy is enforced;
6. requested/completed/failed audit rows are emitted with safe fields;
7. timeout yields unknown outcome and no automatic retry;
8. secrets are masked in config, API Explorer/request display and audit, including nested/case-insensitive cases;
9. arbitrary URL/method remains rejected by API Explorer;
10. a known discovered mutation can execute only after control mode + authorization + confirmation;
11. planned/501 control renders unavailable, never success;
12. maintenance dry run performs no mutation;
13. maintenance preserves live/uncertain worktree ownership and fencing;
14. supervisor restart failure is reported as failure/attention, not success;
15. merge/retry UI cannot bypass existing state/fencing rules;
16. CSRF/origin/auth regression appropriate to the existing auth stack;
17. Task 007–011 isolation/read/UI/explorer regressions remain green.

Prefer deterministic ASGI/service/domain tests. Add browser tests only for confirmation/UI behavior that cannot be proven reliably at ASGI level; environment-dependent browser tests may explicitly skip when the harness is unavailable, but deterministic security/domain coverage must not depend on the browser.

## Checks

Run and report:

- focused Stage 06 acceptance suite;
- Task 007–011 relevant regressions;
- relevant existing Admin/auth/maintenance/supervisor/domain tests;
- Ruff for changed/new Python files;
- `py_compile` for changed/new Python files;
- GRACE lint for changed/new files;
- `git diff --check`.

If repository-wide unrelated legacy failures remain, separate them explicitly from new Stage 06 failures; do not hide any failure caused by this task.

## Required result

Commit and push implementation, then create:

`docs/work/agent_exchange/outbox/012_SUBMISSION.md`

Keep the report concise and include:

- implementation commit SHA;
- mutation proxy/auth/confirmation/audit work;
- maintenance/supervisor/packet/OpenAPI control behavior actually implemented vs unavailable capabilities;
- selected-project isolation and unknown-outcome proof;
- secret/CSRF/origin safety proof;
- test/check results and any deviations.

Do not start Task 013 until reviewer returns `ACCEPT 012`.
