# TZ — Grace Local Adopt refactor / 03 Planning + compiler

Status: READY FOR CODER
Parent: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Priority: P0
Dependency: block 01

Primary targets:

- `src/grace_control/core/plan_compiler.py`
- `src/grace_control/services/feature_planning_service.py`

This document intentionally contains two related but separately packetable sub-blocks.

---

# Part A — `plan_compiler.py`

## A1. Problem

`plan_compiler.py` exceeds the 1000-line Local Adopt limit and `PlanCompiler.compile_plan()` acts as a broad validator coordinator while the same module also owns many independent validation domains.

Current responsibilities include, among others:

- dependency/DAG validation;
- source-split/refactor intent detection;
- repository reference scanning;
- shell/command segmentation;
- Python executable/module/script checks;
- venv/bootstrap command validation;
- packet scope validation;
- scope/frozen-scope validation;
- feature-declared Python-file scope limit;
- scope-vs-acceptance checks;
- evidence validation;
- evidence/instruction contradiction checks;
- role/scope validation.

The correct refactor is a validator decomposition with `PlanCompiler` retained as the public facade.

## A2. Goal

After refactor:

- `core/plan_compiler.py` <=1000 lines, preferred <=500-700;
- `compile_plan()` is a readable coordinator;
- validation domains have explicit owners;
- existing error/warning codes, field paths, messages where tests rely on them, and validation order remain stable;
- public imports stay compatible.

## A3. Preferred module structure

Keep:

- `grace_control.core.plan_compiler.PlanCompiler`
- `grace_control.core.plan_compiler.compile_plan`
- `CompileError`, `CompileResult` compatibility unless moving them is demonstrably internal-only.

Create a validation package or equivalent coherent modules, for example:

```text
src/grace_control/core/plan_validation/
    __init__.py
    commands.py
    scope.py
    evidence.py
    dependencies.py
    source_split.py
```

Names may differ, but responsibilities must not be grouped arbitrarily by line count.

### `commands.py`

Candidate ownership:

- command segmentation;
- executable discovery checks;
- Python module/script checks;
- bash/dash incompatibility;
- venv command checks;
- unsafe grep / negative search validation;
- one-liner command syntax validation.

### `scope.py`

Candidate ownership:

- scope type/entry validation;
- absolute/parent/import-path checks;
- Python-file expansion limit;
- frozen-scope overlap;
- scope-vs-acceptance feasibility;
- role/scope consistency if that keeps ownership clearer.

### `evidence.py`

Candidate ownership:

- evidence kind/expectation validation;
- artifact pattern validation;
- diff evidence constraints;
- evidence/instruction contradiction detection;
- explicit deletion evidence checks.

### `dependencies.py`

Candidate ownership:

- packet dependency collection;
- DAG validation result mapping;
- duplicate/missing/cycle/wave-order/scope-conflict issue mapping.

### `source_split.py`

Candidate ownership:

- source-split intent models;
- keyword/path/import detection;
- repo reference scanning;
- origin-scope/import-migration validation.

## A4. Preserve validation semantics

This is not a compiler redesign.

Preserve:

- existing error codes;
- existing warning codes;
- error/warning severity;
- packet title/field path association;
- fail-closed scope policy;
- current packet contract compatibility;
- current handling of legacy verification lists;
- current `python_file_limit` feature-text detection;
- source split/import migration rules;
- current shell/environment discovery semantics;
- deterministic validation ordering where tests assert list order.

If extracting validators changes ordering, explicitly preserve the old order in the facade.

## A5. Public/import compatibility

Existing imports from `grace_control.core.plan_compiler` should continue to work.

The public facade may re-export implementations from new modules, but callers should not require migration merely because internals were split.

Do not rename current public error codes as part of this work.

## A6. Tests — do we change them?

**Yes: keep current compiler tests and add focused validator tests.**

Primary regression test:

- `tests/grace_control/core/test_plan_compiler.py`

Also inspect other tests importing compiler symbols or asserting compiler error codes.

Required policy:

- existing end-to-end compiler tests remain green;
- do not delete broad tests just because focused validator tests are added;
- extracted validators may receive new unit tests for edge cases;
- add compatibility-import coverage if models/functions are moved internally.

Required high-risk regression areas:

1. empty coder scope remains `E_CODER_EMPTY_SCOPE`;
2. invalid scope type remains fail-closed;
3. root/packet frozen-scope overlaps remain rejected;
4. dependency errors retain current code mapping;
5. source-split origin missing remains detected;
6. import migration scope completeness remains detected;
7. command interpreter/module/script checks retain semantics;
8. evidence contradiction/deletion rules retain semantics;
9. legacy verification list compatibility remains intact;
10. current contract `conflict_keys` behaviour remains intact.

## A7. Verification

At minimum:

```bash
.venv/bin/python -m pytest tests/grace_control/core/test_plan_compiler.py -q
make lint
```

Then run any additional compiler/plan-autofix/feature-planning tests that import the facade.

## A8. Acceptance

- `plan_compiler.py` <=1000 lines, preferred <=700;
- `PlanCompiler.compile_plan()` <4000 estimated tokens, preferred <=2500;
- every extracted function <4000 estimated tokens;
- no public compiler import break;
- no validation-code drift;
- compiler tests pass.

---

# Part B — `feature_planning_service.py`

## B1. Problem

`feature_planning_service.py` exceeds the file limit and combines multiple planning lifecycle stages plus workspace safety, persistence and orchestration.

Current responsibilities include:

- architect plan normalization;
- planning workspace creation/removal;
- target repository mutation snapshots;
- context-builder run lifecycle;
- architect run lifecycle;
- planning run logging/artifacts/events;
- plan compilation/autofix flow;
- plan persistence/materialisation preparation;
- feature planning state reads.

## B2. Goal

Keep `FeaturePlanningService` as a stable public orchestration facade while extracting stage-specific services/helpers.

Target:

- original module <=1000 lines, preferred <=600-800;
- stage functions are bounded;
- planning behaviour, artifacts and run state remain unchanged.

## B3. Preferred extraction boundaries

### Planning workspace / mutation guard

Move cohesive filesystem/git safety helpers:

- planning workspace clone/copy;
- cleanup;
- pre/post git snapshots;
- mutation description/guard logic.

Suggested owner:

- `services/feature_planning_workspace.py`, or equivalent.

Do not change the safety rule: context-builder/architect planning work must not mutate the target repository.

### Context-builder stage

Move orchestration specific to context collection:

- planning-run setup;
- context-builder invocation;
- stage logging/artifacts/events;
- mutation check around the disposable planning workspace;
- result mapping/persistence.

Suggested owner:

- `services/feature_planning_context_service.py`.

### Architect stage

Move architect-specific lifecycle:

- architect execution;
- output capture/parsing;
- normalization through the existing contract;
- compile/autofix coordination where architect-specific;
- stage persistence/events.

Suggested owner:

- `services/feature_planning_architect_service.py`.

### Shared planning-run persistence/observability

If enough repeated code exists, extract a small shared helper for:

- run start/finish/error bookkeeping;
- stdout/stderr paths;
- common event/artifact emission.

Do not introduce a generic framework just to reduce line count.

## B4. Keep stable public surfaces

Prefer retaining in `feature_planning_service.py`:

- `FeaturePlanningService`;
- `normalize_architect_plan` import compatibility;
- current public service methods called by routers/tests;
- top-level error classes used externally.

Internal helpers may delegate to new modules.

## B5. Tests — do we change them?

**Yes, minimally and intentionally.**

Keep all existing feature-planning behaviour tests.

Allowed:

- patch new internal service boundaries instead of old private helpers;
- add unit tests for workspace/mutation guard extraction;
- add stage-service tests;
- add compatibility import tests.

Do not change expected:

- planning run statuses;
- artifact/log paths;
- architect/context event names;
- plan JSON shape;
- current contract normalization semantics;
- mutation-guard failure behaviour;
- target repo cleanliness expectations.

Required regression coverage:

1. context builder cannot mutate target repo;
2. architect cannot leave planning workspace mutation unreported;
3. `normalize_architect_plan(..., require_current_contract=True)` behaviour is unchanged;
4. missing `conflict_keys` for fresh coder packets remains rejected;
5. legacy/manual normalization compatibility remains;
6. planning run start/error/done persistence remains;
7. compiler result is persisted/handled as before.

## B6. Interaction with Part A

Part B should call `grace_control.core.plan_compiler` through its preserved public facade.

Do not make feature planning import private `plan_validation.*` internals unless there is a strong ownership reason.

This keeps compiler and planning refactors independently testable and reduces packet conflicts.

## B7. Verification

Run dedicated feature planning tests, then:

```bash
make lint
make test
```

## B8. Acceptance

- `feature_planning_service.py` <=1000 lines, preferred <=800;
- no touched function >4000 estimated tokens;
- target repository mutation guard unchanged;
- planning stage state/artifact/event behaviour unchanged;
- compiler facade remains the dependency boundary;
- feature planning tests pass.

---

# Coder submission for block 03

For each Part A/B packet report separately:

- before/after file lines;
- largest function before/after estimated tokens;
- extracted module responsibility map;
- public facade/re-exports retained;
- tests changed and why;
- validation/error/event contracts confirmed unchanged;
- exact commands run.
