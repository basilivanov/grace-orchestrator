# TZ 02_PACKET_EXECUTION — Grace Local Adopt packet execution refactor

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_02_PACKET_EXECUTION.md`
Dependency: `01_LINT_GUARDRAILS` — ACCEPTED by Architect

## Coder protocol

You are the Coder for this named TZ. Read and execute **only this file**. Do not open or start any other inbox task/TZ unless the Architect explicitly names it after ACCEPT.

Before editing anything:

1. Work in `/opt/grace-orchestrator`.
2. Fast-forward sync with GitHub. The checkout must be clean and updated from `origin/main`; use a fast-forward-only sync and do not create a merge commit.
3. If the checkout cannot fast-forward cleanly, stop and report the blocker; do not overwrite local work.

After implementation:

1. Run the required verification below.
2. Commit the implementation.
3. Push the commit to GitHub.
4. Create **only** `docs/work/agent_exchange/outbox/02_PACKET_EXECUTION_SUBMISSION.md` for the report.
5. Do not create the next task, review file, `state.json`, lock files, orchestration metadata, or any other coordination file.

The submission must contain these exact lines with the real implementation commit SHA:

```text
WEB_ORCH_REPORT: SUBMISSION 02_PACKET_EXECUTION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <commit-sha>
WEB_ORCH_CHECKS: PASS
```

If the Architect later returns REVIEW, read only `docs/work/agent_exchange/inbox/02_PACKET_EXECUTION_REVIEW.md`, fix that review, and report only to `docs/work/agent_exchange/outbox/02_PACKET_EXECUTION_RESUBMISSION.md`.

## Goal

Refactor `src/grace_control/adapters/packet_executor.py` back into a thin execution facade/coordinator without changing packet execution behaviour.

Required structural result:

- `packet_executor.py` must be `<= 1000` physical lines; target `<= 800` where practical;
- `PacketExecutionAdapter.execute()` must be `< 4000` Grace-estimated tokens and preferably `<= 2500–3000`;
- every extracted function/method must stay `< 4000` estimated tokens;
- every new Python module must stay `<= 1000` physical lines;
- public `PacketExecutionAdapter` and `ExecutionResult` import surfaces remain compatible.

Do not solve this by arbitrary line slicing or code compression.

## Owned write scope

Primary source:

- `src/grace_control/adapters/packet_executor.py`

New execution-focused modules may be added under existing `src/grace_control/services/` or `src/grace_control/adapters/` conventions when they own coherent responsibilities.

Directly affected packet-execution/runtime tests may be changed or added.

Frozen by default:

- `src/grace_control/db/schema.py`
- Alembic migrations
- `src/grace_control/core/contracts.py`
- `src/grace_control/config/settings.py`
- `src/grace_control/core/state_machine.py`
- public API schemas

Do not change these unless an unavoidable test-backed reason exists; if so, keep the change minimal and explain it in the submission.

## Required extraction shape

Refactor by responsibility, not by file size alone. Use existing dedicated services instead of copying business logic.

### 1. Preflight / runtime preparation

Extract cohesive orchestration for the appropriate subset of:

- runtime contract creation;
- runtime selftest and result mapping;
- selftest artifact/event emission orchestration;
- effective target/worktree resolution needed before execution;
- materialisation/context-required pre-run gating.

Reuse existing components such as `AgentRuntimeContractBuilder`, `AgentRuntimeSelftest`, and `PacketMaterializer`.

### 2. Rerun dispatch

The adapter should decide that the rerun path is needed and delegate to existing rerun owners.

Do not duplicate:

- prior terminal-context loading;
- rerun pipeline execution;
- rerun result persistence;
- one-shot rerun semantics.

### 3. Post-execution worktree / scope stage

Extract cohesive orchestration for:

- worktree/result inspection;
- existing agent commit detection;
- no-change handling;
- runtime scope enforcement;
- immediate diagnostic/result mapping after backend execution.

Reuse existing Git/worktree/scope services.

### 4. Acceptance / final routing

Keep `acceptance_pipeline`, verifier/reviewer logic, persistence, and routing rules authoritative.

The adapter may delegate to extracted orchestration, but do not create a second acceptance implementation.

### 5. Observability

Extract stateless/cohesive observability helpers if that materially reduces the adapter.

Preserve exactly:

- event names;
- stage/component/status values;
- artifact names, paths, and kinds;
- trace/run/packet associations;
- payload keys consumed by tests/UI/admin surfaces.

## What must remain in `PacketExecutionAdapter`

Keep the public facade responsibilities:

- constructor compatibility;
- `execute(packet_id, worker_id, claim_data=None)`;
- high-level stage ordering;
- dependency wiring genuinely owned by the facade;
- compatibility helpers/re-exports required by existing callers.

The final `execute()` should read as a high-level pipeline, approximately:

1. initialise run/observability;
2. preflight;
3. materialise/prepare;
4. rerun branch or backend execution;
5. inspect/enforce;
6. acceptance;
7. final route/persist;
8. fail safely.

Exact internal names are implementation choice.

## Behaviour that must not change

Preserve all existing execution semantics, including:

- safety-gate ordering;
- runtime selftest defaults and failure behaviour;
- target repository resolution;
- worktree/branch naming;
- context skip/required semantics;
- rerun one-shot behaviour;
- `agent_runtime_fail_on_no_changes` behaviour;
- scope enforcement;
- acceptance profile handling;
- verifier/reviewer routing;
- commit SHA capture;
- error propagation and terminal run status;
- result/evidence/diagnostics JSON keys;
- observability event/artifact names and payload shapes.

No DB schema, HTTP contract, configuration-key/default, planner contract, merge semantics, or packet state-machine changes belong in this TZ.

## Existing owners to inspect and reuse

Before creating new logic, reuse existing components where applicable:

- `AgentRuntimeContractBuilder`
- `AgentRuntimeSelftest`
- `PacketMaterializer`
- `WorktreeInspector`
- `AgentCommitService`
- `WorktreeCleanupService`
- `RuntimeArtifactStore`
- `RuntimeEventLogger`
- `RuntimeScopeEnforcer`
- rerun context/pipeline/result persistence services
- `acceptance_pipeline`
- evidence verifier/reviewer gate
- packet control/rerun marker service

Do not create parallel implementations with slightly different semantics.

## Tests

Existing execution tests are behavioural contracts and must not be weakened.

Find and preserve coverage for at least:

- normal packet execution;
- claim-based execution;
- selftest pass/fail;
- context-required rejection;
- rerun branches;
- no-change behaviour;
- scope violations;
- acceptance accept/reject;
- existing agent commit detection;
- persistence/result JSON;
- observability events/artifacts.

Allowed test changes:

- update monkeypatch/import targets when internals move;
- add focused unit tests for extracted coordinators/helpers;
- add compatibility-import coverage for `PacketExecutionAdapter` and `ExecutionResult` from the old module path;
- add stage-order coverage if useful.

Required protection coverage must demonstrate:

1. runtime selftest failure rejects before backend execution;
2. rerun path does not fall through into normal backend execution;
3. acceptance accept/reject persists the same domain status/reason shape;
4. no-change feature-flag behaviour is unchanged;
5. major observability event names remain unchanged;
6. an agent-created commit is still recognised when the worktree is clean but HEAD differs from workspace base.

Do not delete assertions, change expected lifecycle/result values to fit regressions, or add broad skips/xfails.

## Lint / structural guardrails

The accepted block 01 semantics are authoritative:

- `GRC005`: violation only when a Python file has `> 1000` physical lines;
- `GRC012`: violation only when `len(function_source) // 4 > 4000`;
- `GRC012` applies to public/private sync/async functions;
- selective `rules_enabled` behaviour must remain intact;
- do not add `GRC005` or `GRC012` allowlist suppressions.

The preferred `<=800` file and `<=2500–3000` large-function targets are engineering headroom goals, not new lint codes.

## Required verification

Run the smallest directly affected packet-execution/runtime tests first, then at minimum:

```bash
.venv/bin/python -m pytest tests/grace_control/ -q
.venv/bin/python scripts/grace_lint.py src/grace_control/adapters/packet_executor.py
make lint
git diff --check
```

Also lint any newly created Python modules directly with GraceLint.

If repository tooling/environment still prevents `make lint` from reaching a clean zero because of known baseline Ruff debt or missing `.venv` Ruff, report the exact commands and exact failures. Do not suppress unrelated debt and do not claim an individual command passed if it failed. `WEB_ORCH_CHECKS: PASS` must reflect that the TZ-specific implementation and focused verification are green, with repository-baseline failures called out separately and precisely.

## Acceptance criteria

Architect will inspect the actual implementation commit and diff. ACCEPT requires all of the following:

1. `packet_executor.py <= 1000` physical lines.
2. `execute()` is below 4000 estimated tokens and has meaningful headroom where practical.
3. No extracted function/method exceeds 4000 estimated tokens.
4. No new Python module exceeds 1000 lines.
5. Refactor is by coherent responsibility, not arbitrary slicing/compression.
6. Existing dedicated services remain the single owners of their business rules.
7. Public imports for `PacketExecutionAdapter` and `ExecutionResult` remain compatible.
8. Safety, rerun, scope, no-change, acceptance, commit-detection, persistence, and observability semantics remain unchanged.
9. Behavioural tests are not weakened.
10. Required protection tests remain/add coverage for the six critical paths above.
11. No `GRC005/GRC012` suppression is added.
12. Diff contains no unrelated product/API/DB/config/state-machine change.
13. Focused execution tests and targeted GraceLint checks pass.

## Submission content

Keep `02_PACKET_EXECUTION_SUBMISSION.md` concise but include:

- exact implementation commit SHA;
- files created/modified;
- before/after line count for `packet_executor.py`;
- before/after `len(source) // 4` estimate for `execute()`;
- largest function(s) in every touched/new execution module;
- responsibility -> new owner mapping;
- existing services reused;
- compatibility facade/re-exports retained;
- tests updated/added and why;
- confirmation no behavioural assertion was weakened;
- exact verification commands/results;
- any known follow-up debt, without starting another named TZ.
