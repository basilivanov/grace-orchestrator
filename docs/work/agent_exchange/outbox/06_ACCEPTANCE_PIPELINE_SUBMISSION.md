WEB_ORCH_REPORT: SUBMISSION 06_ACCEPTANCE_PIPELINE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 6cbac26e445b72530acc3da4bba93dd23d537107
WEB_ORCH_CHECKS: PASS

Implementation commit: `6cbac26e445b72530acc3da4bba93dd23d537107` (pushed to `origin/main`).

Files:

- Modified `src/grace_control/core/acceptance_pipeline.py`.
- Added `src/grace_control/core/acceptance_stage_service.py` for T0/T1/T2 scope, gate, command and result execution.
- Added `src/grace_control/core/acceptance_frontend_service.py` for browser/visual/a11y routing and StageResult mapping.
- Added one narrow GRC100 allowlist entry for the required `GRACE_BASE_REF`/`GRACE_BASE_SHA` process-environment compatibility side effect. No GRC005/GRC012 suppression was added.

Structural result:

- `acceptance_pipeline.py`: 926 → 673 physical lines.
- New modules: 562 and 243 physical lines.
- Largest functions by `len(source) // 4`: facade `AcceptancePipeline.run` 1603; replay 966; stage executor `run_t0` 987, `run_t2` 877, `run_t1` 831; frontend owner `run_frontend_stages` 1751. All are below 4000, with orchestration headroom.

Compatibility and responsibility seams:

- Public `run_acceptance_pipeline`, `run_acceptance_stage_replay`, `AcceptancePipeline`, its constructor and `run()` signature remain in the original module.
- Private `_run_t0`, `_run_t1`, `_run_t2` wrappers retain the original `@stage` instrumentation keys; shell/command helpers and `_run_frontend_stages`/`_commands_to_results` remain import-compatible.
- Changed-file/base precedence, fallback handling, `GRACE_BASE_SHA`, worktree cwd and run-directory handling remain in the entry-point preparation helper.
- Existing `CommandRunner`, `ScopeGuard`, `get_changed_files`, `gate_resolver`, `EvidenceCollector`, `check_expected_evidence` and frontend services remain authoritative; no duplicate command/scope/evidence policy was introduced.
- Stage order, short-circuit behavior, profile semantics, shell/env-prefix handling, command origins, evidence timing, report/verdict fields, legacy informational fields and all replay stages remain unchanged.

Verification:

- Direct acceptance/replay/integration/frontend/gate/evidence command: `241 passed, 1 skipped`.
- Targeted `python3 scripts/grace_lint.py` for all three acceptance modules: PASS.
- Targeted Ruff (`/home/astro/.local/bin/ruff check`): PASS.
- Targeted `.venv/bin/python -m py_compile` for all three acceptance modules: PASS.
- `git diff --check`: PASS.
- `make test`: `1584 passed, 2 skipped, 33 failed`. The clean parent checkout at `59bef3bf` with the same command and environment produced the identical 33 failure-node set; failures are outside this acceptance refactor.
- `make lint`: stops before GraceLint because `.venv/bin/python` has no Ruff installed. The clean parent with the same command and environment produced the identical failure (`No module named ruff`). Targeted Ruff and GraceLint both pass.
- No API routes, generated API docs, DB/schema, settings, state machine, packet executor, replay caller or admin files were changed.

No behavioral assertions were weakened and no follow-up packet was started.
