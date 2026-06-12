# File-level review: Business Feature Intake follow-up 2

Status: REVIEWED / FAIL — PARTIAL PROGRESS, CORE BLOCKERS REMAIN
Date: 2026-06-12
Reviewed commit: `7a8bb1e`
Base: `25a4df2`
Scope: file-level review of `25a4df2..7a8bb1e`

## Diff scope

GitHub compare for `25a4df2..7a8bb1e` shows one commit and these changed files:

```text
src/grace_control/api/routers/features.py
src/grace_control/services/feature_planning_service.py
tests/grace_control/services/test_feature_planning_store.py
```

So this is a narrow follow-up over the previous review. It mainly tries to replace stubbed Context Builder / Architect with async real integrations.

## Executive verdict

Fail, but improved.

This commit closes part of the previous blocker around pure stubs:

- `run_context_builder()` is now async and calls `ContextCollector`.
- `run_architect()` is now async and calls `run_llm()` unless `GRACE_CONTEXT_DISABLED` is set.
- `features.py` awaits context + architect in background and auto_queue flows.
- Service tests were adapted to async methods.

However, the implementation is still not acceptable as completed Waves 1–4 because the core architecture still has unresolved blockers:

1. `/api/architect/plan` is still the old duplicate planning path, not a compatibility wrapper.
2. Wave 4 live logs are still not implemented.
3. `regenerate_plan()` still does not actually restart planning.
4. Failure behavior can mark a feature `PLAN_READY` with fallback plan even after architect failure in non-disabled mode, depending on branch behavior.
5. Tests still mostly validate shape/state, not real integration guarantees.

## What improved

## Improved 1 — Context Builder is no longer a fixed stub in the normal path

`FeaturePlanningService.run_context_builder()` now:

- accepts `target_repo_root`;
- resolves settings target repo root;
- constructs `ContextCollector`;
- calls `collector.collect(...)`;
- persists summary, estimated scope, complexity, file count, file previews.

This is meaningful progress.

## Improved 2 — Architect is no longer a fixed stub in the normal path

`FeaturePlanningService.run_architect()` now:

- builds an architect prompt from task + context;
- calls `run_llm()`;
- normalizes plan/waves/packets;
- stores model/result;
- marks `PLAN_READY` on successful architect run.

This is also meaningful progress.

## Improved 3 — API flow was updated to await async planning methods

`POST /api/features` background path now calls:

```python
context = await planning.run_context_builder(feature_id, request.target_repo_root)
await planning.run_architect(feature_id, context, request.target_repo_root)
```

The `auto_queue` path does the same before approval.

## Blocking findings

## P0-1 — `/api/architect/plan` is still a duplicate planning implementation

Expected:

`/api/architect/plan` should be a thin compatibility wrapper over `FeatureIntakeService` / `FeaturePlanningService`.

Actual:

`src/grace_control/api/routers/architect.py` still contains the old independent path:

- creates Feature/Wave/Packet placeholder directly;
- uses old `_warm_context()`;
- uses old `_call_architect_llm()`;
- uses old `_persist_plan()`;
- runs its own background task.

Impact:

There are still two business-feature planning paths:

1. `/api/features` using `FeaturePlanningService`;
2. `/api/architect/plan` using legacy router internals.

This violates the main architecture rule from the approved TZ: one control plane / one service path.

Required fix:

- convert `/api/architect/plan` into a wrapper that calls the same intake/planning service;
- remove direct placeholder wave/packet creation from the router;
- remove or move `_warm_context`, `_call_architect_llm`, `_persist_plan` into services/shared materializer;
- add a regression test that both paths share service behavior or that `/api/architect/plan` is deprecated and not used by Admin.

## P0-2 — Wave 4 live logs are still not implemented

Expected:

- stdout/stderr visible while Context Builder / Architect / Coder are still running;
- ProcessSupervisor / AgentRunService writes stdout/stderr incrementally;
- FeaturePlanningRun stores stdout_path/stderr_path;
- logs endpoint tails those files.

Actual in this diff:

- only `feature_planning_service.py`, `features.py`, and one service test file changed;
- no `ProcessSupervisor` or `AgentRunService` changes;
- `run_context_builder()` and `run_architect()` do not set `stdout_path` / `stderr_path`;
- logs endpoint can still only read paths that are never populated by the current planning service.

Impact:

Wave 4 remains incomplete. The API may exist, but there are no live planning logs.

Required fix:

- implement streaming process output at the process execution layer;
- store log file paths on every feature planning run;
- add a test that a long-running fake process writes stdout before completion.

## P0-3 — Regenerate still does not run planning

Expected:

`POST /api/features/{id}/regenerate-plan` should create a new planning run chain and actually rerun context + architect, or enqueue a runner that does so.

Actual:

`regenerate_plan()` still:

- sets `feature.status = "PLANNING"`;
- adds a new `context_builder` run with `pending`;
- removes `plan_json`;
- returns planning state.

It does not call context builder or architect, and no route-level background task starts after regenerate.

Impact:

Regenerate can leave a feature stuck in `PLANNING` with a pending run.

Required fix:

- either make `regenerate-plan` start the same background planning task as create;
- or add explicit planning runner/queue and document it;
- add tests that regenerate eventually reaches `PLAN_READY` or `PLAN_FAILED`.

## P0-4 — Architect failure semantics are unsafe

Expected:

If Architect LLM fails in normal mode, feature should become `PLAN_FAILED` and no fallback implementation packet should be silently accepted unless explicitly configured.

Actual:

In `run_architect()`, the exception path creates `_fallback_plan(...)`, sets `arch_run.status = "failed"`, and stores that fallback plan. `_finalize_plan()` then sets feature status to `PLAN_FAILED` if status is failed, which is better than earlier behavior.

But this is still risky because fallback plan is stored in `spec["plan_json"]` even when status is `PLAN_FAILED`.

Impact:

The UI/API may expose a fallback plan that looks approve-able unless approve correctly blocks by status. It currently does block because status is not `PLAN_READY`, but this needs a test.

Required fix:

- keep failed fallback diagnostics outside `plan_json`, e.g. `planning_error` / `fallback_result_json`;
- or clearly mark `plan_json.fallback = true` and add tests that fallback plans cannot be approved while status is `PLAN_FAILED`.

## P0-5 — Tests still do not prove real behavior

The service tests now await the async methods, but they still mostly assert broad shape:

- context is a dict and has a summary;
- plan is a dict and has waves;
- approve sets queued/ready;
- regenerate resets state.

They do not prove:

- `ContextCollector.collect()` was called with the right target repo root;
- `run_llm()` was called with the expected prompt/cli/cwd;
- invalid LLM JSON retries then fails visibly;
- regenerate starts real planning;
- `/api/architect/plan` is a wrapper;
- logs are live.

Required fix:

- add monkeypatched fake ContextCollector and fake run_llm tests;
- assert prompt contains business requirement + context file list;
- assert generated multi-wave plan is persisted exactly;
- assert failed LLM creates `PLAN_FAILED` and approve returns 409;
- assert compatibility path does not duplicate implementation.

## P1 findings

## P1-1 — Context failure marks the run failed but still returns fallback context

This can be acceptable, but the policy must be explicit.

If context fallback is allowed, then Architect should receive a payload that clearly says `fallback: true`, and event payload should include the error.

## P1-2 — Mode remains free-form string

`FeatureCreateRequest.mode` is still a plain string. Unknown modes fall through and return a created feature.

Required fix:

- make mode a Literal/Enum: `draft_plan | auto_queue`;
- reject unknown modes with 422.

## P1-3 — Materialization still does not reuse old `_persist_plan()` enrichment

`approve_plan()` still creates packets directly and does not appear to reuse the old enrichment path for verification/root constraints/gate defaults/self-improvement metadata.

Required fix:

- extract shared materializer from old `_persist_plan()`;
- keep first-wave READY behavior;
- keep gate enrichment and constraints.

## P1-4 — FeaturePlanningRun log fields remain unused

`FeaturePlanningRun` has stdout/stderr fields, but neither context nor architect stage writes them.

Required fix:

- either populate fields or remove Wave 4 claim until streaming is implemented.

## File notes

## `src/grace_control/api/routers/features.py`

Good:

- async service calls are now awaited correctly;
- `draft_plan` starts background task;
- `auto_queue` runs planning then approve inline.

Problems:

- unknown mode still falls through;
- route still owns background task wiring rather than delegating to a planning runner/service method;
- regenerate route still only calls `regenerate_plan()` and does not restart background planning.

## `src/grace_control/services/feature_planning_service.py`

Good:

- real ContextCollector path added;
- real run_llm architect path added;
- plan normalization added;
- fallback path separated for disabled/error conditions.

Problems:

- `/api/architect/plan` still owns duplicate old logic;
- no live log path population;
- failed fallback plan is still stored as `plan_json`;
- materialization remains simplified and not shared with old materializer;
- regenerate does not execute planning.

## `tests/grace_control/services/test_feature_planning_store.py`

Good:

- tests updated to async service methods.

Problems:

- assertions are still too shape-based;
- no fake LLM/context collector behavior assertions;
- no failure tests for invalid JSON / LLM failure / context failure;
- no compatibility-wrapper test;
- no live-log test.

## Required next fix

Do not keep broadening. The next packet should target the remaining architecture blockers only.

### Required Fix 1 — Compatibility wrapper

Convert `/api/architect/plan` to the new service path or explicitly deprecate it.

Acceptance:

- Admin uses `/api/features`;
- `/api/architect/plan` does not create placeholder packets directly;
- no duplicate `_warm_context/_call_architect_llm/_persist_plan` implementation remains in router.

### Required Fix 2 — Regenerate actually runs

Acceptance:

- `POST /api/features/{id}/regenerate-plan` starts the same background planning flow as create;
- final state becomes `PLAN_READY` or `PLAN_FAILED`;
- tests cover both success and failure.

### Required Fix 3 — Live logs

Acceptance:

- planning runs write stdout/stderr paths;
- ProcessSupervisor/AgentRunService or equivalent writes incrementally;
- logs endpoint returns content while process is still running.

### Required Fix 4 — Strengthen tests

Acceptance:

- fake ContextCollector proves context path is called;
- fake run_llm proves architect path is called;
- invalid JSON retry/failure tested;
- approve blocked on PLAN_FAILED;
- compatibility path tested;
- queue claim after approve tested.

## Final decision

Do not accept `7a8bb1e` as completed Waves 1–4.

Correct status:

```text
FAIL — real context/architect path started, but architecture is still incomplete.
```

Recommended next action:

Return to agent with this report and require a targeted fix for:

1. `/api/architect/plan` wrapper;
2. regenerate execution;
3. live logs;
4. stronger tests.
