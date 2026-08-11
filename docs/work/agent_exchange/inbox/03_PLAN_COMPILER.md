# TZ 03_PLAN_COMPILER — Grace Local Adopt plan compiler refactor

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_03_PLANNING_COMPILER.md` — **Part A only**
Dependency: `01_LINT_GUARDRAILS` — ACCEPTED by Architect

## Coder protocol

You are the Coder for this named TZ. Read and execute **only this file**. Do not open or start another inbox task/TZ unless the Architect explicitly names it after ACCEPT.

Before editing anything:

1. Work in `/opt/grace-orchestrator`.
2. Fast-forward sync with GitHub. The checkout must be clean and updated from `origin/main`; use fast-forward-only sync and do not create a merge commit.
3. If the checkout cannot fast-forward cleanly, stop and report the blocker; do not overwrite local work.

After implementation:

1. Run the required verification below.
2. Commit the implementation.
3. Push the commit to GitHub.
4. Create **only** `docs/work/agent_exchange/outbox/03_PLAN_COMPILER_SUBMISSION.md` for the report.
5. Do not create the next task, review file, `state.json`, lock files, orchestration metadata, or any other coordination file.

The submission must contain these exact lines with the real implementation commit SHA:

```text
WEB_ORCH_REPORT: SUBMISSION 03_PLAN_COMPILER
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <commit-sha>
WEB_ORCH_CHECKS: PASS
```

If the Architect later returns REVIEW, read only `docs/work/agent_exchange/inbox/03_PLAN_COMPILER_REVIEW.md`, fix that review, and report only to `docs/work/agent_exchange/outbox/03_PLAN_COMPILER_RESUBMISSION.md`.

## Goal

Refactor `src/grace_control/core/plan_compiler.py` into a bounded public compiler facade plus coherent validation owners, without changing compiler behaviour or the planner/architect packet contract.

Required structural result:

- `plan_compiler.py` must be `<= 1000` physical lines; target `<= 700` and preferably around `500–700`;
- `PlanCompiler.compile_plan()` must be `< 4000` Grace-estimated tokens and target `<= 2500`;
- every extracted function/method must stay `< 4000` estimated tokens, with practical headroom rather than landing just below the cap;
- every new Python module must stay `<= 1000` physical lines, preferably `<= 800`;
- existing public compiler imports remain compatible.

Do not solve this by arbitrary line slicing, code compression, string-concatenation lint evasion, or moving one oversized function into a new near-limit module.

## Owned write scope

Primary source:

- `src/grace_control/core/plan_compiler.py`

Expected new validator modules/package under `src/grace_control/core/`, preferably a coherent package such as:

- `src/grace_control/core/plan_validation/`

Directly affected compiler tests may be changed or added, primarily:

- `tests/grace_control/core/test_plan_compiler.py`

Other tests may be touched only when they directly import compiler internals whose ownership moved, and observable behaviour must remain unchanged.

### Explicitly out of scope for this packet

Do **not** start Part B of source block 03. In particular, do not structurally refactor:

- `src/grace_control/services/feature_planning_service.py`

That will be a separate named TZ after Architect ACCEPT.

Frozen by default:

- `src/grace_control/db/schema.py`
- Alembic migrations
- `src/grace_control/core/contracts.py`
- `src/grace_control/config/settings.py`
- `src/grace_control/core/state_machine.py`
- public API schemas

Do not change these unless an unavoidable, test-backed compatibility reason exists; if so, keep it minimal and explain it in the submission.

## Required responsibility decomposition

Refactor by validation domain, not by line count alone. Suggested ownership follows the source TZ; exact module names may vary if existing conventions demand it.

### 1. Command validation

A coherent command validator may own:

- command segmentation;
- executable discovery checks;
- Python executable/module/script checks;
- bash/dash incompatibility;
- venv/bootstrap command validation;
- unsafe grep / negative-search validation;
- one-liner command syntax validation.

### 2. Scope validation

A coherent scope validator may own:

- scope type and entry validation;
- absolute/parent/import-path checks;
- Python-file expansion limit;
- root/packet frozen-scope overlap;
- scope-vs-acceptance feasibility;
- role/scope consistency when that keeps ownership coherent.

### 3. Evidence validation

A coherent evidence validator may own:

- evidence kind/expectation validation;
- artifact-pattern validation;
- diff evidence constraints;
- evidence/instruction contradiction detection;
- explicit deletion-evidence checks.

### 4. Dependency / DAG validation

A coherent dependency validator may own:

- packet dependency collection;
- DAG issue mapping;
- duplicate/missing/cycle/wave-order/scope-conflict mapping.

Reuse the existing DAG/dependency owner where one already exists; do not fork a second implementation.

### 5. Source-split / import-migration validation

A coherent source-split validator may own:

- source-split intent models/detection;
- keyword/path/import detection;
- repository reference scanning;
- origin-scope/import-migration validation.

## What must remain compatible in `plan_compiler.py`

Keep or re-export as needed:

- `PlanCompiler`;
- `compile_plan`;
- `CompileError`;
- `CompileResult`;
- any other symbol demonstrably imported from `grace_control.core.plan_compiler` by current source/tests.

Callers must not be forced to migrate merely because internals were extracted.

The final `compile_plan()`/compiler path should read as an explicit, ordered coordinator over validation domains rather than own every rule inline.

## Behaviour that must not change

This is a structural refactor, not a compiler redesign. Preserve:

- existing error codes;
- existing warning codes;
- severity;
- field paths and packet/title association;
- error/warning messages where tests or consumers rely on them;
- deterministic validation ordering;
- fail-closed scope policy;
- current packet-contract compatibility;
- legacy verification-list compatibility;
- current `python_file_limit` feature-text detection;
- source-split/import-migration rules;
- shell/environment discovery semantics;
- `conflict_keys` behaviour;
- planner/architect contract shape.

Do not add/remove validation rules merely because extraction makes that tempting.

## Required regression protection

Existing compiler tests remain behavioural contracts and must not be weakened.

At minimum preserve/add explicit coverage proving:

1. empty coder scope remains `E_CODER_EMPTY_SCOPE`;
2. invalid scope type remains fail-closed;
3. root/packet frozen-scope overlaps remain rejected;
4. dependency errors retain current code mapping;
5. source-split origin missing remains detected;
6. import-migration scope completeness remains detected;
7. command interpreter/module/script checks retain semantics;
8. evidence contradiction/deletion rules retain semantics;
9. legacy verification-list compatibility remains intact;
10. current contract `conflict_keys` behaviour remains intact;
11. public imports from `grace_control.core.plan_compiler` remain compatible;
12. validation error/warning ordering remains stable for representative multi-error inputs.

Allowed test edits:

- add focused tests for extracted validators;
- change internal import/monkeypatch targets only where ownership genuinely moved;
- add compatibility-import tests.

Forbidden:

- deleting behavioural assertions;
- changing expected codes/messages/order merely to accommodate drift;
- broad `skip`/`xfail`;
- replacing broad compiler integration coverage with mocks only.

## Lint / structural guardrails

Accepted block 01 semantics are authoritative:

- `GRC005`: violation only when a Python file has `> 1000` physical lines;
- `GRC012`: violation only when `len(function_source) // 4 > 4000`;
- `GRC012` applies to public/private sync/async functions;
- selective `rules_enabled` behaviour must remain intact;
- do not add `GRC005` or `GRC012` allowlist suppressions.

If a textual non-size GraceLint rule produces a genuine false positive solely because code moved, prefer fixing ownership/code naturally. If an allowlist entry is truly unavoidable, it must be narrowly scoped, truthful, and explained; never evade a rule by obscuring normal identifiers with string concatenation or equivalent tricks.

## Required verification

Run the smallest directly affected compiler tests first, then at minimum:

```bash
.venv/bin/python -m pytest tests/grace_control/core/test_plan_compiler.py -q
.venv/bin/python scripts/grace_lint.py src/grace_control/core/plan_compiler.py
make test
make lint
git diff --check
```

Also run targeted GraceLint and `py_compile` on every newly created Python validator module.

Run any directly affected plan-autofix/planning tests that import the compiler facade.

The repository currently has known environment/baseline debt outside this packet, including a `.venv` without Ruff and a stable set of unrelated full-suite failures observed in TZ02. Do not assume a failure is baseline merely from that history: if `make test` or another broad command is non-zero, compare the exact failure-node set against a clean parent baseline using the same environment/arguments and report whether the sets are identical. Do not hide failures and do not claim an individual command passed when it failed.

`WEB_ORCH_CHECKS: PASS` may only mean the TZ-specific/focused implementation is green with any separately proven baseline/environment blockers reported precisely.

## Acceptance criteria

Architect will inspect the actual implementation commit and diff. ACCEPT requires all of the following:

1. `plan_compiler.py <= 1000` physical lines with practical headroom, target `<= 700`.
2. `compile_plan()` below 4000 estimated tokens and target `<= 2500`.
3. No extracted function/method exceeds 4000 estimated tokens; large orchestration functions have practical headroom.
4. No new Python module exceeds 1000 lines; avoid near-limit parking where a coherent split exists.
5. Validation is decomposed by coherent responsibility, not arbitrary slicing/compression.
6. Existing dedicated dependency/business-rule owners remain authoritative; no duplicate rule implementation.
7. Public compiler imports remain compatible.
8. Error/warning codes, messages/paths where contractual, severity, ordering, scope policy, source-split, command, evidence, dependency and `conflict_keys` semantics remain unchanged.
9. Behavioural tests are not weakened.
10. Required high-risk regression areas remain covered.
11. No `GRC005/GRC012` suppression is added.
12. Diff contains no Part-B feature-planning refactor and no unrelated product/API/DB/config/state-machine change.
13. Focused compiler tests and targeted GraceLint checks pass.
14. Any broad-suite non-zero result is proven against the clean parent baseline rather than merely labelled pre-existing.

## Submission content

Keep `03_PLAN_COMPILER_SUBMISSION.md` concise but include:

- exact implementation commit SHA;
- files created/modified;
- before/after line count for `plan_compiler.py`;
- before/after `len(source) // 4` estimate for `compile_plan()`;
- largest function(s) in every touched/new compiler/validator module;
- responsibility -> new owner mapping;
- existing services/helpers reused rather than copied;
- compatibility facade/re-exports retained;
- tests updated/added and why;
- confirmation no behavioural assertion was weakened;
- confirmation error/warning codes and ordering remain stable;
- exact verification commands/results;
- any baseline/environment failures with evidence of parent comparison;
- any known follow-up debt, without starting another named TZ.
