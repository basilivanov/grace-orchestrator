# Task 009 — Admin Control Center Stage 03: Cross-Project Observability

## Source of truth

Implement:

`docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_03_CROSS_PROJECT_OBSERVABILITY.md`

Read for context/invariants:

- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_MASTER.md`
- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_00_INDEX.md`

Depends on accepted Tasks 007–008 / Control Center Stages 01–02. Current code on `main` is authoritative where older docs differ.

## Objective

Implement only Control Center **Stage 03**: Hub-level JSON/service aggregation for cross-project overview, events, logs, search, diagnostics and attention.

The Hub must obtain project data through project-local APIs/`ProjectClient`; it must not open another project's DB, filesystem or Git tree directly. Do **not** build the final explorer/UI screens from later stages.

## Reviewer constraints

1. Add a service-layer cross-project composition component (`AdminCrossProjectService` or equivalent). Routers must not own fan-out loops, merge/sort logic or per-project error normalization.
2. Reuse Stage 01 registry/context/client isolation. Project selection must remain explicit; no process-global current-project/settings/DB mutation.
3. Fan-out only to requested/enabled projects and keep it concurrent/bounded so one slow project does not serialize or amplify timeout latency.
4. Every cross-project row/result must carry `project_key` and, where practical, project display name.
5. Implement `GET /api/admin-hub/overview` with per-project snapshots plus aggregate counts and explicit coverage metadata (`projects_total/responded/failed` or equivalent). Offline projects must not be counted as zero-valued healthy data.
6. Implement `GET /api/admin-hub/events` over canonical project-local event APIs. Forward requested filters, preserve full payload, merge by source timestamp descending without rewriting timestamps, retain project attribution and per-project errors.
7. Event pagination/continuation must be deterministic and documented. Do not pretend a naive per-project `limit` fetch is exact global pagination. A bounded partial/continuation model is acceptable if explicit and testable.
8. Implement `GET /api/admin-hub/logs` using project-local Stage 02 read/log APIs only. Normalize heterogeneous sources into one safe row model with project/source/timestamp/level/entity/trace/message/raw fields and normalized missing values.
9. Implement `GET /api/admin-hub/search?q=...` over project-local canonical search plus project metadata. Normalize supported result kinds and include canonical project-aware Hub target URLs. One project failure belongs in `errors`, not as a global failure.
10. Implement `GET /api/admin-hub/diagnostics` and `GET /api/admin-hub/projects/{project_key}/diagnostics`. Preserve each project snapshot and only compute aggregate counts when mathematically valid with explicit coverage.
11. Diagnostics must carry Stage 02 concurrency/worker/packet/ordinary lease/parallel lease/merge lease/wait/recheck/system-health data without exposing secrets/fencing tokens.
12. Add a normalized read-only attention model for operator-facing issues such as offline/identity mismatch/unhealthy runtime/failed or blocked packets/stuck merge or repeated safety failures. Do not mutate packet/business state.
13. Attention items must include severity, project key, kind, entity identity where relevant, title/reason/timestamp and a canonical detail URL.
14. Preserve original project timestamps despite possible clock skew; use timestamp only for global ordering and retain project attribution.
15. Normalize connect error, timeout, HTTP failure, malformed JSON, missing capability and partial project responses independently. One bad project must not corrupt healthy project data.
16. Any cache introduced must be short-lived, project-key scoped and limited to stable/expensive metadata. Do not aggressively cache active events/logs/packet state.
17. Preserve accepted Stage 01/02 behavior and all existing single-project APIs. Do not start Stage 04 UI or Stage 05 explorers.

## Required tests / acceptance proof

Use at least two independent fake/test project APIs with different identities and data. At minimum prove:

1. overview aggregates healthy projects;
2. offline project returns partial data, not 500;
3. overview/diagnostic coverage metadata is mathematically correct;
4. global event ordering and project attribution;
5. event filters are forwarded correctly;
6. event pagination/continuation semantics are deterministic;
7. logs from two projects normalize and retain source/project;
8. malformed log/event response from one project does not corrupt the other;
9. cross-project search returns project-aware canonical links;
10. diagnostics preserve per-project concurrency and lease state;
11. attention classification flags blocked/offline cases and ignores healthy idle cases;
12. fan-out concurrency is proven deterministically, not by a brittle timing threshold;
13. cache entries, if any, cannot leak across project keys;
14. Task 007–008 isolation/read-surface regressions remain green.

Also run relevant Ruff / `py_compile` / GRACE lint checks and `git diff --check`.

## Required result

Commit and push the implementation.

Then create:

`docs/work/agent_exchange/outbox/009_SUBMISSION.md`

Keep it short and include:

- implementation commit SHA;
- cross-project overview/events/logs/search/diagnostics/attention work completed;
- pagination/continuation strategy used for global events;
- resilience/concurrency/coverage proof summary;
- tests/checks run and results;
- any limitation or deviation from TZ03.

Do not start Task 010 until reviewer returns `ACCEPT 009`.