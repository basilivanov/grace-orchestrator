# TZ — Grace Local Adopt refactor / 02 Packet execution

Status: READY FOR CODER
Parent: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Priority: P0
Primary target: `src/grace_control/adapters/packet_executor.py`
Dependency: block 01

## 1. Problem

`packet_executor.py` has grown far beyond the Local Adopt file limit and the central `PacketExecutionAdapter.execute()` method owns too many lifecycle responsibilities.

The module contract describes the adapter as a thin execution facade, but the implementation currently coordinates or directly owns substantial pieces of:

- run loading/initialisation;
- executor resolution;
- runtime contract/selftest;
- materialisation;
- context safety gate;
- rerun dispatch;
- backend execution;
- runtime observability/artifacts;
- worktree inspection/commit detection;
- post-run scope enforcement;
- acceptance;
- verifier/reviewer routing;
- final persistence/error handling.

This block restores the adapter to a facade/coordinator instead of slicing the file arbitrarily.

## 2. Goal

After refactor:

- `packet_executor.py` <= 1000 lines, preferably <= 600-800;
- no function/method in the touched execution path >4000 estimated tokens;
- `execute()` reads as a high-level pipeline, not a full implementation of every stage;
- existing execution behaviour remains unchanged;
- existing dedicated services are reused rather than copied.

## 3. What we refactor

Required source:

- `src/grace_control/adapters/packet_executor.py`

New modules are expected. Exact names may be adjusted to existing naming conventions, but responsibilities must be coherent.

Preferred extraction boundaries:

### A. Execution preflight / runtime preparation

Move cohesive logic for:

- runtime contract creation;
- runtime selftest invocation/result mapping;
- runtime selftest artifact/event emission orchestration;
- effective target/worktree resolution needed for preflight;
- materialisation/context-required pre-run gate where it naturally belongs.

Suggested owner shape:

- `services/packet_execution_preflight_service.py`, or equivalent.

Do not duplicate `AgentRuntimeContractBuilder`, `AgentRuntimeSelftest`, `PacketMaterializer`; orchestrate those existing components.

### B. Rerun dispatch

The code already has dedicated rerun services.

Keep the execution adapter responsible only for deciding that the rerun branch is needed and delegating.

Do NOT reimplement:

- previous terminal context loading;
- rerun pipeline execution;
- rerun result persistence.

If useful, extract a small rerun coordinator that composes existing services. It must not become a second rerun business-logic owner.

### C. Post-execution worktree/scope stage

Extract cohesive orchestration for:

- worktree existence/result inspection;
- existing agent commit detection;
- no-change handling;
- runtime scope enforcement;
- diagnostic mapping needed immediately after backend execution.

Suggested owner shape:

- `services/packet_execution_postrun_service.py`, or equivalent.

Do not move generic Git operations out of their existing service boundaries unless needed to remove actual duplication.

### D. Acceptance/final routing

Keep existing `acceptance_pipeline`, verifier/reviewer, persistence and routing rules authoritative.

The adapter should delegate to small stage methods/services rather than inline the entire chain.

If extraction is required, extract orchestration only. Do not create duplicate acceptance semantics.

### E. Observability helpers

The current adapter contains substantial event/artifact helper logic.

Extract stateless/cohesive observability support if doing so materially reduces the adapter and improves ownership.

Suggested owner shape:

- `services/packet_execution_observability.py`, or equivalent.

Preserve exactly:

- event names;
- stage/component/status values;
- artifact names/paths/kinds;
- trace IDs and run/packet association;
- payload keys used by UI/admin/tests.

## 4. What remains in `PacketExecutionAdapter`

The facade should still own or expose the public adapter API expected by callers:

- constructor compatibility;
- `execute(packet_id, worker_id, claim_data=None)` public entry point;
- high-level stage ordering;
- dependency wiring required by the facade;
- compatibility helpers that are genuinely adapter-specific.

A good final `execute()` should resemble a readable sequence such as:

1. initialise run + observability;
2. preflight;
3. materialise/prepare;
4. rerun branch or backend execution;
5. inspect/enforce;
6. acceptance;
7. final route/persist;
8. fail safely.

The exact method names are implementation choice. The important constraint is one responsibility per extracted unit.

## 5. Existing dedicated owners to reuse

Before creating a new service, inspect and reuse current components including, where applicable:

- `AgentRuntimeContractBuilder`;
- `AgentRuntimeSelftest`;
- `PacketMaterializer`;
- `WorktreeInspector`;
- `AgentCommitService`;
- `WorktreeCleanupService`;
- `RuntimeArtifactStore`;
- `RuntimeEventLogger`;
- `RuntimeScopeEnforcer`;
- `rerun_context_service`;
- `rerun_pipeline_service`;
- `run_result_persistence_service`;
- `acceptance_pipeline`;
- evidence verifier / reviewer gate;
- packet control/rerun marker service.

Do not create parallel implementations with slightly different semantics.

## 6. Public/import compatibility

Do not rename/remove `PacketExecutionAdapter` or `ExecutionResult` as public import surfaces in this block.

If implementations move:

- keep re-exports in `adapters/packet_executor.py` where needed;
- avoid forcing unrelated callers/tests to import new internals;
- internal tests may target extracted units directly in addition to compatibility tests.

## 7. Tests — do we change them?

**Yes, but behaviour expectations stay the same.**

### Existing execution tests

Find tests covering:

- normal packet execution;
- claim-based execution;
- selftest pass/fail;
- context-required rejection;
- rerun branches;
- no-change behaviour;
- scope violations;
- acceptance rejection/acceptance;
- existing agent commit detection;
- persistence/result JSON;
- observability events/artifacts.

Keep those tests as regression contracts.

### Allowed test edits

- update monkeypatch/import targets when an internal helper moves;
- add unit tests for extracted preflight/postrun/observability coordinators;
- add a compatibility test importing `PacketExecutionAdapter` and `ExecutionResult` from the old module path;
- add stage-order tests if extraction makes order regressions easier to introduce.

### Required protection tests

At minimum preserve/add coverage proving:

1. failed runtime selftest fast-rejects before backend execution;
2. rerun branch does not fall through to normal backend execution;
3. accepted/rejected acceptance outcomes persist the same domain status/reason shape;
4. no-change feature flag behaviour is unchanged;
5. observability event names for major stages remain unchanged;
6. agent-created commit is still recognised when worktree is clean but HEAD differs from workspace base.

### Forbidden test edits

Do not change expected lifecycle/result values to accommodate implementation drift.

## 8. No behaviour changes

Specifically preserve:

- order of safety gates;
- runtime selftest default behaviour;
- target repository resolution;
- worktree naming / branch naming;
- context skip/required semantics;
- rerun one-shot semantics;
- `agent_runtime_fail_on_no_changes` semantics;
- scope enforcement;
- acceptance profile handling;
- verifier/reviewer flow;
- commit SHA capture;
- error propagation and terminal run status;
- result/evidence/diagnostics JSON keys.

## 9. Size acceptance

Required:

- `packet_executor.py` <=1000 lines;
- target <=800 lines where practical;
- `PacketExecutionAdapter.execute()` <4000 estimated tokens and preferably <=2500-3000;
- every extracted function/method <4000 estimated tokens;
- every new Python module <=1000 lines.

Do not achieve this by packing multiple statements onto one line.

## 10. Verification

Run the smallest directly affected tests first, then the relevant execution suite.

At minimum:

```bash
.venv/bin/python -m pytest tests/grace_control/ -q
make lint
```

If there are dedicated packet executor/runtime tests, run them explicitly before the broad suite.

Then, before merge of the whole programme:

```bash
make test
make ci
```

## 11. Coder submission

Include:

- before/after line count for `packet_executor.py`;
- before/after estimated token count for `execute()`;
- list of extracted responsibilities and destination modules;
- confirmation that existing dedicated services were reused rather than copied;
- tests updated/added and why;
- public compatibility retained;
- verification results.
