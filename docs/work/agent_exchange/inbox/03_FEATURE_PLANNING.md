# TZ 03_FEATURE_PLANNING — Grace Local Adopt feature planning refactor

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_03_PLANNING_COMPILER.md` — **Part B only**
Dependency: `03_PLAN_COMPILER` — ACCEPTED by Architect

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
4. Create **only** `docs/work/agent_exchange/outbox/03_FEATURE_PLANNING_SUBMISSION.md` for the report.
5. Do not create the next task, review file, `state.json`, lock files, orchestration metadata, or any other coordination file.

The submission must contain these exact lines with the real implementation commit SHA:

```text
WEB_ORCH_REPORT: SUBMISSION 03_FEATURE_PLANNING
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <commit-sha>
WEB_ORCH_CHECKS: PASS
```

If the Architect later returns REVIEW, read only `docs/work/agent_exchange/inbox/03_FEATURE_PLANNING_REVIEW.md`, fix that review, and report only to `docs/work/agent_exchange/outbox/03_FEATURE_PLANNING_RESUBMISSION.md`.

## Goal

Refactor `src/grace_control/services/feature_planning_service.py` into a bounded public orchestration facade plus coherent planning-stage owners, without changing planning behaviour, persisted state/artifact/event contracts, target-repository mutation safety, or the planner/architect packet contract.

Required structural result:

- `feature_planning_service.py` must be `<= 1000` physical lines; target practical headroom of `<= 800`, preferably around `600–800` or smaller if it remains a clear facade;
- every touched/new function or async function must stay `< 4000` Grace-estimated tokens (`len(source) // 4`), with large orchestration functions preferably `<= 2500–3000`;
- every new Python module must stay `<= 1000` physical lines, preferably `<= 800`;
- `FeaturePlanningService` remains the stable public orchestration entry point;
- Part A compiler internals remain behind `grace_control.core.plan_compiler` and are not coupled into planning via private `plan_validation.*` imports.

Do not solve this by arbitrary line slicing, code compression, string-concatenation lint evasion, or moving one oversized function into a new near-limit module.

## Owned write scope

Primary source:

- `src/grace_control/services/feature_planning_service.py`

Expected new planning-focused modules under `src/grace_control/services/`, for example coherent owners for:

- planning workspace / mutation guard;
- context-builder stage;
- architect stage;
- shared planning-run persistence / observability where actual duplication justifies it.

Directly affected tests may be changed or added, especially existing feature-planning, planning-store, context-safety, architect/context-run, and plan-autofix tests whose observable behaviour depends on this service.

Optional only if a genuine moved-code textual false positive cannot be fixed naturally:

- `.grace/lint_allowlist.yaml`

Any new allowlist entry must be narrow, truthful, non-size, and explained. Never add `GRC005` or `GRC012` suppression and never obscure normal identifiers to evade GraceLint.

### Explicitly out of scope

Do not reopen accepted Part A unless an unavoidable compatibility defect is proven. In particular, do not structurally modify:

- `src/grace_control/core/plan_compiler.py`
- `src/grace_control/core/plan_validation/`

Feature planning must continue to depend on the preserved public compiler facade.

Also do not start blocks 04, 05, or 06.

Frozen by default:

- `src/grace_control/db/schema.py`
- Alembic migrations
- `src/grace_control/core/contracts.py`
- `src/grace_control/config/settings.py`
- `src/grace_control/core/state_machine.py`
- public API schemas

Do not change these unless an unavoidable, test-backed compatibility reason exists; if so, keep it minimal and explain it in the submission.

## Required responsibility decomposition

Refactor by responsibility, not by line count alone.

### 1. Planning workspace / mutation guard

A coherent owner may contain filesystem/git safety orchestration for:

- disposable planning workspace clone/copy creation;
- workspace cleanup;
- pre/post target-repository git snapshots;
- mutation description and guard checks.

The existing safety rule is invariant: context-builder and architect planning work must not mutate the target repository.

### 2. Context-builder stage

A coherent owner may contain:

- planning-run setup for context collection;
- context-builder invocation;
- stdout/stderr/artifact/event handling;
- mutation checks around the disposable planning workspace;
- result mapping and persistence.

### 3. Architect stage

A coherent owner may contain:

- architect invocation;
- output capture/parsing;
- normalization through the existing planning contract;
- compiler/autofix coordination where architect-specific;
- stage persistence/events.

### 4. Shared planning-run persistence / observability

Extract a small shared helper only where repeated lifecycle bookkeeping actually exists, such as:

- run start/done/error persistence;
- stdout/stderr paths;
- common event/artifact emission.

Do not introduce a generic framework solely to reduce line count.

## Public and behavioural compatibility

Retain or re-export as needed from `feature_planning_service.py`:

- `FeaturePlanningService`;
- `normalize_architect_plan`;
- current public service methods called by routers/tests;
- top-level planning exceptions/classes demonstrably imported by current source/tests;
- existing monkeypatch points where tests/callers rely on module-level dependencies, unless tests are minimally retargeted to an intentionally extracted internal owner without changing observable behaviour.

Preserve exactly unless existing tests prove otherwise:

- planning run statuses and state transitions;
- planning run start/error/done persistence;
- stdout/stderr and artifact/log paths;
- context-builder and architect event names/order where observable;
- plan JSON shape and normalization semantics;
- `normalize_architect_plan(..., require_current_contract=True)` behaviour;
- missing `conflict_keys` rejection for fresh coder packets;
- legacy/manual normalization compatibility;
- target repository cleanliness and mutation-guard failure behaviour;
- compiler result persistence/handling and autofix flow;
- existing public method signatures and return shapes;
- configuration keys/defaults.

Part B must call `grace_control.core.plan_compiler` through its public facade. Do not import private `grace_control.core.plan_validation.*` internals.

## Regression protection

Existing feature-planning behavioural/integration tests remain the contract and must not be weakened.

At minimum preserve or add coverage proving:

1. context builder cannot mutate the target repository;
2. architect cannot leave target/planning-workspace mutation unreported according to the existing contract;
3. `normalize_architect_plan(..., require_current_contract=True)` remains unchanged;
4. missing `conflict_keys` for fresh coder packets remains rejected;
5. legacy/manual normalization compatibility remains;
6. planning run start/error/done persistence remains;
7. compiler result is persisted/handled exactly as before;
8. stdout/stderr paths and planning artifacts remain stable;
9. context-builder/architect event names and terminal statuses remain stable;
10. current public imports/method calls remain compatible.

Allowed test edits:

- patch a new internal service boundary where ownership genuinely moved;
- add focused workspace/mutation-guard or stage-service tests;
- add compatibility-import tests;
- update an internal fixture only when construction was intentionally split.

Forbidden:

- deleting behavioural assertions;
- changing expected status/state/event/artifact/result merely to accommodate drift;
- broad `skip`/`xfail` additions;
- replacing integration coverage with mocks only.

## Lint / structural guardrails

Accepted block 01 semantics are authoritative:

- `GRC005`: violation only when a Python file has `> 1000` physical lines;
- `GRC012`: violation only when `len(function_source) // 4 > 4000`;
- `GRC012` applies to public/private sync/async functions;
- selective `rules_enabled` behaviour remains intact;
- no `GRC005`/`GRC012` allowlist suppressions.

## Required verification

Run the smallest directly affected feature-planning tests first. At minimum run the relevant existing modules covering feature planning and persistence/safety; include exact commands in the submission. The verification set must include:

```bash
.venv/bin/python -m pytest tests/grace_control/services/test_feature_planning_service.py -q
.venv/bin/python -m pytest tests/grace_control/services/test_feature_planning_store.py -q
.venv/bin/python -m pytest tests/grace_control/services/test_context_builder_safety.py -q
.venv/bin/python -m pytest tests/grace_control/services/test_plan_autofix.py -q
make test
make lint
git diff --check
```

If one of these exact test files is absent at current `main`, report that fact and run the closest current owner test instead; do not invent a replacement silently.

Also run:

- `py_compile` on `feature_planning_service.py` and every new Python planning module;
- targeted `scripts/grace_lint.py` on `feature_planning_service.py` and every new Python planning module;
- any additional tests that import/patch the moved planning symbols or exercise architect/context run persistence.

The repository has known baseline/environment debt outside this packet, including a `.venv` without Ruff and a stable unrelated broad-suite failure set. Do not assume failures are baseline from history. If any required broad or directly affected command is non-zero, compare the exact failure-node set against a clean parent baseline using the same environment and exact arguments. Report whether the sets are identical; any new failure attributable to this packet is a blocker.

Do not claim an individual command passed when it failed. `WEB_ORCH_CHECKS: PASS` may only mean the TZ-specific implementation is green with any separately proven baseline/environment blockers reported precisely.

## Acceptance criteria

Architect will inspect the actual implementation commit and diff. ACCEPT requires all of the following:

1. `feature_planning_service.py <= 1000` physical lines with practical headroom, target `<= 800`.
2. No touched function/async function exceeds 4000 estimated tokens; large orchestration functions have practical headroom.
3. No new Python module exceeds 1000 lines; avoid near-limit parking where a coherent split exists.
4. Responsibilities are extracted coherently by planning stage/safety ownership, not arbitrary slicing/compression.
5. `FeaturePlanningService`, `normalize_architect_plan`, and other demonstrated public surfaces remain compatible.
6. Target-repository mutation safety is unchanged and remains fail-closed according to existing behaviour.
7. Planning run status/state, event, artifact/log path, plan JSON, normalization, compiler/autofix, and persistence semantics remain unchanged.
8. Feature planning depends only on the public `grace_control.core.plan_compiler` boundary, not private `plan_validation.*` internals.
9. Existing behavioural tests are not weakened.
10. Directly affected feature-planning/persistence/safety tests pass or any non-zero set is proven identical to clean parent baseline.
11. Targeted GraceLint and `py_compile` pass for every touched/new planning source file.
12. No `GRC005/GRC012` suppression or lint-evasion construction is introduced.
13. Diff contains no Part-A redesign, block 04/05/06 work, or unrelated product/API/DB/config/state-machine change.
14. Any broad-suite non-zero result is proven against the clean parent baseline rather than merely labelled pre-existing.

## Submission content

Keep `03_FEATURE_PLANNING_SUBMISSION.md` concise but include:

- exact implementation commit SHA;
- files created/modified;
- before/after physical line count for `feature_planning_service.py`;
- largest function(s) before/after using `len(source) // 4`;
- largest function in every touched/new planning module;
- responsibility -> new owner mapping;
- existing services/helpers reused rather than copied;
- public facade/re-exports and patch points retained or intentionally retargeted;
- tests changed/added and why;
- confirmation no behavioural assertion was weakened;
- confirmation planning state/status/event/artifact/normalization/compiler contracts remain stable;
- exact verification commands/results;
- any baseline/environment failures with clean-parent comparison evidence;
- any narrow non-size allowlist change and rationale;
- any known follow-up debt, without starting another named TZ.
