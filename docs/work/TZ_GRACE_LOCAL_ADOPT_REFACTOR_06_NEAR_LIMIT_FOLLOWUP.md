# TZ — Grace Local Adopt refactor / 06 Near-limit follow-up

Status: READY FOR CODER
Parent: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Priority: P1
Dependency: block 01; admin part follows block 05

Targets:

- `src/grace_control/core/acceptance_pipeline.py`
- `src/grace_control/api/routers/admin_controls.py`
- `src/grace_control/services/admin_cross_project_service.py`
- `src/grace_control/services/admin_mutation_service.py`
- `src/grace_control/api/routers/admin_control_center.py`

These modules are close enough to the 1000-line ceiling that normal feature growth is likely to create new hard-limit failures. Do not put all targets into one coder packet.

## Part A — Acceptance pipeline

Primary target: `src/grace_control/core/acceptance_pipeline.py`.

### What we do

Create structural headroom while keeping acceptance behaviour unchanged. Preferred final size is <=650-750 lines; every function must remain below 4000 estimated tokens.

Split only by real responsibility. Candidate extraction areas:

- verification command execution and result collection;
- acceptance-specific changed-file/scope evaluation while reusing existing scope/Git owners;
- evidence/report construction;
- profile-specific evaluators if they form a stable interface.

Keep the existing public acceptance entry point import-compatible. The top-level function should coordinate stages rather than implement every check inline.

### What we do not change

Preserve command order, cwd/worktree behaviour, timeouts, stdout/stderr capture, acceptance profiles, verdict values, report keys, failure/reason mapping, artifact paths and base-SHA semantics.

### Tests

Yes, tests may change structurally when internals move. Existing behavioural expectations do not change.

Keep coverage for accepted flow, T0/T1/T2 failures, scope/diff rejection, evidence/report output, profiles, worktree/base SHA behaviour, command failure/timeout mapping and no-change cases where applicable.

Add focused unit tests for newly extracted evaluators with branching logic. Do not change expected verdicts merely to fit the refactor.

### Acceptance

- meaningful headroom below 1000 lines;
- no function >4000 estimated tokens;
- public acceptance import preserved;
- reports/verdicts unchanged;
- targeted and broad tests pass.

## Part B — Admin near-limit follow-up

Do this after block 05 so these modules can use the settled admin service boundaries.

### B1. `api/routers/admin_controls.py`

Goal: make it a route-composition layer rather than a business-logic container.

Split route groups according to actual use cases in the file, for example maintenance/control, recovery/rerun, worker/process and project actions.

Preserve every path, HTTP method, dependency, status code and response body. Route handlers should delegate to services. Do not move database loops or core mutation rules into new router files.

Tests: keep API tests; add route registration/OpenAPI coverage where needed. A split must not omit any route.

### B2. `services/admin_cross_project_service.py`

Goal: split cross-project read/composition responsibilities while preserving project isolation.

Candidate boundaries:

- project registry/list/summary reads;
- cross-project aggregation;
- per-project status/health mapping;
- delegation to existing filesystem/runtime read services.

Tests must preserve multi-project ordering/filtering, response shape, missing-project behaviour and isolation.

### B3. `services/admin_mutation_service.py`

Goal: separate mutation command families without changing the guarded mutation contract.

Candidate boundaries:

- packet/feature lifecycle actions;
- rerun/recovery actions;
- maintenance/process actions;
- shared validation, audit and result mapping.

All extracted paths must preserve the same authorization, project and state checks as the original service.

Tests must preserve allowed/rejected cases, state transition results, audit/event payloads, invalid request mapping and project isolation.

### B4. `api/routers/admin_control_center.py`

Goal: reduce the router before additional endpoints push it over the hard limit.

Extract route groups aligned with service boundaries established in block 05. Do not duplicate service logic in routers.

Preserve routes, methods, dependencies, OpenAPI-visible metadata where relied on, status codes and response bodies.

Tests: run control-center API tests and compare OpenAPI route set before/after.

## Recommended admin order

1. Finish block 05 hard-limit admin services.
2. Refactor `admin_cross_project_service.py` and `admin_mutation_service.py`.
3. Split the two near-limit routers against the settled service boundaries.
4. Run OpenAPI/admin integration verification.

## Size targets

For every touched file in this block:

- hard requirement: <=1000 lines;
- preferred: <=700-800 lines;
- every function/method <=4000 estimated tokens;
- do not move the problem into one new oversized module.

## Test policy

Allowed test changes:

- update imports/patch targets after extraction;
- add unit tests for new components;
- add compatibility and route-registration tests;
- compare OpenAPI route set.

Forbidden:

- weakening acceptance results;
- removing admin response fields;
- removing project/state protection tests;
- changing state outcomes merely to match refactored code;
- accepting unexplained API schema drift.

## Verification

For acceptance work, run focused acceptance tests and then:

```bash
make lint
make test
```

For admin work, run focused admin tests and then:

```bash
make lint
make test
make docs-check
```

Final programme gate:

```bash
make ci
```

## Coder submission

For each target module report:

- before/after line count;
- extracted responsibility and destination module;
- largest touched function estimated tokens;
- tests modified/added and why;
- public import/API compatibility evidence;
- verification commands/results.
