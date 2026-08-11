# TZ 06_ADMIN_MUTATION — Grace Local Adopt guarded mutation headroom

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_06_NEAR_LIMIT_FOLLOWUP.md` Part B3
Dependencies: block 05 admin hard-limit work accepted; `06_ADMIN_CROSS_PROJECT` accepted

## Coder protocol

You are the Coder for this named TZ. Read and execute **only this file**. Do not open or start another inbox task/TZ unless the Architect explicitly names it after ACCEPT.

Before editing:

1. Work in `/opt/grace-orchestrator`.
2. Fast-forward sync with GitHub. Checkout must be clean and updated from `origin/main` using fast-forward-only sync; do not create a merge commit.
3. If the checkout cannot fast-forward cleanly, stop and report the blocker; do not overwrite local work.

After implementation:

1. Run the required verification below.
2. Commit and push the implementation.
3. Create **only** `docs/work/agent_exchange/outbox/06_ADMIN_MUTATION_SUBMISSION.md`.
4. Do not create the next task, review file, state/lock/orchestration metadata or unrelated coordination files.

Submission header must be exactly:

```text
WEB_ORCH_REPORT: SUBMISSION 06_ADMIN_MUTATION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <implementation-sha>
WEB_ORCH_CHECKS: PASS
```

If Architect returns REVIEW, read only `docs/work/agent_exchange/inbox/06_ADMIN_MUTATION_REVIEW.md`, fix it, and report only to `docs/work/agent_exchange/outbox/06_ADMIN_MUTATION_RESUBMISSION.md`.

## Goal

Create substantial structural headroom in:

- `src/grace_control/services/admin_mutation_service.py`

The current module is about 930 physical lines and mixes capability/catalog reads, action validation/confirmation, ordinary mutation execution, OpenAPI mutation discovery/guarding, transport identity verification, remote-result normalization and many pure helpers.

This packet implements **only block 06 Part B3**. Keep `AdminMutationService` as the stable guarded mutation facade and extract coherent owners/helpers without changing mutation policy or observable results.

Structural targets:

- `admin_mutation_service.py` should preferably land around `<= 550–700` lines, and substantially smaller is fine when responsibility boundaries are clean;
- every touched/new function or async function must be `<= 4000` Grace-estimated tokens (`len(source) // 4`), with orchestration normally `<= 2500–3000`;
- every new Python module must be `<= 1000` lines, preferably `<= 800`;
- do not move one giant method verbatim into another near-limit file, compress code, use service-locator tricks, or obscure identifiers for lint.

## Owned write scope

Primary:

- `src/grace_control/services/admin_mutation_service.py`
- new focused mutation modules under `src/grace_control/services/`
- directly affected admin mutation/control tests when genuinely needed

Optional only for a genuine textual **non-size** GraceLint false positive introduced by moved code:

- `.grace/lint_allowlist.yaml`

Never add `GRC005` or `GRC012` suppression. Never use `getattr`, `__dict__`, split strings, dynamic imports or similar constructions merely to hide a normal identifier from GraceLint. Existing compatibility `getattr` used to probe client transport capabilities is business behavior and may remain where appropriate; do not confuse that with lint-evasion.

### Explicitly out of scope

Do not modify/refactor in this TZ:

- `src/grace_control/api/routers/admin_controls.py`
- `src/grace_control/api/routers/admin_control_center.py`
- accepted `admin_cross_project_service.py` / its new mixins except an unavoidable tiny compatibility fix
- block-05 control-center/aggregation services except an unavoidable tiny compatibility fix
- acceptance pipeline files
- DB schema/migrations, settings, state machine, templates/UI or public API schemas/routes

Routers are the next responsibility group after the mutation service settles; do not start them now.

## Stable public/compatibility surface

Preserve existing import paths and callable contracts for at least:

- `grace_control.services.admin_mutation_service.AdminMutationService`
- `AdminMutationService.__init__(hub)`
- `AdminMutationService.available_controls(...)`
- `AdminMutationService.execute(...)`
- `AdminMutationService.execute_openapi(...)`
- `grace_control.services.admin_mutation_service.normalize_mutation_result`
- `grace_control.services.admin_mutation_service.UNKNOWN_OUTCOME_MESSAGE`

Before moving internals, search current code/tests for direct imports, monkeypatches or calls of private helpers/methods and preserve demonstrated seams by delegation/re-export where needed. At minimum inspect `_read_entity_state(...)` and `_call_project(...)`, because control tests may patch transport/state behavior there.

Keep `self._hub` compatibility and continue using the accepted `AdminCrossProjectService` boundaries:

- `hub._registry` for immutable project selection;
- `hub._request(...)` for selected-project reads/identity checks;
- `hub._client_factory(context)` only at the mutation transport boundary where current behavior requires it.

Do not bypass the accepted cross-project facade by opening project state directly.

## Required responsibility decomposition

Split by real responsibility. Exact module/class names are flexible, but a good ownership map is:

1. **Control catalog / state-aware availability**
   - capability read;
   - disabled-project behavior;
   - entity-state read;
   - deterministic action catalog;
   - advertised-capability + current-state fail-closed availability.

2. **Action validation and confirmation**
   - project key/action/entity validation;
   - aliases and strong/normal action classification;
   - typed confirmation semantics;
   - bounded request parameters/request IDs;
   - preferably pure helpers in one focused owner rather than duplicated checks.

3. **Mutation transport / identity guard**
   - exactly one selected-project mutation attempt;
   - health/runtime identity verification before mutation;
   - disabled-project rejection;
   - `mutate_json` / `request_json` compatibility probing;
   - request ID/actor propagation according to supported client signatures;
   - no retry and no cross-project fallback.

4. **OpenAPI mutation guard**
   - non-GET/HEAD/OPTIONS requirement;
   - safe same-origin path validation;
   - dangerous control/lifecycle/claim/shutdown prefix rejection;
   - exact discovered `(method, path)` mutation requirement from selected project's OpenAPI;
   - `_openapi_request` parameter materialization/error behavior;
   - confirmation before transport;
   - mutation still goes through the narrow local OpenAPI control endpoint, never arbitrary URL execution.

5. **Result normalization**
   - canonical success/failed/unknown-after-timeout DTO mapping;
   - identity mismatch/unavailable mapping;
   - planned/501 unavailable mapping;
   - wait-state mapping;
   - masking, status/error/retry/attention fields;
   - `UNKNOWN_OUTCOME_MESSAGE` exact compatibility.

Do not duplicate security/openapi helpers already owned by `admin_control_security.py` or `admin_control_center_explorer_helpers.py`.

## Mutation behavior that must not drift

This is refactor-only. Preserve exactly, where applicable:

- one explicit immutable project key; no broadcast/all selector;
- unsupported actions rejected with current error codes/messages;
- action aliases remain identical;
- entity-ID requirements and safety limits remain identical;
- every mutation requires explicit confirmation;
- strong actions and OpenAPI mutations require the same typed identity value as today;
- read-only catalog actions are never executed as mutations;
- disabled projects do not mutate;
- selected runtime identity is verified before mutation;
- identity mismatch and identity unavailable remain distinct fail-closed results/statuses;
- no mutation retry after timeout/disconnect;
- ambiguous transport outcome remains `unknown_after_timeout`, with exact `UNKNOWN_OUTCOME_MESSAGE`, `retry_allowed=False` and operator attention semantics;
- planned/not-implemented runtime behavior remains unavailable rather than optimistic success;
- wait payloads remain non-success with current wait/error/retry mapping;
- actor/request ID propagation remains bounded and masked where currently rendered;
- secret masking remains through `mask_operator_data`;
- no direct project DB/filesystem/Git/process mutation from the Hub.

## OpenAPI behavior that must not drift

Preserve:

- method uppercasing and rejection of GET/HEAD/OPTIONS;
- `_safe_openapi_path` same-origin/path-only protection;
- dangerous prefix list and semantics;
- selected-project `/openapi.json` discovery through `hub._request`;
- operation must be exactly discovered and marked mutation;
- query/path parameter validation via existing explorer helper;
- bounded parameters/body behavior;
- strong confirmation semantics;
- payload keys sent to the local OpenAPI control endpoint;
- at most one remote mutation call;
- error/status/result shapes for undiscovered/unsafe/invalid-parameter/invalid-confirmation cases.

No public route or OpenAPI schema is changed by this service refactor.

## Regression protection / tests

Existing behavioral tests are the contract and must not be weakened.

Before coding, discover actual current callers/tests. At minimum inspect and run relevant coverage around:

- `tests/grace_control/api/test_admin_controls_stage06.py`;
- current Stage 07 / Stage 07 matrix Control Center tests;
- admin control-center explorer/API mutation tests;
- admin router/OpenAPI tests;
- any tests that patch `AdminMutationService`, `_call_project`, `_read_entity_state`, `normalize_mutation_result`, Hub `_request` or client mutation methods.

Keep coverage for:

1. constructor/public compatibility;
2. capability catalog, disabled project and unavailable capability behavior;
3. packet/feature/project action availability by current state;
4. invalid project/action/entity/confirmation rejection;
5. normal vs strong confirmation;
6. identity mismatch/unavailable fail-closed behavior;
7. exactly-one mutation transport and no retry;
8. timeout/disconnect UNKNOWN OUTCOME behavior and exact message;
9. successful/failed/planned/wait result normalization;
10. OpenAPI safe-path/dangerous-prefix/discovery/method/parameter/confirmation gates;
11. request-id and actor propagation through compatible fake/real client shapes;
12. project isolation with the accepted `AdminCrossProjectService` facade;
13. Control Center/API callers continuing to use the same facade without route/schema changes.

Allowed test edits:

- add focused unit tests for extracted owners/branching pure helpers;
- minimally retarget a private monkeypatch when ownership genuinely moved;
- add compatibility-import/delegation coverage.

Forbidden:

- deleting or weakening behavioral assertions;
- broad skip/xfail additions;
- changing expected error/status/result/state merely to fit refactored code;
- weakening confirmation/identity/path guards;
- replacing integration coverage with mocks only.

## Verification

Run directly affected mutation/control tests first, then at minimum:

```bash
make test
make lint
make docs-check
git diff --check
```

Also run:

- `.venv/bin/python -m py_compile` on the facade and every touched/new mutation Python module;
- `python3 scripts/grace_lint.py` targeted at every touched/new source module;
- Ruff targeted at touched/new modules when available;
- focused mutation + Control Center + router/OpenAPI compatibility tests discovered from current imports.

For every required command that is non-zero, compare the exact failure-node/output set against a **clean parent checkout** using the same environment and exact command arguments. Do not merely call historical failures baseline.

`make lint` may still stop because the repository `.venv` lacks Ruff. Re-attempt it and report exact current/parent results; targeted Ruff and GraceLint still must pass.

This service-only packet must not change routes. Run the current admin router/OpenAPI semantic tests and/or semantic OpenAPI hash comparison. `make docs-check` must introduce no new generated drift; if it is non-zero from existing baseline, prove exact parent equivalence.

## Acceptance criteria

Architect ACCEPT requires all of the following:

1. substantial structural headroom in `admin_mutation_service.py` with every new/touched module bounded;
2. no touched/new file >1000 lines and no function >4000 estimated tokens;
3. extraction by coherent catalog/validation/transport/OpenAPI/result responsibility rather than arbitrary slicing;
4. stable `AdminMutationService`, constructor, three public methods, `normalize_mutation_result` and `UNKNOWN_OUTCOME_MESSAGE` compatibility;
5. demonstrated private monkeypatch/import seams preserved where current callers rely on them;
6. immutable project selection and accepted Hub `_registry`/`_request`/client boundary preserved;
7. confirmation, identity, OpenAPI path/discovery and no-retry guards unchanged;
8. success/failure/wait/planned/unknown DTOs and exact unknown-outcome message unchanged;
9. request-id/actor propagation and masking unchanged;
10. existing security/explorer helpers reused rather than duplicated;
11. existing behavioral tests not weakened;
12. focused tests, targeted GraceLint/Ruff/py_compile and diff-check pass;
13. every broad non-zero result proven identical to clean parent;
14. no router/API/DB/config/state/UI/acceptance/cross-project refactor work included;
15. no `GRC005`/`GRC012` suppression or lint-evasion construction.

## Submission content

Report concisely:

- exact implementation SHA;
- files created/modified;
- before/after physical line count for `admin_mutation_service.py` and sizes of new owners;
- old responsibility -> new owner map;
- largest touched functions using `len(source) // 4`;
- public/private compatibility seams retained;
- tests changed/added and confirmation no behavioral assertion was weakened;
- exact focused test results;
- targeted GraceLint/Ruff/py_compile/diff-check results;
- exact `make test`, `make lint`, `make docs-check` results and clean-parent comparisons for every non-zero command;
- OpenAPI/route semantic comparison;
- allowlist changes and rationale, if any;
- confirmation that project isolation, confirmation/identity/OpenAPI/no-retry and normalization semantics are unchanged;
- follow-up debt only; do not start router refactors.