# Final file-level review: Business Feature Intake polish

Status: REVIEWED / PASS
Date: 2026-06-12
Reviewed commit: `58a44a6`
Base: `df5855b`
Scope: file-level review of `df5855b..58a44a6`

## Diff scope

GitHub compare for `df5855b..58a44a6` shows one commit and these changed files:

```text
src/grace_control/api/routers/architect.py
src/grace_control/api/routers/features.py
src/grace_control/services/process_supervisor.py
tests/api/test_architect_background.py
tests/grace_control/services/test_process_supervisor_streaming.py
```

This is the expected narrow polish/fix packet after the conditional pass on `b08ea59`.

## Executive verdict

Pass.

The commit addresses the remaining cleanup items from the previous review:

1. old dead helper implementations were removed from `architect.py`;
2. `ProcessSupervisor` streaming mode now handles `stdin_text`;
3. planning logs endpoint now validates `stream`, enforces `/tmp/grace_planning_logs` root, and caps `tail`;
4. feature creation mode is now a strict `Literal["draft_plan", "auto_queue"]`;
5. dedicated ProcessSupervisor streaming tests were added;
6. architect background tests were updated for the wrapper path.

This is now acceptable as the completed Business Feature Intake + Planning Observability implementation slice.

## Acceptance summary

| Area | Status | Notes |
| --- | --- | --- |
| `/api/architect/plan` wrapper | PASS | Router now has active wrapper only; old helper implementations removed |
| Admin `/api/features` intake | PASS | Already closed in earlier commit |
| Real context/architect service path | PASS | Already closed in earlier commits |
| Regenerate starts planning | PASS | Already closed in earlier commit |
| Live log plumbing | PASS | ProcessSupervisor streaming + stdin covered |
| Logs endpoint hardening | PASS | `stream` Literal, tail bounds, root validation |
| Mode validation | PASS | `Literal["draft_plan", "auto_queue"]` |
| Tests | PASS | Added streaming tests and updated background wrapper tests |

## File-level findings

## `src/grace_control/api/routers/architect.py`

Verdict: PASS.

The file is now a genuine compatibility wrapper:

- imports only service/router dependencies;
- `create_plan()` creates the feature via `FeatureIntakeService`;
- predefined waves go through DAG validation, `plan_json`, and `FeaturePlanningService.approve_plan()`;
- business text goes through `run_context_builder()` and `run_architect()`;
- no old `_persist_plan`, `_warm_context`, `_call_architect_llm`, or `_run_opencode` functions remain.

This closes the duplicate planning path risk.

Minor note:

The line `mode = "draft_plan" if not has_waves else "draft_plan"` is redundant. It is harmless but can be simplified later.

## `src/grace_control/api/routers/features.py`

Verdict: PASS.

Accepted changes:

- `FeatureCreateRequest.mode` is now a `Literal["draft_plan", "auto_queue"]`, so invalid modes become Pydantic 422s.
- Logs endpoint uses `stream: Literal["stdout", "stderr"]`.
- Logs endpoint enforces `tail` bounds with `Query(..., ge=10, le=10000)`.
- Logs endpoint resolves path and rejects anything outside `_LOG_ROOT = /tmp/grace_planning_logs`.

This closes the mode and logs hardening cleanup.

Small future hardening option:

Use a configured log root instead of hardcoded `/tmp/grace_planning_logs`, but this is not a blocker.

## `src/grace_control/services/process_supervisor.py`

Verdict: PASS.

Streaming branch now writes `stdin_text` before reading stdout/stderr:

```python
if stdin_text and proc.stdin:
    proc.stdin.write(in_data)
    await proc.stdin.drain()
    proc.stdin.close()
```

This closes the stdin regression risk from the previous review.

The existing non-streaming `communicate(input=...)` path remains intact.

## `tests/grace_control/services/test_process_supervisor_streaming.py`

Verdict: PASS.

Added tests cover:

- stdout log writing in streaming mode;
- streaming mode with stdin;
- separate stdout/stderr log files;
- non-streaming compatibility.

Minor note:

The first test checks log content after process completion, not mid-process while the process is still alive. Given the implementation uses line-by-line writes and the test covers the streaming branch, this is acceptable for this acceptance pass. A stricter mid-run assertion can be added later if needed.

## `tests/api/test_architect_background.py`

Verdict: PASS.

Background architect tests are now aligned with the wrapper path:

- immediate background response;
- feature created in `PLANNING` / `PLAN_READY`;
- background creates feature planning runs;
- failure path is at least status-bounded;
- run stdout/stderr paths are asserted for context_builder/architect runs.

## Final decision

Pass.

The implementation can now be treated as accepted for the Business Feature Intake + Planning Observability slice.

Recommended follow-up outside this acceptance:

1. optionally replace hardcoded `/tmp/grace_planning_logs` with a settings value;
2. optionally add a stricter mid-run live-log assertion;
3. optionally simplify the redundant `mode = "draft_plan" if not has_waves else "draft_plan"` line in `architect.py`.

None of these are blockers.
