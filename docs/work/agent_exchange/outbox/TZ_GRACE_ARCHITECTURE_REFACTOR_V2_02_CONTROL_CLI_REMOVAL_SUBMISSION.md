WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_02_CONTROL_CLI_REMOVAL
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 0c86e10e462549779f8b0d92161f08f3051fd590
WEB_ORCH_CHECKS: PASS

## Sync and implementation

- Synced base SHA: `93a48267ca957ba96cbfa7289781d8e70c6ff593`.
- Initial status was `main...origin/main` with unrelated untracked files preserved.
- `origin/main` was up to date before edits; the implementation commit was pushed to `origin/main`.
- Implementation SHA: `0c86e10e462549779f8b0d92161f08f3051fd590`.
- Scope stayed limited to control-CLI removal in migration helpers and the existing architecture guard.

## Classified CLI/entrypoint audit

- No `src/grace_control/cli.py` or control-CLI package remains.
- `pyproject.toml` exposes no removed control entrypoint and has no live Typer control dependency.
- Active operator checks and instructions no longer invoke `grace_control.cli`, `grace_ctl`, `gracectl`, or an equivalent wrapper.
- `scripts/validate_migration.sh` now validates the direct `grace_control.supervisor` bootstrap and the HTTP/OpenAPI lifecycle route.
- `scripts/migrate_to_grace_package.sh` now verifies the supervisor module and prints HTTP/OpenAPI operator checks.
- `scripts/rollback_migration.sh` no longer restores or instructs operators to use the removed CLI directory/module.
- Remaining `gracectl.yaml` references in migration helpers are legacy source-project configuration-file detection, not command or package entrypoint references. The old-directory wording in the migration documentation describes cleanup of that legacy source tree; it is not an operator command.
- `_LEGACY_ENTRYPOINTS` in `scripts/ci_repo_hygiene.py`, its synthetic negative test, and the focused architecture guard are negative policy/assertion coverage. Historical `docs/work/` evidence was not edited.

## Bootstrap and preserved internal execution

- `scripts/live_supervisor.sh` continues to invoke `python -m grace_control.supervisor` directly.
- HTTP/OpenAPI remains the runtime/operator control surface after bootstrap; existing routes and response contracts were not changed.
- `UniversalCliAgentBackend`, `mini_swe_runner`, `AgentRunService`, Agy execution, and generic subprocess/CLI agent execution were not removed or rewritten.
- No packet lifecycle/state, DB/Alembic, API, reviewer, recovery, acceptance, merge, or OpenCode-removal semantics were changed.

## Durable guard

`tests/grace_control/api/test_no_control_cli_surface.py` now checks module absence, removed package entrypoint absence, active-file absence of operator CLI invocations (including shell lookup and `python3 -m` forms), constructible FastAPI/OpenAPI routes, and direct supervisor bootstrap. It passed all 5 tests.

## Checks

- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_no_control_cli_surface.py` — PASS, 5 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/runtime tests/grace_control/agent` — PASS, 122 passed.
- `make lint` — PASS; baseline-aware gate reports Ruff `1020` and GraceLint `3249`, matching the reviewed baseline.
- `make docs-check` — PASS; 3 files in sync.
- `make hygiene` — PASS.
- `bash -n scripts/live_supervisor.sh scripts/validate_migration.sh scripts/migrate_to_grace_package.sh scripts/rollback_migration.sh` — PASS.
- `git diff --check` — PASS.
- Raw `.venv/bin/python scripts/grace_lint.py src/grace_control tests scripts` — non-zero with 3249 existing baseline diagnostics; not reported as a clean raw lint pass.
- Raw `.venv/bin/python -m ruff check src/grace_control tests scripts` — non-zero with 1020 existing baseline diagnostics; canonical `make lint` passed.

Changed paths:

- `scripts/MIGRATION_SCRIPTS.md`
- `scripts/migrate_to_grace_package.sh`
- `scripts/rollback_migration.sh`
- `scripts/validate_migration.sh`
- `tests/grace_control/api/test_no_control_cli_surface.py`

No next packet was started.
