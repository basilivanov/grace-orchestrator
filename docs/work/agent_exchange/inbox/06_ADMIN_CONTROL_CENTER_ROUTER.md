# TZ 06_ADMIN_CONTROL_CENTER_ROUTER — Grace Local Adopt Control Center route headroom

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_06_NEAR_LIMIT_FOLLOWUP.md` Part B4
Dependencies: block 05 accepted; `06_ADMIN_CROSS_PROJECT`, `06_ADMIN_MUTATION`, and `06_ADMIN_CONTROLS_ROUTER` accepted

## Coder protocol

You are the Coder for this named TZ. Read and execute **only this file**. Do not open or start another inbox task/TZ unless the Architect explicitly names it after ACCEPT.

Before editing:

1. Work in `/opt/grace-orchestrator`.
2. Fast-forward sync with GitHub. Checkout must be clean and updated from `origin/main` using fast-forward-only sync; do not create a merge commit.
3. If fast-forward cannot be done cleanly, stop and report the blocker; do not overwrite local work.

After implementation:

1. Run the required verification below.
2. Commit and push the implementation.
3. Create **only** `docs/work/agent_exchange/outbox/06_ADMIN_CONTROL_CENTER_ROUTER_SUBMISSION.md`.
4. Do not create the next task, review file, state/lock/orchestration metadata or unrelated coordination files.

Submission header must be exactly:

```text
WEB_ORCH_REPORT: SUBMISSION 06_ADMIN_CONTROL_CENTER_ROUTER
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <implementation-sha>
WEB_ORCH_CHECKS: PASS
```

If Architect returns REVIEW, read only `docs/work/agent_exchange/inbox/06_ADMIN_CONTROL_CENTER_ROUTER_REVIEW.md`, fix it, and report only to `docs/work/agent_exchange/outbox/06_ADMIN_CONTROL_CENTER_ROUTER_RESUBMISSION.md`.

## Goal

Create substantial structural headroom in:

- `src/grace_control/api/routers/admin_control_center.py`

This is **only block 06 Part B4**. Make the near-limit Control Center router a stable route-composition facade while preserving every current HTML/HTMX route, query/path parameter, response class, rendering behavior, template context, project isolation rule and `AdminControlCenterService` boundary.

This is a router refactor only. The accepted block-05 service decomposition is authoritative and must not be reopened.

Structural targets:

- `admin_control_center.py` preferably `<= 500–650` physical lines; substantially smaller is fine when historical route names/decorators remain clear;
- every new/touched module `<= 1000` lines, preferably `<= 700–800`;
- every function/async function `<= 4000` Grace-estimated tokens (`len(source) // 4`), with route orchestration normally well below `2500–3000`;
- no compressed code, giant catch-all owner, dynamic route registration tricks, service locators or identifier obfuscation.

## Owned write scope

Primary:

- `src/grace_control/api/routers/admin_control_center.py`
- new focused Control Center router/composition modules under `src/grace_control/api/routers/`
- directly affected Control Center/router/OpenAPI/template integration tests when genuinely needed

Optional only for a genuine textual **non-size** GraceLint false positive introduced/exposed by readable code:

- `.grace/lint_allowlist.yaml`

Never add `GRC005` or `GRC012` suppression. Never hide normal identifiers through `__dict__`, split strings, dynamic imports or `getattr` merely to pass GraceLint. The current facade contains `request.app.__dict__["state"]`; because this file is being refactored, replace such ordinary app-state access with the normal supported form. If a textual rule falsely flags the readable access, use one narrow documented non-size allowlist entry rather than another spelling trick.

### Explicitly out of scope

Do not modify/refactor in this TZ:

- accepted `src/grace_control/api/routers/admin_controls.py` or its owner modules except an unavoidable tiny compatibility fix;
- accepted `AdminControlCenterService` facade/owners from block 05 except an unavoidable tiny compatibility fix;
- accepted `AdminCrossProjectService` / mixins;
- accepted `AdminMutationService` / owners;
- acceptance pipeline;
- DB schema/migrations, settings, state machine, templates/UI design, public JSON API routes/schemas.

Do not add features, redesign templates, change navigation semantics or alter service DTOs.

## Stable module / rendering surface

Preserve import compatibility for:

- `grace_control.api.routers.admin_control_center.router`

Before moving helpers or route bodies, search current code/tests/templates for direct imports/monkeypatches. Preserve demonstrated seams by facade wrapper/re-export when needed.

In particular inspect and preserve compatibility where relied on for:

- `_service`
- `_render`
- `_render_fragment`
- `_render_project_partial`
- `_cc_url`
- `_cc_query_url`
- `_partial_url`
- `_status_icon`
- `_raise_project_not_found`
- `_templates` / registered template globals when current tests/templates depend on them.

The safest pattern is the one accepted for `06_ADMIN_CONTROLS_ROUTER`: keep the historical decorators, route function names/signatures and operation IDs in the facade, and delegate bodies to coherent owner functions with explicit callbacks. Do not use automatic/dynamic route registration.

## Route surface that must remain exact

Preserve **every** current decorator/alias, including the current dashboard/project/explorer/global/partial routes. At minimum the current file includes:

- `GET /admin`
- `GET /admin/projects`
- `GET /admin/_partial/projects`
- `GET /admin/p/{project_key}`
- `GET /admin/p/{project_key}/feature/{feature_id}`
- `GET /admin/p/{project_key}/wave/{wave_id}`
- `GET /admin/p/{project_key}/packet/{packet_id}`
- `GET /admin/p/{project_key}/system`
- `GET /admin/p/{project_key}/maintenance`
- `GET /admin/p/{project_key}/git`
- `GET /admin/p/{project_key}/files`
- `GET /admin/p/{project_key}/api`
- `GET /admin/p/{project_key}/events`
- `GET /admin/p/{project_key}/logs`
- `GET /admin/events`
- `GET /admin/logs`
- `GET /admin/search`
- `GET /admin/p/{project_key}/_partial/content`
- `GET /admin/_partial/project`
- `GET /admin/p/{project_key}/_partial/system`

This list is not permission to drop anything else found in the live parent. Generate an exact parent route inventory before coding and prove current vs implementation equality afterward.

Preserve decorator order, function names, `response_class=HTMLResponse`, query/path parameter names/defaults/constraints, FastAPI operation IDs/OpenAPI-visible metadata where applicable, and all status/error semantics.

## Required responsibility decomposition

Split by real UI/router responsibility. Exact filenames are flexible, but coherent ownership should resemble:

1. **Dashboard / project shell owner**
   - `/admin`, `/admin/projects`, project cards partial;
   - project overview/feature/wave deep links;
   - empty-registry legacy-console fallback;
   - selected-project 404 mapping.

2. **Packet / project explorer route owner**
   - packet deep link and its tab/run/stage/timeline/file/git selectors;
   - system, maintenance, Files, Git, API pages;
   - project-scoped Events/Logs pages;
   - only map HTTP/query inputs to the accepted `AdminControlCenterService`; do not duplicate service assembly or safety policy.

3. **Global explorer owner**
   - cross-project Events/Logs/Search pages;
   - project filters and HTMX logs fragment behavior;
   - accepted Hub/service query semantics remain authoritative.

4. **HTMX partial owner**
   - project-content partial;
   - query-form compatibility partial;
   - system partial;
   - preserve explicit project/entity/tab/run/stage selectors and exact template names/context.

5. **Rendering / URL helpers**
   - shared template context construction;
   - canonical quoted project/entity URLs and bounded query composition;
   - template globals;
   - status icon helper;
   - keep these pure/read-only and explicit.

Avoid circular imports: owner modules must not import the facade back. Pass explicit callbacks/helpers from the facade when historical monkeypatch/template seams need to remain live.

## Authoritative boundaries to preserve

Reuse, do not duplicate:

- accepted `AdminControlCenterService` for all page/read-model composition;
- accepted `AdminCrossProjectService` behind that service;
- block-05 Files/Git/OpenAPI/project-isolation safety owners;
- Jinja2 templates and `register`ed template filters;
- FastAPI `Query` validation and existing response classes.

The router must remain a translation/rendering layer. Do not move DTO assembly, filesystem/Git/OpenAPI safety, packet/run/stage validation or mutation policy back into router code.

## Behavior that must not drift

Preserve exactly, where applicable:

- explicit `project_key`; no global current-project state;
- unknown project -> canonical UI 404;
- empty registry `/admin` fallback to legacy console;
- dashboard filter/default behavior;
- project/feature/wave/packet deep-link semantics;
- packet tab/run/stage/timeline/log/artifact/files/git selector names and defaults;
- Files/Git/API explorer query names and bounds;
- API control-mode/confirmation values passed exactly to the accepted service;
- actor header fallback;
- selected-project and cross-project Events/Logs filters/cursors/limits;
- HTMX Logs response uses the same fragment instead of full shell;
- project partial/query-partial compatibility and exact selectors;
- template filenames and context keys (`request`, `page`, project/current-project, `projects`, URL helpers, status helper);
- URL quoting/query omission semantics;
- status icon strings;
- all response/status/error behavior.

No hidden browser/session-selected project may be introduced.

## Route / template / OpenAPI compatibility gate

Compare clean parent vs implementation and prove:

- identical `(path, method, route function name)` set;
- no duplicate registration and no lost route;
- identical route signatures/defaults/Query constraints;
- no changed FastAPI operation IDs/OpenAPI route semantics attributable to this router split;
- exact template filenames rendered by every route/fragment;
- key context contracts remain unchanged.

Because these are HTML routes, do not rely only on generated JSON API docs; run the current Control Center UI/route integration tests and add a narrow route inventory test only if existing coverage cannot prove registration equality.

## Regression protection / tests

Existing behavioral tests are the contract and must not be weakened.

Before coding, discover actual current callers/tests. At minimum run relevant coverage around:

- Stage 07 Control Center tests;
- Stage 07 matrix tests;
- admin router/OpenAPI tests that instantiate the app;
- Files/Git/API explorer UI tests;
- Stage 06 control tests that enter Control Center mutation/API flows;
- any tests importing `_cc_url`, `_partial_url`, route functions, `_templates`, `_service` or render helpers.

Keep explicit coverage for:

1. route inventory / no duplicates;
2. dashboard and empty-registry fallback;
3. project isolation / unknown-project 404;
4. feature/wave/packet deep links;
5. packet query/default/constraint forwarding;
6. system/maintenance/files/git/api forwarding;
7. project + global events/logs/search forwarding;
8. HTMX Logs fragment behavior;
9. content/query/system partials;
10. exact template/context helper compatibility;
11. no OpenAPI/route semantic drift.

Allowed test edits:

- add focused route-registration or owner delegation tests;
- minimally retarget a private monkeypatch only when ownership genuinely moved;
- add compatibility wrapper coverage.

Forbidden:

- changing expected route/query/template behavior to fit implementation;
- removing/weakening project isolation or explorer safety coverage;
- broad skip/xfail additions;
- replacing integration coverage with mocks only.

## Verification

Run directly affected Control Center/UI/router suites first, then at minimum:

```bash
make test
make lint
make docs-check
git diff --check
```

Also run:

- `.venv/bin/python -m py_compile` on the facade and every touched/new Python module;
- `python3 scripts/grace_lint.py` targeted at every touched/new source module;
- Ruff targeted at touched/new modules when available;
- explicit parent/current route inventory comparison;
- focused Stage 07 + Stage 07 matrix + admin router/OpenAPI + Files/Git/API UI compatibility tests.

For every required command that is non-zero, compare the exact failure-node/output set against a **clean parent checkout** using the same environment and command arguments.

`make lint` may still stop because the repository `.venv` lacks Ruff. Re-attempt and report exact current/parent results; targeted Ruff and GraceLint still must pass.

`make docs-check` may retain existing generated drift only if exact clean-parent equivalence is proven.

## Acceptance criteria

Architect ACCEPT requires all of the following:

1. substantial headroom in `admin_control_center.py`;
2. no touched/new file >1000 lines and no function >4000 estimated tokens;
3. coherent dashboard/project/explorer/global/partial/render decomposition;
4. historical `router` import preserved;
5. complete route/function/signature/default/constraint set preserved exactly;
6. no duplicate registration or operation-ID drift;
7. rendering templates/context and URL/status helper semantics unchanged;
8. explicit project isolation, 404 and empty-registry fallback unchanged;
9. accepted Control Center service/safety owners remain authoritative;
10. demonstrated private/template monkeypatch/import seams preserved where relied on;
11. no identifier obfuscation in touched code; narrow documented non-size allowlist only for a genuine textual false positive;
12. existing tests not weakened;
13. focused tests, targeted GraceLint/Ruff/py_compile and diff-check pass;
14. every broad non-zero result proven identical to clean parent;
15. no accepted services, other router, DB/config/state/templates/acceptance refactor included;
16. no `GRC005`/`GRC012` suppression.

## Submission content

Report concisely:

- implementation SHA;
- files created/modified;
- before/after physical line count for `admin_control_center.py` and sizes of new modules;
- route/responsibility -> new owner map;
- largest touched functions using `len(source) // 4`;
- exact parent/current route inventory comparison;
- public/private/template compatibility seams retained;
- tests changed/added and why, confirming no assertion weakening;
- exact focused test results;
- targeted GraceLint/Ruff/py_compile/diff-check results;
- exact `make test`, `make lint`, `make docs-check` results with clean-parent comparison for every non-zero command;
- route/OpenAPI/template semantic comparison;
- allowlist changes/rationale, if any;
- confirmation that project isolation, query/default/template/HTMX/service-boundary semantics are unchanged;
- follow-up debt only. Do not start the final integration gate packet.