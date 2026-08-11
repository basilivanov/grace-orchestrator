# TZ 06_ADMIN_CONTROLS_ROUTER — Grace Local Adopt admin controls route headroom

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_06_NEAR_LIMIT_FOLLOWUP.md` Part B1
Dependencies: block 05 accepted; `06_ADMIN_CROSS_PROJECT` accepted; `06_ADMIN_MUTATION` accepted

## Coder protocol

You are the Coder for this named TZ. Read and execute **only this file**. Do not open or start another inbox task/TZ unless the Architect explicitly names it after ACCEPT.

Before editing:

1. Work in `/opt/grace-orchestrator`.
2. Fast-forward sync with GitHub. Checkout must be clean and updated from `origin/main` using fast-forward-only sync; do not create a merge commit.
3. If fast-forward cannot be done cleanly, stop and report the blocker; do not overwrite local work.

After implementation:

1. Run the required verification below.
2. Commit and push the implementation.
3. Create **only** `docs/work/agent_exchange/outbox/06_ADMIN_CONTROLS_ROUTER_SUBMISSION.md`.
4. Do not create the next task, review file, state/lock/orchestration metadata or unrelated coordination files.

Submission header must be exactly:

```text
WEB_ORCH_REPORT: SUBMISSION 06_ADMIN_CONTROLS_ROUTER
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <implementation-sha>
WEB_ORCH_CHECKS: PASS
```

If Architect returns REVIEW, read only `docs/work/agent_exchange/inbox/06_ADMIN_CONTROLS_ROUTER_REVIEW.md`, fix it, and report only to `docs/work/agent_exchange/outbox/06_ADMIN_CONTROLS_ROUTER_RESUBMISSION.md`.

## Goal

Create substantial structural headroom in:

- `src/grace_control/api/routers/admin_controls.py`

This is **only block 06 Part B1**. Make `admin_controls.py` a stable route-composition facade instead of a near-limit container while preserving every live route, alias, dependency, authorization/confirmation gate, status code, response body, audit event and mutation/maintenance/OpenAPI behavior.

Do not start the `admin_control_center.py` router refactor in this packet.

Structural targets:

- facade preferably `<= 450–650` physical lines, substantially smaller is fine when route composition remains readable;
- each new/touched router/helper module `<= 1000` lines, preferably `<= 700–800`;
- every function/async function `<= 4000` Grace-estimated tokens (`len(source) // 4`), with route orchestration normally well below `2500–3000`;
- no line compression, giant moved-verbatim catch-all module, service locator, dynamic route registration trick or identifier obfuscation to game lint.

## Owned write scope

Primary:

- `src/grace_control/api/routers/admin_controls.py`
- new focused admin-controls router/composition modules under `src/grace_control/api/routers/`
- directly affected admin control/router/OpenAPI tests when genuinely needed

Optional only for a genuine textual **non-size** GraceLint false positive introduced by moved code:

- `.grace/lint_allowlist.yaml`

Never add `GRC005` or `GRC012` suppression. Never hide normal identifiers with `getattr`, `__dict__`, split strings, dynamic imports or similar lint-evasion constructions. Existing `getattr` used for real compatibility/state probing may remain only where behavior actually requires it.

### Explicitly out of scope

Do not modify/refactor in this TZ:

- `src/grace_control/api/routers/admin_control_center.py`
- accepted `src/grace_control/services/admin_mutation_service.py` or its new owner modules except an unavoidable tiny compatibility fix
- accepted `admin_cross_project_service.py` / mixins except an unavoidable tiny compatibility fix
- accepted block-05 control-center/aggregation services except an unavoidable tiny compatibility fix
- acceptance pipeline files
- DB schema/migrations, settings, state machine, templates/UI or public API schemas solely to fit the split

Do not redesign mutation, confirmation, audit, maintenance, OpenAPI or domain state semantics while splitting routes.

## Stable module and route surface

Preserve import compatibility for:

- `grace_control.api.routers.admin_controls.router`
- `grace_control.api.routers.admin_controls.legacy_admin_action`

Before moving any other function/helper, search current code/tests for direct imports or monkeypatches and preserve every demonstrated seam by wrapper/re-export where needed. In particular inspect whether current tests/callers rely on route functions or helpers such as `local_control_action`, `_mutation_service`, `_control_body`, `_mutation_response`, `_confirmation_allowed`, `_openapi_operation_allowed`, maintenance helpers or local dispatch helpers.

The facade may compose/include focused subrouters, but importing the historical `router` must still register the complete existing route set exactly once.

Preserve all current paths and aliases, including at minimum:

- `GET /api/admin-hub/projects/{project_key}/controls`
- `POST /api/admin-hub/projects/{project_key}/controls`
- `POST /api/admin-hub/projects/{project_key}/control`
- `POST /api/admin-hub/projects/{project_key}/openapi-control`
- `POST /api/admin-hub/projects/{project_key}/api-control`
- `GET /api/admin-hub/projects/{project_key}/maintenance`
- `GET /api/admin/maintenance/snapshot`
- `POST /api/admin/control/action`
- `POST /api/admin/control/openapi`
- `POST /api/admin/maintenance/cleanup`

If current code contains additional route decorators/aliases, preserve those too. Do not treat this list as permission to drop anything not listed.

Preserve route methods, dependency/auth behavior, body/query/path parameter names/defaults, HTTP statuses, response media/body shape, operation visibility and OpenAPI-visible metadata where current tests or generated schema rely on it.

## Required responsibility decomposition

Split by actual use case. Exact module names are flexible, but a coherent result should resemble:

1. **Hub proxy routes**
   - selected-project control catalog;
   - selected-project ordinary mutation proxy;
   - selected-project discovered OpenAPI mutation proxy;
   - selected-project maintenance read;
   - continue delegating to accepted `AdminMutationService` / `AdminCrossProjectService` boundaries.

2. **Local action route / legacy adapter**
   - `/api/admin/control/action`;
   - `legacy_admin_action` compatibility adapter;
   - canonical local dispatch/audit flow;
   - do not duplicate the accepted Hub mutation policy or create a second state machine.

3. **Local maintenance routes**
   - snapshot/dry-run model;
   - confirmed cleanup;
   - preserve `AdminMaintenanceControlService` and `MaintenanceService` authority, lease/worktree safety and fail-closed behavior.

4. **Local OpenAPI route**
   - `/api/admin/control/openapi` same-ASGI execution;
   - exact operation discovery/path materialization;
   - confirmation, auth, audit, timeout/unknown-outcome and response masking semantics.

5. **Shared pure/router adapters** only when they are genuinely shared
   - mutation response mapping;
   - body/confirmation normalization;
   - audit adapters;
   - local action routing helpers.

Prefer explicit imports/composition over circular imports. Do not make subrouters import the facade back.

## Authoritative boundaries to preserve

Reuse rather than copy/reinvent:

- `AdminMutationService` for Hub-side mutation/catalog/OpenAPI mutation behavior;
- accepted `AdminCrossProjectService` for project registry/read transport;
- `admin_control_security.require_control_request` and masking;
- `admin_control_local_helpers` for audit identity/event/OpenAPI request materialization;
- `AdminMaintenanceControlService` and `MaintenanceService` for maintenance safety;
- existing project-local Packet/lifecycle/process services used by the current local dispatcher;
- `record_event`/current audit path exactly where current code requires canonical events.

Do not move DB aggregation/business state loops into new router modules. If current router code already delegates a state change to a service, keep that service authoritative. This packet is a structural route split, not a domain rewrite.

## Behavior that must not drift

Preserve exactly, where applicable:

- read token cannot mutate;
- control authorization and same-origin rules;
- embedded `project_key` cannot switch the path-selected project;
- one selected project only; no broadcast/reroute;
- unknown project/status mapping;
- confirmation alias normalization and strong confirmation behavior;
- Hub proxy result -> HTTP status mapping, including wait and `unknown_after_timeout`;
- exact `UNKNOWN_OUTCOME_MESSAGE` behavior;
- local action aliases and supported/unavailable action behavior;
- local action audit-before-mutation, success/failure audit and fail-closed audit errors;
- WAIT/merge-slot response semantics;
- maintenance dry-run/live-worktree/lease protection and cleanup result fields;
- local OpenAPI exact discovered operation checks, path parameter materialization, same-ASGI request, auth header forwarding, masking and timeout handling;
- no fake success on domain/supervisor/maintenance/downstream failure;
- request-id/actor propagation and secret masking;
- all existing status codes and response JSON keys.

## Route registration / OpenAPI requirements

This router packet has a strict route-set gate.

Compare clean parent vs implementation and prove:

- identical set of `(path, HTTP method)` operations attributable to these routes;
- no duplicate registration;
- no lost alias;
- no changed public path/method;
- no unexpected OpenAPI schema/operation drift caused by function movement or subrouter composition.

Where operation IDs or summaries are currently relied on by tests/generated docs, preserve them or prove semantic equality expected by the repository's current checks.

## Regression protection / tests

Existing behavior tests are the contract and must not be weakened.

Before coding, discover actual imports/callers and run relevant tests including at minimum:

- `tests/grace_control/api/test_admin_controls_stage06.py`;
- current Stage 06 review coverage if present;
- `tests/grace_control/api/test_admin_router.py`;
- `tests/grace_control/api/test_openapi_paths.py`;
- Stage 07 / Stage 07 matrix Control Center tests that use Hub controls;
- current maintenance, legacy admin mutation and local OpenAPI tests;
- any router tests that inspect route registration/operation IDs.

Keep explicit coverage for:

1. every route/alias still registered;
2. read-token/auth/origin rejection;
3. project isolation and body project-key switching rejection;
4. normal and strong confirmation;
5. ordinary Hub mutation + unknown/wait/status mapping;
6. local action audit and unsupported/planned/failure paths;
7. legacy adapter compatibility;
8. maintenance snapshot/dry-run/cleanup lease/worktree safety;
9. local OpenAPI discovery/path params/downstream failure/timeout semantics;
10. masking/request-id/actor propagation;
11. no route/schema drift.

Allowed test edits:

- add focused route-registration/composition tests;
- minimally retarget a private monkeypatch/import when ownership genuinely moves;
- add compatibility wrapper coverage.

Forbidden:

- deleting/weakening security/state/audit assertions;
- broad skip/xfail additions;
- changing expected HTTP status/body merely to fit the split;
- dropping route aliases;
- replacing integration coverage with mocks only.

## Verification

Run directly affected router/control suites first, then at minimum:

```bash
make test
make lint
make docs-check
git diff --check
```

Also run:

- `.venv/bin/python -m py_compile` on `admin_controls.py` and every touched/new Python module;
- `python3 scripts/grace_lint.py` targeted at every touched/new source module;
- Ruff targeted at touched/new modules when available;
- focused Stage 06 + router + OpenAPI + maintenance + Control Center compatibility tests;
- explicit parent/current route-set or semantic OpenAPI comparison.

For every required command that is non-zero, compare the exact failure-node/output set against a **clean parent checkout** using the same environment and exact command arguments. Do not merely label historical failures baseline.

`make lint` may still stop because the repository `.venv` lacks Ruff. Re-attempt it and report exact current/parent results; targeted Ruff and GraceLint must still pass.

`make docs-check` may still expose known generated-doc baseline drift. Prove exact clean-parent equivalence and no semantic route/OpenAPI drift.

## Acceptance criteria

Architect ACCEPT requires all of the following:

1. substantial structural headroom in `admin_controls.py`;
2. no touched/new module >1000 lines and no function >4000 estimated tokens;
3. coherent route-group decomposition rather than arbitrary slicing;
4. stable historical `router` import and `legacy_admin_action` compatibility;
5. complete route/alias set registered exactly once;
6. paths, methods, params/defaults, auth, confirmation, status codes and response bodies unchanged;
7. accepted mutation/cross-project/security/maintenance/domain owners remain authoritative;
8. local audit and fail-closed semantics unchanged;
9. OpenAPI same-origin/discovery/materialization/downstream semantics unchanged;
10. maintenance lease/worktree safety unchanged;
11. demonstrated private monkeypatch/import seams preserved where current callers rely on them;
12. existing tests not weakened;
13. focused tests, targeted GraceLint/Ruff/py_compile and diff-check pass;
14. exact parent equivalence proven for every broad non-zero command;
15. no `admin_control_center.py`, DB/config/state/UI/accepted-service refactor included;
16. no `GRC005`/`GRC012` suppression or lint-evasion construction.

## Submission content

Report concisely:

- implementation SHA;
- files created/modified;
- before/after physical line count for `admin_controls.py` and sizes of new modules;
- old route/responsibility -> new owner map;
- largest touched functions using `len(source) // 4`;
- route count and exact parent/current `(path, method)` comparison;
- public/private compatibility seams retained;
- tests changed/added and why, confirming no assertion weakening;
- exact focused test results;
- targeted GraceLint/Ruff/py_compile/diff-check results;
- exact `make test`, `make lint`, `make docs-check` results with clean-parent comparisons for every non-zero command;
- OpenAPI semantic comparison;
- allowlist changes and rationale, if any;
- confirmation that auth/project isolation/confirmation/audit/maintenance/OpenAPI/status/DTO semantics are unchanged;
- follow-up debt only; do not start `admin_control_center.py` router refactor.