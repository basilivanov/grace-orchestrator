WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CONTROL_CENTER_DEPENDENCY_INVERSION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 7503ba67c6ba08ddfcbf9edf2ea7d11cbe71217d
WEB_ORCH_CHECKS: PASS

## Sync

- Synced base SHA: `185a9f07317d5190fa1dd1598f7ddd61ac245906`.
- Initial status: `main...origin/main`, with preserved unrelated untracked files:
  `.env.bak-mini-endpoint-20260705170600` and `parse_list.py`.
- `git fetch origin --prune` and `git pull --ff-only origin main` completed successfully.

## Implementation

Changed/added files:

- `src/grace_control/services/admin_control_center.py`
- `src/grace_control/services/admin_control_center_project_service.py`
- `src/grace_control/services/admin_control_center_packet_service.py`
- `src/grace_control/services/admin_control_center_explorer_service.py`
- `src/grace_control/services/admin_control_center_page_service.py`
- `src/grace_control/services/admin_control_center_project_shell.py` (added)
- `src/grace_control/services/admin_project_access.py` (added)
- `tests/grace_control/architecture/test_admin_control_center_dependency_inversion.py` (added)

No files were deleted. The implementation commit was pushed to `origin/main`.

Before:

```text
AdminControlCenterService
  -> facade-backed Project/Packet/Explorer/Page services
  -> dynamic Hub OpenAPI cache
  -> private facade bridges (_read, _context, _explorer_shell, and child-only bridges)
```

After:

```text
AdminControlCenterService
  -> AdminProjectAccess -> CrossProjectTransport
  -> AdminControlCenterProjectShell -> AdminProjectAccess + public Hub overview
  -> AdminControlCenterExplorerService -> AdminProjectAccess + ProjectShell + one AdminMutationService
  -> AdminControlCenterPacketService -> AdminProjectAccess + Explorer + one AdminMutationService
  -> AdminControlCenterProjectService -> AdminProjectAccess + ProjectShell + Packet
  -> AdminControlCenterPageService -> public Hub + ProjectShell
```

Removed all focused-child `self._facade` references, facade-private read/context
bridges, and private Hub reach-through from the named Control Center services.
No private `AdminControlCenterService` compatibility methods remain; therefore
there are no retained private-method callers to justify. The only retained
module-level compatibility symbol is `_OPENAPI_CACHE_TTL_SECONDS`, imported by
the existing Stage 07 matrix acceptance test; it is a read-only TTL constant,
not a facade dependency.

`AdminProjectAccess` owns the mutable project-keyed OpenAPI cache and exposes it
through `openapi_cache`. The Hub is no longer mutated with `_admin_openapi_cache`.
`AdminMutationService` is constructed once in the composition root and injected
into Explorer and Packet services. Mutation internals and policy were not
refactored.

## Checks

- Required Control Center/Hub/UI regression set: **50 passed, 3 skipped**.
- Required four packet regression files: **27 passed, 1 skipped**.
- Architecture guard: **4 passed** in the final combined run; focused guard plus
  matrix check: **6 passed, 1 skipped**.
- Ruff: PASS on all changed Python files.
- GRACE lint: PASS on all changed Python files.
- `py_compile`: PASS for all changed production and guard files.
- `git diff --check`: PASS.

Forbidden-reference scans returned zero hits for:

```text
self._facade
_facade._hub
_hub._registry
_hub._request
_hub._client_factory
_admin_openapi_cache
```

The child-service scan for `AdminControlCenterService` also returned zero hits.

Wave 3 and all later work were not started.
