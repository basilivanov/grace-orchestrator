# Final sign-off review: Business Feature Intake polish cleanup

Status: REVIEWED / PASS — NO REMAINING REVIEW BLOCKERS
Date: 2026-06-12
Reviewed commit: `481bbae`
Base: `5459b1d`
Scope: file-level review of `5459b1d..481bbae`

## Diff scope

GitHub compare for `5459b1d..481bbae` shows one narrow cleanup commit touching:

```text
src/grace_control/api/routers/architect.py
src/grace_control/api/routers/features.py
src/grace_control/config/settings.py
src/grace_control/services/feature_planning_service.py
tests/grace_control/services/test_feature_planning_store.py
tests/grace_control/services/test_process_supervisor_streaming.py
```

This is the expected final polish after `REVIEW_BUSINESS_FEATURE_INTAKE_58A44A6_FINAL_FILE_LEVEL.md`.

## Executive verdict

Pass.

The last remaining non-blocking review notes from `58a44a6` were addressed:

1. `planning_logs_root` is now a setting.
2. Feature logs route and planning service use `settings.planning_logs_root`.
3. The redundant `mode = "draft_plan" if not has_waves else "draft_plan"` was removed.
4. A true mid-run live-log test was added.
5. Tests no longer hardcode `/tmp/grace_planning_logs` where settings should be used.

No remaining blockers or required cleanup items were found in this final diff.

## Verified fixes

## 1. planning log root moved to settings

`GraceSettings` now includes:

```python
planning_logs_root: str = "/tmp/grace_planning_logs"
```

`features.py` now builds `_LOG_ROOT` from `settings.planning_logs_root`, not a hardcoded path.

`FeaturePlanningService.run_context_builder()` and `run_architect()` now create per-run log directories under `settings.planning_logs_root`.

Verdict: PASS.

## 2. redundant architect mode expression removed

`architect.py` now calls `FeatureIntakeService.create_feature(..., mode="draft_plan", ...)` directly.

The previous redundant conditional:

```python
mode = "draft_plan" if not has_waves else "draft_plan"
```

is gone.

Verdict: PASS.

## 3. mid-run live-log behavior covered

`tests/grace_control/services/test_process_supervisor_streaming.py` now includes:

```text
test_log_content_visible_mid_run
```

The test starts a slow process, checks that log content appears before the process finishes, waits for multiple lines, then asserts final completion.

Verdict: PASS.

## 4. logs endpoint still hardened

`features.py` still has:

- `stream: Literal["stdout", "stderr"]`;
- `tail: Query(..., ge=10, le=10000)`;
- path root validation against `_LOG_ROOT`.

With `_LOG_ROOT` now settings-backed, this is accepted.

Verdict: PASS.

## Final acceptance

The Business Feature Intake + Planning Observability slice is accepted.

Accepted capabilities:

- `/api/features` business feature intake;
- `/api/architect/plan` compatibility wrapper;
- feature-level planning runs;
- real Context Builder / Architect service path;
- draft planning and auto-queue modes;
- regenerate planning;
- approve/materialize to existing queue semantics;
- first wave READY, later waves DRAFT;
- planning logs endpoint;
- live stdout/stderr log plumbing with mid-run visibility;
- settings-backed planning log root;
- tests covering the accepted behavior.

## Final decision

```text
PASS — no remaining review blockers.
```

Reported local evidence from implementer:

```text
47/47 feature tests pass
```

This review accepts that evidence as reported, with file-level inspection confirming the corresponding source/test changes are present.
