# TZ 03_FEATURE_PLANNING submission

Implementation commit: `aa37f581ea44c9e149ff1b4f78d4777ed7103f79`.

## Result

- `feature_planning_service.py`: 1532 → 987 physical lines; the stable `FeaturePlanningService` facade remains in place.
- Context Builder, Architect, planning workspace safety, and shared planning-run configuration were extracted into four focused modules:
  - `context_builder_stage.py` — Context Builder lifecycle, artifacts/events, heartbeat, and mutation guard.
  - `architect_stage.py` — Architect lifecycle, prompt rendering, strict current-contract normalization callback, retry, and finalization.
  - `planning_workspace_service.py` — git snapshot, disposable clone/copy, mutation evidence, and cleanup.
  - `planning_run_support.py` — log paths, target-root precedence, and context-disabled flag.
- The facade still exports `FeaturePlanningService`, `normalize_architect_plan`, `CONTEXT_BUILDER_MUTATED_TARGET_REPO`, `_git_snapshot`, `_planning_workspace_mutation`, `_prepare_planning_workspace`, and `_remove_planning_workspace` for existing imports and patch points.
- Public compiler usage and Part A files were not changed; no private `plan_validation.*` import was introduced.

## Ownership and compatibility

- Workspace isolation and mutation evidence → `planning_workspace_service.py`.
- Context Builder execution and context artifacts/events → `context_builder_stage.py`.
- Architect prompt, LLM retry, strict normalization call, and plan finalization → `architect_stage.py`.
- Environment/log configuration precedence → `planning_run_support.py`.
- Approval, materialization, repair, state queries, regeneration, heartbeat compatibility, and public facade → `feature_planning_service.py`.

Existing event names, artifact names, run fields/statuses, fallback behavior, log-path behavior, target-root precedence, compiler/materializer flow, and mutation safety were preserved. No test assertion was weakened and no broad skip was added.

## Size and function estimates

Grace estimate is `len(function_source) // 4`:

- Before: `approve_plan` ~3745, `try_approve_or_repair_plan` ~3467, `run_context_builder` ~2734, `run_architect` ~2163.
- After facade: `approve_plan` ~3674, `try_approve_or_repair_plan` ~3403; the stage wrappers are ~164 and ~211.
- Extracted largest functions: Context Builder `run` ~2639; Architect `run` ~1973; prompt renderer ~652; workspace preparation ~397.
- All touched/new Python modules are below 1000 physical lines and all functions remain below the 4000-token GraceLint threshold.

The three narrow GraceLint allowlist entries are limited to the intentional subprocess boundary (`planning_workspace_service.py`), environment adapters (`planning_run_support.py`), and the required canonical OpenCode fallback identifier (`context_builder_stage.py`).

## Verification

- `.venv/bin/python -m pytest tests/grace_control/services/test_feature_planning_service.py -q` — 3 passed, 2 failures caused by the existing unwritable `/tmp/grace_planning_logs`; clean parent has the identical failure nodes. With a writable test-only log root: 5 passed.
- `.venv/bin/python -m pytest tests/grace_control/services/test_feature_planning_store.py -q` — 9 passed, 9 failures caused by the same `/tmp` permission/fixture baseline; clean parent has the identical failure nodes. With a writable test-only log root: 15 passed, 3 existing fallback-fixture failures.
- `.venv/bin/python -m pytest tests/grace_control/services/test_context_builder_safety.py -q` — 30 passed, 2 existing `/tmp` permission failures; clean parent has the identical failure nodes. With a writable test-only log root: 32 passed.
- `.venv/bin/python -m pytest tests/grace_control/services/test_plan_autofix.py -q` — 24 passed.
- `make test` — 1584 passed, 2 skipped, 33 failed. A clean `8801bf25` worktree with the same command/environment produced the identical 33 failure-node set.
- `.venv/bin/python -m py_compile` on the facade and four extracted modules — PASS.
- `python3 scripts/grace_lint.py` on the facade and four extracted modules — PASS.
- Full `python3 scripts/grace_lint.py src/grace_control` — repository-wide existing violations remain (1143 current vs 1157 on clean parent); no violation is reported for the touched/new planning modules.
- `make lint` — environment blocker: `.venv/bin/python -m ruff` reports `No module named ruff`; clean parent has the same blocker.
- `git diff --check` and staged diff check — PASS.
- Compatibility imports and private plan-validation reference check — PASS.
- `git push origin main` — PASS.

WEB_ORCH_REPORT: SUBMISSION 03_FEATURE_PLANNING
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: aa37f581ea44c9e149ff1b4f78d4777ed7103f79
WEB_ORCH_CHECKS: PASS
