WEB_ORCH_REPORT: SUBMISSION 05_ADMIN_CONTROL_CENTER
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 5cab190c18bef51977253e27fb9381a8ce713ebf
WEB_ORCH_CHECKS: PASS

# TZ05 Admin Control Center submission

## Implementation

The stable `AdminControlCenterService` import, constructor and public page
signatures remain unchanged. The facade now delegates to four coherent owners:

- `admin_control_center_project_service.py` — contexts, dashboard, project tree,
  project shell, system and maintenance composition.
- `admin_control_center_packet_service.py` — packet base reads, run/stage
  validation, timeline filtering, sessions, diagnostics, evidence, logs,
  artifacts and packet DTO assembly. `_packet_page` was decomposed into these
  bounded responsibilities rather than moved intact.
- `admin_control_center_explorer_service.py` — Files, Git and OpenAPI discovery;
  non-GET execution still delegates exclusively to `AdminMutationService`.
- `admin_control_center_page_service.py` — Events, Logs and Search page models.

The original `admin_control_center.py` was 1652 physical lines; the facade is
now 564 lines. New modules are 505, 795, 599 and 267 lines respectively.
Largest Grace-estimated functions (`len(source) // 4`) are:

- facade `project_page`: 327;
- project owner `project_page`: 1020;
- packet owner `_build_packet_model`: 950;
- explorer owner `files_page`: 1211;
- global-page owner `logs_page`: 679.

Existing `admin_control_center_helpers.py`,
`admin_control_center_explorer_helpers.py`, `AdminCrossProjectService`,
`AdminMutationService`, `admin_control_security.py` and the existing project
Admin APIs remain the authoritative normalization, masking, Hub, mutation,
authorization and capability boundaries. The public facade and the historical
private seams `_packet_page`, `_scope_rows_to_run`, `_project_card`, `_read`,
`_context`, card/selector helpers and `_explorer_shell` remain available as
delegating wrappers. `_OPENAPI_CACHE_TTL_SECONDS` remains import-compatible.

No tests were weakened or changed; the existing direct matrix covers the
facade, project isolation, packet tabs, Files/Git/OpenAPI explorers, mutation
gating, security and router/template compatibility.

## Verification

- Direct Control Center/API/UI command covering stage07, stage07 matrix, admin
  router, stage06 controls and both UI explorer modules: `73 passed, 3 skipped`.
- `python3 scripts/grace_lint.py` targeted at the facade and all four new owners:
  PASS.
- Ruff targeted at the facade and all four new owners: PASS.
- `.venv/bin/python -m py_compile` on the facade and all four new owners: PASS.
- `git diff --check`: PASS.
- `make test` in current checkout: `1584 passed, 2 skipped, 33 failed`.
- The same `make test` command in a clean parent checkout with the same absolute
  Python environment: `1584 passed, 2 skipped, 33 failed`; the 33 failure nodes
  and failure causes are identical. Differences are only nondeterministic
  timestamps, temporary paths, generated IDs and warning counts. No Control
  Center failure was introduced.
- `make lint` in both current and clean parent: exit 2 because
  `/opt/grace-orchestrator/.venv/bin/python` has no `ruff` module; targeted Ruff
  passes with the installed system Ruff.
- `make docs-check` in both current and clean parent: exit 2 with identical
  pre-existing generated drift in `docs/openapi.json`, `docs/state-diagram.md`
  and `docs/packet-states.md`.
- Semantic OpenAPI hash is identical in current and clean parent:
  `7d847ff6a70c6ea300f4366ef1cb757dca180dce47ade83c2d7b8bc8c890e2c8`.

No allowlist entry was added. Project isolation, explicit project selection,
disabled-project no-read behavior, filesystem/Git path safety, secret masking,
OpenAPI discovery/cache semantics, mutation gating and DTO/fallback/error
fields remain covered and unchanged. No Part A, block 06 or unrelated follow-up
work was started.
