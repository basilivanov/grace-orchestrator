WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_LIFECYCLE_SERVICE_EXTRACTION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: e8587a62c99f329847236cdef2c5206ea9a21529
WEB_ORCH_CHECKS: PASS

## Sync

- Synced `main` with `origin/main` using `git switch main`, `git fetch origin main`, and `git merge --ff-only origin/main`.
- Synced base SHA: `d29727f6d2a8cdfad230fa4b8370c19f4bf78f1e`.
- Initial status was `## main...origin/main` with unrelated untracked files `.env.bak-mini-endpoint-20260705170600` and `parse_list.py`; both were preserved and excluded from the commit.

## Implementation

- Added explicit `RuntimeStateStore`, `VersionProvider`, `WorkerReadService`, `SupervisorControlService`, and `LifecycleService` services.
- Added `config/lifecycle_settings.py` and `lifecycle_composition.py`; each composition call resolves `GRACE_TARGET_DIR -> settings.target_dir -> /tmp/grace-live-wt`, so test/runtime environment changes after import are honored without mutating global settings.
- Rewrote `lifecycle.py` as a thin FastAPI adapter. State parsing, Worker projection, Git lookup, health/version/status composition, and UDS control are below the router boundary.
- `SupervisorControlService` uses the existing `SupervisorClient`; composition sets the lifecycle timeout to 30 seconds. Missing state maps to 503, missing socket/transport to 502, and remote HTTP status/detail are preserved.
- Admin restart/reload now receive `build_lifecycle_service` through an explicit dispatcher callback. Existing confirmation and canonical audit sequencing remain unchanged; typed lifecycle failures are converted before the audit outcome is recorded.
- Added AST architecture guard and focused service tests. Updated the existing failed-supervisor Admin test to patch the explicit lifecycle composition seam.

## Dependency graph

```text
FastAPI lifecycle router
  -> build_lifecycle_service()
    -> LifecycleService
      -> RuntimeStateStore
      -> SupervisorControlService -> SupervisorClient
      -> WorkerReadService -> get_db/Worker
      -> VersionProvider -> GitService

Admin controls -> explicit lifecycle_service_fn -> LifecycleService
```

Cleanup and shutdown remain audited/unavailable legacy aliases; no schema or route contract changed.

## Structural checks

- Lifecycle router scan for `os.environ`, `subprocess`, `httpx`, `get_db`, `Worker`, and ORM `.query(`: zero hits.
- Removed helper/private-control scan for `read_state_file`, `get_git_sha`, `get_db_workers`, `_proxy_supervisor`, `_restart_local`, and `_reload_local` in the specified API modules: zero hits.
- Admin-local import scan for `grace_control.api.routers.lifecycle`: zero hits.
- FastAPI import scan across the five extracted services: zero hits.
- No new lint/size allowlist entry was added.

## Checks

- Focused service + architecture tests: **24 passed**.
- Lifecycle API regression `tests/supervisor/test_lifecycle_api.py`: **8 passed**.
- Admin control suites `test_admin_controls_stage06.py` and `test_admin_controls_stage06_review.py`: **23 passed**.
- The broader Stage07 topology suite reached fixture setup but had **4 setup errors** because its 15-second readiness window expired while the isolated subprocess was still running the existing Alembic startup (captured startup logs show approximately 18 seconds from `db_init_start` to `db_init_done`); no Stage07 assertion ran. This is an environment/startup timing limitation outside the lifecycle packet and is not reported as a packet regression.
- `python3 scripts/grace_lint.py` on all changed Python files/tests: PASS.
- `ruff check` on all changed Python files/tests: PASS.
- `python3 -m py_compile` on all changed Python files/tests: PASS.
- `git diff --check`: PASS.
- Implementation commit pushed to `origin/main`: `e8587a62`.
