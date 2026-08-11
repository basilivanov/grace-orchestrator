# TZ — Grace Local Adopt: structural refactor master

Status: READY FOR CODER
Type: refactor-only / architecture debt removal
Repository: `grace-orchestrator`
Scope root: `src/grace_control/`, related tests, GraceLint metadata

## 1. Goal

Bring the current Grace codebase back under the Local Adopt structural limits and create enough headroom that normal feature work does not immediately violate them again.

Hard limits:

- Python source file: **<= 1000 physical lines** (`GRC005`).
- Function / async function: **<= 4000 estimated tokens** (`GRC012`, current Grace estimate = source characters / 4).
- `GRC012` applies to **all functions**, including names beginning with `_`.

Refactor targets must not merely land at 999 lines / 3999 tokens. For files touched by this programme, target practical headroom:

- preferred module size: <= 800 lines;
- preferred large orchestration function: <= 2500-3000 estimated tokens;
- a thin compatibility facade may be much smaller.

The preferred sizes are design targets, not new hard lint rules unless a dedicated follow-up explicitly adds such rules.

## 2. Non-goals

This programme MUST NOT intentionally change:

- packet lifecycle semantics;
- state-machine transitions;
- executor selection / recovery ladder behaviour;
- acceptance semantics;
- merge semantics;
- public HTTP routes, methods, response shapes or status codes;
- persisted DB schema;
- artifact/evidence directory semantics;
- public Python import paths relied on by existing code/tests;
- configuration keys or defaults;
- current planner/architect packet contract.

No unrelated cleanup, style rewrite, naming campaign, dependency upgrade, formatting sweep or product feature is part of this work.

## 3. Behaviour-preservation rule

Treat existing behaviour and existing regression tests as the contract.

When moving code:

1. Move one coherent responsibility at a time.
2. Preserve public entry points.
3. Prefer delegation from the old module over a flag-day import migration.
4. If an existing import path is used outside the module, keep a compatibility re-export/facade unless all references are intentionally migrated in the same bounded packet.
5. Do not duplicate business logic between old and new modules.
6. Do not use allowlist entries to make `GRC005` / `GRC012` pass.
7. Do not compress code onto fewer physical lines to beat the file limit.

## 4. Tests — global policy

### Existing tests

Existing tests MUST NOT be weakened just because implementation code moved.

Allowed test changes:

- update imports when a test intentionally targets a newly extracted internal unit;
- add focused unit tests for extracted components;
- add compatibility-import tests;
- replace brittle monkeypatch targets only when the target moved and the observable behaviour remains identical;
- update fixtures that instantiate an internal class whose construction was intentionally split.

Forbidden test changes:

- deleting failing behavioural assertions;
- changing expected status/state/result merely to match a refactor regression;
- broad `xfail`/`skip` additions;
- lowering lint limits;
- adding `GRC005` or `GRC012` allowlist suppressions;
- replacing integration coverage with mocks only.

### Required verification after every logical block

At minimum run the directly affected test module(s), then:

```bash
make lint
make test
```

At final integration run:

```bash
make ci
```

If generated docs drift only because imports/internal implementation changed, that is a failure: refactor-only work should not change public OpenAPI. If code generation legitimately rewrites formatting without semantic API drift, include and explain the generated diff.

## 5. Source-of-truth target groups

### Hard-limit violations — must be refactored

1. `src/grace_control/adapters/packet_executor.py`
2. `src/grace_control/core/plan_compiler.py`
3. `src/grace_control/services/admin_aggregation_service.py`
4. `src/grace_control/services/admin_control_center.py`
5. `src/grace_control/services/feature_planning_service.py`
6. `src/grace_control/services/merge_service.py`

### Near-limit modules — refactor before further feature growth

1. `src/grace_control/api/routers/admin_controls.py`
2. `src/grace_control/core/acceptance_pipeline.py`
3. `src/grace_control/services/admin_cross_project_service.py`
4. `src/grace_control/services/admin_mutation_service.py`
5. `src/grace_control/api/routers/admin_control_center.py`

Do not expand the programme to every 300+ line module. The list above is intentionally bounded.

## 6. Logical work blocks

Detailed specifications live in sibling documents:

- `TZ_GRACE_LOCAL_ADOPT_REFACTOR_00_INDEX.md`
- `TZ_GRACE_LOCAL_ADOPT_REFACTOR_01_LINT_GUARDRAILS.md`
- `TZ_GRACE_LOCAL_ADOPT_REFACTOR_02_PACKET_EXECUTION.md`
- `TZ_GRACE_LOCAL_ADOPT_REFACTOR_03_PLANNING_COMPILER.md`
- `TZ_GRACE_LOCAL_ADOPT_REFACTOR_04_MERGE_PIPELINE.md`
- `TZ_GRACE_LOCAL_ADOPT_REFACTOR_05_ADMIN_CONTROL_PLANE.md`
- `TZ_GRACE_LOCAL_ADOPT_REFACTOR_06_NEAR_LIMIT_FOLLOWUP.md`

The split is intentional: no coder packet should own the entire programme at once.

## 7. Recommended execution order

### Wave 0 — guardrail correctness

Do block 01 first.

Reason: before refactoring, GraceLint must correctly detect oversized private helpers; otherwise the programme can finish with hidden `GRC012` violations.

### Wave 1 — hard-limit domains

Blocks 02, 03, 04 and 05 may be worked in parallel **only when their write scopes do not overlap**.

Important overlap rules:

- block 02 owns `packet_executor.py` and newly extracted execution modules;
- block 03 owns `plan_compiler.py`, `feature_planning_service.py` and newly extracted planning/validation modules;
- block 04 owns `merge_service.py` and newly extracted merge modules;
- block 05 owns hard-limit admin read/control modules;
- shared generic modules such as `db/schema.py`, `config/settings.py`, `core/contracts.py` are frozen unless a specific packet proves they must change.

### Wave 2 — near-limit follow-up

Do block 06 after the corresponding hard-limit extractions settle. `acceptance_pipeline.py` can normally be handled independently from the admin near-limit files.

### Wave 3 — integration

Run full lint/tests/CI and verify public surfaces did not drift.

## 8. Refactor design rules

### Prefer responsibility extraction, not arbitrary line slicing

Bad split:

- `packet_executor_part1.py`
- `packet_executor_part2.py`

Good split:

- facade/coordinator;
- preflight/runtime preparation;
- observability/artifact helpers;
- post-run/acceptance routing;
- existing dedicated rerun/persistence services reused rather than copied.

### Keep one owner per business rule

If a rule already lives in a dedicated service, call it. Do not create a second implementation simply to reduce lines in the original file.

### Avoid circular dependency fixes by service-locator hacks

Do not solve import cycles with broad dynamic imports everywhere. Local imports are acceptable at existing cycle boundaries, but new modules should be layered so that lower-level helpers do not import the facade that owns them.

### Preserve data contracts

DTO keys, event names, artifact names, reason codes, failure codes, state values and persisted JSON keys are behaviour for this refactor and must remain stable unless a test demonstrates they were never externally observable.

## 9. Acceptance criteria — programme

The programme is complete only when all are true:

1. Every Python file in the hard-limit and near-limit target set is <= 1000 lines.
2. Every function/async function in the touched target set, including private functions/methods, is <= 4000 estimated tokens.
3. `GRC012` itself checks private functions for size while continuing to exempt them from public FUNCTION_CONTRACT requirements.
4. No `GRC005`/`GRC012` allowlist exemptions are introduced.
5. Stale lint allowlist metadata for `packet_executor.py` is removed or corrected.
6. Existing public Python imports continue to work or are migrated with compatibility coverage.
7. HTTP route set and response contracts remain unchanged.
8. DB migrations are not required.
9. Existing behavioural tests remain green.
10. New tests cover extracted boundaries where regressions could otherwise hide.
11. `make lint` passes.
12. `make test` passes.
13. `make ci` passes.

## 10. Coder submission requirements

Each coder submission must include:

- files created / moved / modified;
- old responsibility -> new owner mapping;
- tests changed and why;
- confirmation that no behavioural assertions were weakened;
- before/after line count of each target source file;
- largest function(s) in touched modules using the same `len(source) // 4` estimate as GraceLint;
- exact verification commands run;
- any compatibility facade/re-export retained and why;
- any known follow-up debt left for the next logical block.
