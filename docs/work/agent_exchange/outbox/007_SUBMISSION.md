WEB_ORCH_REPORT: SUBMISSION 007
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 6ad8d36f75593fc1b8616fc4f40bbe5c2ee1cfc2
WEB_ORCH_CHECKS: PASS

Implemented TZ01 Project Hub foundation and pushed `6ad8d36f75593fc1b8616fc4f40bbe5c2ee1cfc2`.

- Added validated `/etc/grace/projects.yaml`-compatible registry with duplicate/invalid transport/path checks and frozen `ProjectContext`.
- Added bounded HTTP/Unix-socket `ProjectClient`, typed errors, safe JSON decoding and secret-free browser DTOs.
- Added service-owned bounded concurrent fan-out, disabled-project skipping, registry/runtime identity comparison and isolated failure results.
- Added the four required routes: `GET /api/admin-hub/projects`, `GET /api/admin-hub/projects/{project_key}`, `GET /api/admin-hub/projects/{project_key}/health`, and `GET /api/admin-hub/health`, plus project-local `GET /api/admin/project-identity`.
- Added 10 independent-project acceptance tests; the focused Hub/single-project suite passed **71 tests**. New modules passed Ruff, `py_compile`, GRACE lint and `git diff --check`.

No TZ01 scope deviation. The existing `tests/grace_control/api/test_admin_router.py` still has six unrelated baseline failures (legacy control-stub and stale SPA/template assertions); no files or routes covered by those expectations were changed for TZ01.
