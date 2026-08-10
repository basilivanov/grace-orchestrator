# GRACE Admin Control Center v3 — implementation index

Master specification:

`docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_MASTER.md`

## Goal of this split

The Control Center is intentionally divided into small reviewable stages. A coder should implement them in order. Every stage has a bounded source-of-truth document, tests and an independently useful result.

Do not start by rebuilding the frontend. The order is designed to establish correct multi-project isolation and complete read APIs before the UI depends on them.

## Stages

| Stage | File | Result |
|---|---|---|
| 01 | `TZ_GRACE_ADMIN_CONTROL_CENTER_01_PROJECT_HUB_FOUNDATION.md` | Project registry, immutable project contexts, Hub transport and health fan-out |
| 02 | `TZ_GRACE_ADMIN_CONTROL_CENTER_02_PROJECT_READ_SURFACE.md` | Complete project-local read surface: raw DTOs, OpenAPI, safe operational filesystem and Git metadata primitives |
| 03 | `TZ_GRACE_ADMIN_CONTROL_CENTER_03_CROSS_PROJECT_OBSERVABILITY.md` | Cross-project events, logs, search and diagnostics aggregation with failure isolation |
| 04 | `TZ_GRACE_ADMIN_CONTROL_CENTER_04_MULTI_PROJECT_UI.md` | Projects dashboard, project-aware navigation and full entity drill-down UI |
| 05 | `TZ_GRACE_ADMIN_CONTROL_CENTER_05_EXPLORERS.md` | Global Event/Log/File/Git/Raw/API explorers and large-data UX |
| 06 | `TZ_GRACE_ADMIN_CONTROL_CENTER_06_CONTROLS_SECURITY_MAINTENANCE.md` | Safe control actions, audit trail, security hardening and maintenance UI |
| 07 | `TZ_GRACE_ADMIN_CONTROL_CENTER_07_INTEGRATION_ACCEPTANCE.md` | Multi-project E2E, offline/failure isolation, performance smoke, regression and final docs |

## Dependency graph

```text
MASTER
  |
  v
01 Project Hub foundation
  |
  v
02 Project read surface
  |
  v
03 Cross-project observability
  |
  v
04 Multi-project UI
  |
  v
05 Explorers
  |
  v
06 Controls/security/maintenance
  |
  v
07 Integration acceptance
```

Stages are sequential because later stages rely on contracts created earlier. Within an individual stage, implementation can be split into backend/frontend/test packets if useful.

## Existing code to preserve/reuse

Before coding, inspect current `main`, especially:

- `src/grace_control/api/routers/admin_ui.py`;
- `src/grace_control/api/routers/admin.py`;
- `src/grace_control/services/admin_aggregation_service.py`;
- `src/grace_control/api/routers/diagnostics.py`;
- `src/grace_control/services/diagnostics_service.py`;
- Trace/Event APIs and services;
- `src/grace_control/config/project_config.py`;
- supervisor/maintenance services;
- existing admin Jinja/HTMX templates;
- existing Admin v2 and pipeline observability tests/specs.

Do not assume an older document's file layout is still exact; actual current code is authoritative for implementation details.

## Global invariants for every stage

1. No request-time mutation of process-global `GRACE_PROJECT_ROOT`, `settings`, DB binding or target repo selection.
2. Admin Hub never opens another project's SQLite directly.
3. Project-local DB/files/Git operations run through that project's GRACE API/runtime boundary.
4. One offline project cannot break cross-project views.
5. No arbitrary absolute filesystem reader.
6. No frontend direct DB/filesystem access.
7. Existing single-project Admin behavior remains usable while multi-project work is introduced.
8. Existing API contracts remain backward compatible unless a stage explicitly introduces a versioned replacement.
9. Heavy logs/artifacts/files are lazy and bounded.
10. Mutation/control operations never bypass existing domain services and must eventually be audited.

## Suggested coder workflow

For each numbered stage:

1. read MASTER + current stage only;
2. inspect current code and tests named by the stage;
3. implement only required primitives/UI;
4. run stage tests + relevant Admin/Trace/Events/Diagnostics regressions;
5. run Ruff / `python3 -m py_compile` / applicable GRACE lint / `git diff --check`;
6. commit and report SHA + checks;
7. only then continue to the next stage.

## Final target

```text
Admin Hub
  -> Projects dashboard
  -> per-project Feature/Wave/Packet tree
  -> Runs/Stages/Sessions
  -> Timeline + global Events
  -> Logs
  -> Evidence/Artifacts/Files
  -> Git/Worktrees
  -> Leases/Diagnostics
  -> Raw data + OpenAPI Explorer
  -> Safe Controls/Maintenance
```

The final Stage 07 must prove that two different project roots and two different SQLite databases cannot leak state into one another under concurrent Hub requests.
