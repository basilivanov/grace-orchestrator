# File-level review: Business Feature Intake follow-up 3

Status: REVIEWED / CONDITIONAL PASS — CORE P0s CLOSED, CLEANUP REQUIRED
Date: 2026-06-12
Reviewed commit: `b08ea59`
Base: `569d781`
Scope: file-level review of `569d781..b08ea59`

## Diff scope

GitHub compare for `569d781..b08ea59` shows one commit and these changed files:

```text
src/grace_control/agent/universal_cli_backend.py
src/grace_control/api/routers/architect.py
src/grace_control/api/routers/features.py
src/grace_control/core/context_collector.py
src/grace_control/core/llm_runner.py
src/grace_control/services/agent_run_service.py
src/grace_control/services/feature_intake_service.py
src/grace_control/services/feature_planning_service.py
src/grace_control/services/process_supervisor.py
tests/grace_control/services/test_feature_planning_store.py
```

This follow-up directly targets the blockers from `REVIEW_BUSINESS_FEATURE_INTAKE_7A8BB1E_FILE_LEVEL.md`.

## Executive verdict

Conditional pass.

The commit closes the main architectural P0 blockers from the previous review:

1. `/api/architect/plan` is now a compatibility wrapper over `FeatureIntakeService` / `FeaturePlanningService`.
2. `regenerate-plan` now starts the same background planning flow.
3. Feature planning runs now create stdout/stderr log paths before execution.
4. `run_llm` → `UniversalCliAgentBackend` → `AgentRunService` → `ProcessSupervisor` now accepts stdout/stderr log paths.
5. `ProcessSupervisor` now writes subprocess stdout/stderr incrementally when log paths are supplied.
6. Tests were expanded around UID format, log paths, PLAN_FAILED approve blocking, and ready/draft materialization state.

This is now directionally acceptable for the Business Feature Intake implementation, with required cleanup before calling the whole Waves 1–4 production-ready.

## Closed blockers

## P0-1 closed — `/api/architect/plan` no longer owns active planning flow

`architect.py` was changed from the old direct implementation into a compatibility wrapper.

The router now:

- creates the feature via `FeatureIntakeService`;
- for predefined waves, stores `plan_json` and calls `FeaturePlanningService.approve_plan()`;
- for business text, runs `FeaturePlanningService.run_context_builder()` and `FeaturePlanningService.run_architect()` in background or sync mode.

This closes the previous duplicate active path blocker.

Important note: old helper functions still remain below the wrapper, but the active `create_plan()` path no longer calls them.

## P0-2 closed — Regenerate now starts planning

`POST /api/features/{feature_id}/regenerate-plan` now calls `regenerate_plan()` and then starts `_bg_regenerate()` which runs:

```python
context = await planning.run_context_builder(feature_id)
await planning.run_architect(feature_id, context)
```

This closes the previous “regenerate only creates pending run” blocker.

## P0-3 mostly closed — live log path propagation exists

`FeaturePlanningService` now creates per-run log directories:

```text
/tmp/grace_planning_logs/{feature_id}/{run_id}/stdout.log
/tmp/grace_planning_logs/{feature_id}/{run_id}/stderr.log
```

and stores those paths on `FeaturePlanningRun` before context/architect execution.

The log paths are passed into:

```text
ContextCollector → run_llm → UniversalCliAgentBackend → AgentRunService → ProcessSupervisor
```

`ProcessSupervisor.run()` now accepts `stdout_log_path` / `stderr_log_path` and writes lines incrementally while reading stdout/stderr.

This is sufficient to close the original “only endpoint, no live log plumbing” blocker.

## P0-4 improved — materialization uses canonical UIDs and enrichment

`FeatureIntakeService` now uses canonical feature/run UID helpers.

`FeaturePlanningService.approve_plan()` now uses canonical wave/packet/run UID helpers and applies `enrich_packet()`, root verification, frozen scope, first-wave `READY`, and later-wave `DRAFT` behavior.

This is a meaningful improvement over direct UUID/fake packet materialization.

## Remaining issues

## P1-1 — Old helper code remains in `architect.py`

Even though the active route is now a wrapper, old helper functions remain in the file:

```text
_persist_plan
_warm_context
_call_architect_llm
_run_opencode
```

Impact:

- not an immediate runtime blocker if unused;
- still confusing and increases maintenance risk;
- future agents may accidentally reuse the old helpers and reintroduce drift.

Required cleanup:

- delete old unused helpers, or move them into a clearly archived/deprecated module;
- add a comment/test that `/api/architect/plan` behavior is service-owned.

## P1-2 — live streaming branch does not send `stdin_text`

`ProcessSupervisor.run()` supports `stdin_text` in the old `proc.communicate(input=in_data)` path.

In the new streaming path, it starts readers and waits for stdout/stderr, but does not write `stdin_text` to `proc.stdin`.

Impact:

- current architect profiles use `input.mode: file`, so this likely does not break the reviewed architect path;
- stdin-mode profiles using live logs could hang or receive no prompt.

Required fix:

- in streaming mode, write and close `proc.stdin` when `stdin_text` is provided;
- add a ProcessSupervisor test for streaming + stdin.

## P1-3 — logs endpoint still needs path and stream validation

The logs endpoint still chooses stdout when `stream == "stdout"`, otherwise stderr. It also reads the stored path directly.

Impact:

- not arbitrary user path input, because path comes from DB run state;
- still should be hardened.

Required fix:

- reject streams except `stdout` / `stderr`;
- validate resolved path is under `/tmp/grace_planning_logs/` or configured state root;
- cap `tail` with lower and upper bounds.

## P1-4 — failed architect plan is still stored as `plan_json`

When `run_architect()` fails, it creates `_fallback_plan()` and `_finalize_plan()` stores it into `spec["plan_json"]`, while feature status becomes `PLAN_FAILED`.

Approval is correctly blocked by status, but storing fallback as `plan_json` can confuse UI/operators.

Required fix:

- store failed fallback under `planning_error` or `fallback_plan_json`;
- or mark the fallback plan with `fallback: true` and make UI clearly show it as non-approvable.

## P1-5 — test suite still needs live-stream behavior test

New tests verify that stdout/stderr paths are populated, but they do not prove that logs are written while a subprocess is still running.

Required fix:

- add a direct `ProcessSupervisor` test with a slow process that prints lines over time;
- assert the log file has content before process completion;
- add a streaming + stdin regression test.

## P1-6 — mode remains free-form string

`FeatureCreateRequest.mode` still appears to be plain `str` rather than a strict enum/literal.

Required fix:

```text
mode: Literal["draft_plan", "auto_queue"]
```

Unknown modes should return 422 instead of creating a planning feature and falling through.

## File-level notes

## `src/grace_control/api/routers/architect.py`

Good:

- active route now delegates to `FeatureIntakeService` and `FeaturePlanningService`;
- predefined waves are validated and materialized via `approve_plan()`;
- business-text flow uses same context/architect services as `/api/features`.

Needs cleanup:

- old helper code remains after line 212;
- wrapper still has some routing orchestration, but that is acceptable for compatibility after P0 closure.

## `src/grace_control/api/routers/features.py`

Good:

- regenerate route now starts background planning.

Needs cleanup:

- logs endpoint should validate stream/path;
- regenerate route duplicates background planning wiring from create path; consider service helper `start_background_planning(feature_id, target_repo_root)`.

## `src/grace_control/services/feature_planning_service.py`

Good:

- canonical UID usage added;
- log paths created before context/architect run;
- context collector and architect LLM receive log paths;
- materialization uses enrichment and first-ready/later-draft behavior.

Needs cleanup:

- fallback failed plan handling;
- no direct test yet that invalid architect JSON reaches `PLAN_FAILED` and blocks approve;
- live log path root is hardcoded to `/tmp/grace_planning_logs`.

## `src/grace_control/services/process_supervisor.py`

Good:

- incremental stdout/stderr writing exists.

Needs cleanup:

- streaming branch should handle `stdin_text`;
- streaming branch should be covered by direct tests.

## `tests/grace_control/services/test_feature_planning_store.py`

Good:

- tests added for log path population;
- tests added for PLAN_FAILED approve block;
- tests added for exact first-wave READY / later-wave DRAFT behavior;
- tests added for canonical UID formats.

Needs cleanup:

- add monkeypatched fake LLM/context tests for call contract;
- add ProcessSupervisor live-stream test;
- add `/api/architect/plan` wrapper regression test.

## Acceptance status against previous blockers

| Previous blocker | Status in `b08ea59` |
| --- | --- |
| `/api/architect/plan` wrapper | Closed, with cleanup needed |
| `regenerate-plan` does not run | Closed |
| live log plumbing missing | Mostly closed; streaming test/stdin cleanup needed |
| stronger tests | Improved, not complete |
| real context / architect path | Previously improved; still acceptable direction |

## Final decision

Conditional pass.

The implementation is now acceptable as a functional architecture slice for Business Feature Intake, but it should not yet be labeled “fully production-hard Waves 1–4” until the P1 cleanup items above are addressed.

Recommended next action:

Create a small polish/fix packet for:

1. delete or archive old architect helper code;
2. fix streaming + stdin in `ProcessSupervisor`;
3. harden planning logs endpoint;
4. add direct live-stream tests;
5. add `/api/architect/plan` wrapper regression test;
6. make `mode` an enum/literal.
