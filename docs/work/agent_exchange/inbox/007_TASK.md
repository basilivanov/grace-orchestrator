# Task 007 — Admin Control Center Stage 01: Project Hub Foundation

## Source of truth

Implement:

`docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_01_PROJECT_HUB_FOUNDATION.md`

Read for context/invariants:

- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_MASTER.md`
- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_00_INDEX.md`

Current code on `main` is authoritative where older docs differ.

## Objective

Implement only Control Center **Stage 01**: the multi-project backend foundation.

At completion, one Admin Hub must be able to discover multiple configured projects, build immutable/request-scoped project contexts, communicate with independent project-local GRACE APIs concurrently, expose the required `/api/admin-hub/*` project/health JSON surface, and remain usable when one project is unavailable.

Do **not** implement later-stage cross-project events/logs/files/explorers or a major Admin UI redesign.

## Reviewer constraints

1. Preserve the required topology: one Hub above project-local GRACE runtimes. The Hub must not open another project's SQLite DB or private runtime tree directly.
2. Projects may run under different Unix users. `unix_user` is registry/display metadata in this stage; do not implement request-time `sudo -u`, impersonation, or direct cross-user filesystem access from the Hub.
3. Never select a project by mutating process-global state (`GRACE_PROJECT_ROOT`, global settings, DB binding, module-global service/project objects, `current_project`, etc.). Project selection must be explicit via immutable/request-scoped context/key.
4. Implement a validated project registry with unique safe keys, non-empty project-root identity, enabled/disabled state, display metadata and exactly one usable transport. Duplicate keys must fail configuration.
5. Implement immutable `ProjectContext` (or equivalent) and make project-scoped services receive context/key explicitly.
6. Implement a reusable per-project API client with bounded connect/read timeouts, normalized errors and safe JSON decoding. No silent retries for mutations.
7. Implement Hub composition/fan-out in a service layer, not in routers/templates. Cross-project health fan-out must be concurrent and bounded.
8. Fail isolated: timeout, offline or malformed response from project A must not break healthy project B in ALL PROJECTS responses.
9. Add project-local identity/readiness comparison. Registry/runtime identity mismatch must surface as degraded/misconfigured; never silently rewrite registry identity.
10. Add the separate Hub API namespace required by TZ01:
    - `GET /api/admin-hub/projects`
    - `GET /api/admin-hub/projects/{project_key}`
    - `GET /api/admin-hub/projects/{project_key}/health`
    - `GET /api/admin-hub/health`
11. Disabled projects remain listable but are not remotely queried by default fan-out.
12. Browser-facing DTOs must not expose transport credentials, tokens or other secrets. Endpoint display must be safe/masked where needed.
13. Preserve all existing `/admin` and `/api/admin/*` single-project behavior and tests. Do not force existing AdminAggregationService onto a cross-project/global DB abstraction.
14. Use at least two independent fake/test project APIs with different identities for isolation tests. Do not fake multi-project isolation by pointing both contexts at one global settings object.
15. Keep changes bounded to Stage 01. Small shared primitives required by this stage are fine; speculative Stage 02+ implementation is not.

## Required tests / acceptance proof

At minimum prove:

1. registry parses two valid projects;
2. duplicate project key fails clearly;
3. invalid key/path/transport configuration fails clearly;
4. disabled project is listed without remote request by default;
5. concurrent requests for two projects resolve different immutable contexts with no leakage;
6. one project timeout/offline does not break another project response;
7. cross-project fan-out is concurrent rather than serial;
8. identity mismatch is degraded/misconfigured, not silently accepted;
9. browser DTOs do not leak transport secrets;
10. existing single-project Admin API/UI regressions remain green.

Also run relevant Ruff / compile / project lint checks and `git diff --check`.

## Required result

Commit and push the implementation.

Then create:

`docs/work/agent_exchange/outbox/007_SUBMISSION.md`

Keep it short and include:

- implementation commit SHA;
- registry/context/client/Hub API work completed;
- tests/checks run and results;
- resilience/isolation proof summary;
- any limitation or deviation from TZ01.

Do not start Task 008 until reviewer returns `ACCEPT 007`.
