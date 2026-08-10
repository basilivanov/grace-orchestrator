# Task 008 — Admin Control Center Stage 02: Project Read Surface

## Source of truth

Implement:

`docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_02_PROJECT_READ_SURFACE.md`

Read for context/invariants:

- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_MASTER.md`
- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_00_INDEX.md`

Depends on accepted Task 007 / Control Center Stage 01 implementation. Current code on `main` is authoritative where older docs differ.

## Objective

Implement only Control Center **Stage 02**: make each project-local GRACE runtime a complete, safe read source for the Admin Hub so the Hub does not need direct cross-project SQLite/filesystem/Git access for ordinary diagnostics.

Reuse and extend existing Admin/Trace/Events/Diagnostics/artifact services instead of duplicating canonical read paths. Do **not** build Stage 03 cross-project observability or later global UI/explorers.

## Reviewer constraints

1. Inventory current project-local read APIs before adding new endpoints. Reuse canonical `/api/admin/*`, `/api/trace/*`, `/api/events`, `/api/diagnostics/state`, lifecycle/supervisor and artifact/log surfaces where they already satisfy the requirement.
2. Keep project-local runtime as the security/isolation boundary. Hub code must not directly open another project's SQLite, arbitrary project filesystem, or Git working tree.
3. Extend display-safe project metadata/identity to expose required runtime/config fields where available, including target/base branch, workspace/execution mode, state/worktree roots as metadata, GRACE SHA/version, status/concurrency and parallel/merge/stale-base safety settings. Mask secrets.
4. Complete packet/run/stage raw read models so canonical spec, `scope`, `conflict_keys`, `depends_on`, runs/stages/recovery, worker/model/executor, tokens/cost, base/integration SHAs, wait/failure/recheck metadata and full relevant `result_json` are inspectable.
5. Preserve `/api/events` as canonical event query surface. Ensure required filters/pagination and complete `payload_json` drill-down remain available; do not replace it with a duplicate event store/API.
6. Extend diagnostics as needed for packet/feature/worker/run counts plus ordinary leases, parallel leases, merge lease metadata, effective concurrency, typed waits and base/integration/recheck state. Never expose the full fencing token; only a safe masked/fingerprint identity if needed.
7. Implement filesystem reads through a dedicated project-local service with named server-resolved operational roots. Never accept an arbitrary absolute root/path reader.
8. Filesystem safety must include realpath containment, traversal rejection, symlink-escape rejection, path-based secret deny rules, bounded previews/tails, binary handling and typed expected read errors. Use real temp directories/symlinks in tests.
9. Reuse/extend artifact/evidence readers. Keep previews bounded and preserve existing traversal protections.
10. Add/formalize project-local Git read primitives for branch/HEAD/status/worktrees/commits/changed files/diff/stat using validated refs/paths, bounded output/timeouts and Git-tracked file inspection where appropriate. Reject option injection/path escape. Use a real temp Git repo in tests.
11. Ensure `ProjectClient` can retrieve `/openapi.json`; OpenAPI is the discovery/completeness contract. Do not create a hand-maintained endpoint registry.
12. Add a capability document/normalization surface for optional features. Missing optional functionality must be represented as unavailable capability, not make the project broken.
13. Preserve existing single-project Admin/Trace/Events/Diagnostics behavior and accepted Stage 01 project isolation. Do not introduce process-global project switching.
14. Keep all large reads bounded/lazy. No unbounded logs/files/diffs in memory or API payloads.
15. Keep changes bounded to Stage 02. Do not start global cross-project events/log aggregation, final explorers or major UI redesign.

## Required tests / acceptance proof

At minimum prove:

- packet raw/full `result_json` visibility;
- event full payload plus filter/pagination regression;
- diagnostics exposes parallel/merge lease metadata without full fencing token;
- filesystem allowed-root listing;
- traversal rejection;
- symlink escape rejection;
- secret-path rejection;
- bounded large-text preview and bounded tail;
- binary handling;
- missing/unreadable file returns typed non-500 response where expected;
- existing evidence/artifact normal reads remain green;
- Git changed files/diff/stat on an isolated real temp repository;
- unsafe Git path/ref input rejected;
- OpenAPI retrieval through the project client/API boundary;
- missing optional capability is graceful;
- relevant existing Admin/Trace/Events/Diagnostics and Task 007 regressions remain green.

Also run relevant Ruff / `py_compile` / GRACE lint checks and `git diff --check`.

## Required result

Commit and push the implementation.

Then create:

`docs/work/agent_exchange/outbox/008_SUBMISSION.md`

Keep it short and include:

- implementation commit SHA;
- read-model/filesystem/Git/OpenAPI/capability work completed;
- tests/checks run and results;
- filesystem/Git safety proof summary;
- any limitation or deviation from TZ02.

Do not start Task 009 until reviewer returns `ACCEPT 008`.
