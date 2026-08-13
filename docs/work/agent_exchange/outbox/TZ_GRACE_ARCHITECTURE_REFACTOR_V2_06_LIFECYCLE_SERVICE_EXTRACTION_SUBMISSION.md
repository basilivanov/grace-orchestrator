WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_06_LIFECYCLE_SERVICE_EXTRACTION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: e8f04385fc74bbf4a87bdb91e842c64982968e48
WEB_ORCH_CHECKS: PASS

## Sync and implementation

- Synced base SHA: `e8f04385fc74bbf4a87bdb91e842c64982968e48`.
- Initial status: `## main...origin/main`; unrelated untracked files were preserved.
- `git fetch origin --prune` and `git pull --ff-only origin main` completed successfully; origin was already up to date.
- Implementation: **verified no-op**. The synced `HEAD` already satisfies Packet 06, so no source diff was manufactured.
- Implementation SHA: `e8f04385fc74bbf4a87bdb91e842c64982968e48`.

## Lifecycle dependency graph and thin router

- `lifecycle.py` is an HTTP adapter: it declares routes, extracts request data, delegates reads to `build_lifecycle_service()`, maps missing-state errors, and sends mutations through the existing audited Admin action path.
- `LifecycleService` composes explicit `RuntimeStateStore`, `SupervisorControlService`, `WorkerReadService`, and `VersionProvider` collaborators and owns status, versions, health-full, restart and reload composition.
- `RuntimeStateStore` owns target-dir-bound `supervisor.json` existence/read/JSON parsing and preserves the distinction between physical state presence and readable state.
- `VersionProvider` owns deterministic Git lookup through the existing bounded `GitService` boundary and candidate-directory fallback.
- `WorkerReadService` owns the Worker ORM query and historical worker projection serialization.
- `SupervisorControlService` validates restart targets, preserves the state-file/socket gates, delegates one mutation through `SupervisorClient`, and maps transport/remote failures to typed domain errors without retry.
- `lifecycle_composition.py` resolves target directory dynamically at service-build time using `GRACE_TARGET_DIR -> settings.target_dir -> local default` precedence and constructs the explicit graph; it is not a service locator or mutable global registry.

## Admin controls and compatibility

- `admin_controls_local.py` receives `lifecycle_service_fn` explicitly through the dispatch boundary; it does not import lifecycle-router private helpers.
- Restart/reload authorization, confirmation, audit, target validation, missing-state behavior, unavailable-supervisor behavior, cleanup/shutdown aliases, response/status contracts and bootstrap semantics remain intact.
- The lifecycle router has no direct `os`, `subprocess`, `httpx` UDS, `get_db`, `Worker`, filesystem JSON parsing or ORM query ownership. Historical private helpers (`read_state_file`, `get_git_sha`, `get_db_workers`, `_proxy_supervisor`, `_restart_local`, `_reload_local`) are absent from the active lifecycle router/services scan.
- No API/DB/lifecycle-state/packet execution/reviewer/recovery/merge semantics or later typed-read-model/dead-code/CI wave was changed.

## Checks

- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_lifecycle_router_boundary.py` — PASS, 6 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/supervisor/test_lifecycle_api.py` — PASS, 8 passed.
- Lifecycle service suite (`test_lifecycle_service.py`, `test_runtime_state_store.py`, `test_supervisor_control_service.py`, `test_worker_read_service.py`, `test_version_provider.py`) — PASS, 18 passed.
- Admin-controls restart/reload dispatch (`test_admin_controls_stage06.py`, `test_admin_controls_stage06_review.py`) — PASS, 23 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/supervisor/test_supervisor_integration.py` — PASS, 4 passed.
- `.venv/bin/python -m py_compile` on lifecycle router, Admin controls, composition, lifecycle collaborators, settings and SupervisorClient — PASS.
- `make lint` — PASS; baseline-aware gate reports Ruff `1020` and GraceLint `3249`, matching the reviewed baseline.
- `make docs-check` — PASS; 3 files in sync.
- `make hygiene` — PASS.
- `git diff --check` — PASS; no source diff was present.

Changed paths: `none` (verified no-op).

No next packet was started.
