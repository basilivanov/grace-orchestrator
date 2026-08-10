# TZ 07 — Final integration, resilience and acceptance

Depends on Stages 01-06.

## Objective

Prove the complete GRACE Admin Control Center works as a safe multi-project operator console under realistic concurrent/failure conditions and does not regress the existing single-project runtime.

This stage is not a place to paper over missing earlier functionality. Fix defects at the owning service/UI layer and keep the final suite as the integrated proof.

## 1. Required final topology test

Create at least two genuinely independent project fixtures:

```text
Project A
  project_root A
  SQLite DB A
  state root A
  worktree root A
  real target Git repo A
  project API A

Project B
  project_root B
  SQLite DB B
  state root B
  worktree root B
  real target Git repo B
  project API B
```

Use distinct packet/feature data and also deliberately reuse at least one identical entity ID between A and B to prove project namespace isolation.

The Admin Hub talks to both through the same interfaces used in production.

Do not implement the final isolation proof with one global DB and mocked project labels.

## 2. Multi-project isolation proof

Prove concurrently:

- request A returns only A DB/runtime data;
- request B returns only B data;
- same packet ID resolves to different project-specific packet detail correctly;
- files/evidence from A cannot be opened via B project routes;
- Git repo A cannot be read through project B client context;
- controls sent to A cannot mutate B;
- caches are project-key scoped;
- project switching never changes process-global DB/root settings.

Include concurrent requests, not only sequential tests.

## 3. Offline/failure isolation

Exercise a project with:

```text
connection refused
timeout
HTTP 500
malformed JSON
missing capability
project identity mismatch
```

Verify:

- Projects page remains usable;
- healthy project data remains visible;
- global events/logs/search/diagnostics return partial results with explicit errors;
- no stale data from another project is substituted;
- control action to unavailable project is not rerouted.

## 4. End-to-end operator journeys

At minimum automate/smoke the following journeys against the final UI/API:

### Journey A — healthy parallel work

```text
Projects
-> project A
-> running/accepted packet
-> Pipeline/Stages
-> Events
-> Logs
-> lease/diagnostics state
-> merged result
```

### Journey B — failure diagnosis

```text
Projects Attention
-> blocked packet
-> blocking decision
-> failed StageRun
-> stderr/log tail
-> raw event payload
-> evidence/artifact
-> recommended action
```

### Journey C — stale-base diagnosis

```text
packet
-> base SHA/current HEAD
-> stale_base detected
-> integration recheck
-> passed or failed evidence
-> Git diff
-> final state
```

### Journey D — cross-project observability

```text
Global Events/Logs/Search
-> results from A+B
-> filter project B
-> open B packet
-> browser back to global view
```

### Journey E — safe control

```text
blocked/retryable entity
-> control action
-> confirmation
-> project-local mutation
-> audit event
-> refreshed state
```

## 5. Complete read-surface acceptance

For one rich project fixture populate representative data for:

```text
Feature/Wave/Packet
PacketRun result_json
StageRun
session if supported
Event payload_json
stdout/stderr/agent log
parsed evidence
raw evidence JSON
image artifact
Markdown/text artifact
binary artifact
worktree
Git diff
ordinary lease
parallel lease
merge lease metadata
stale-base metadata
```

Prove every item is reachable from either a dedicated pretty view or Raw/API Explorer without SSH/direct DB access.

This is the core completeness acceptance criterion.

## 6. OpenAPI completeness test

Add a synthetic/test project API path that is not hard-coded in frontend navigation.

Verify it appears automatically in the project's API Explorer from `/openapi.json` and a GET response can be inspected.

This proves future API additions are not invisible merely because a dedicated UI has not yet been written.

## 7. Filesystem security acceptance

Using real temp filesystem roots, prove:

```text
../ traversal denied
absolute path denied
symlink escape denied
.env denied
private key/credentials pattern denied
large read bounded
large tail bounded
binary preview bounded
allowed evidence file readable
allowed stage stdout readable
project A root cannot be used via project B
```

No test-only bypass should be present in production path.

## 8. Git security acceptance

Using real Git repos prove:

- tracked file view works;
- diff/stat works;
- packet/base/integration SHAs render;
- worktree listing works;
- malicious ref/path/options input rejected;
- project A Git cannot be queried through B context;
- large diff is bounded with explicit truncation indication.

## 9. Control safety acceptance

Prove:

- read-only user cannot mutate;
- authorized control with confirmation works;
- mutation audit event is visible;
- timeout/unknown outcome does not auto-retry;
- planned unsupported operation remains unavailable;
- manual merge cannot bypass packet state/parallel/merge fencing/stale-base rules;
- maintenance cannot delete live/uncertain worktree;
- API Explorer cannot become arbitrary URL/shell execution.

## 10. UI/browser acceptance

Use current frontend acceptance infrastructure where available.

Desktop and mobile minimum:

- Projects page;
- project selector;
- project tree;
- packet detail tabs;
- Event/Log explorer;
- long JSON/log horizontal/vertical handling;
- offline card;
- confirmation modal;
- back/forward/deep link;
- no project context loss after HTMX polling.

Accessibility smoke:

- keyboard reachable project selector/tabs/actions;
- states have text, not color-only meaning;
- modal focus/escape behavior if current frontend policy supports it.

## 11. Performance smoke

The goal is to prevent obvious N+1/filesystem-scan disasters, not establish a universal benchmark.

Test representative scale, e.g.:

```text
10-20 projects configured
several offline
hundreds of packets in one project
thousands of events
large logs/artifact directories
```

Assertions/instrumentation should prove:

- Projects overview fans out concurrently;
- one dead project timeout does not multiply by project count serially;
- overview does not recursively read all evidence/log files;
- heavy explorer payloads paginate/tail;
- project OpenAPI can be short-TTL cached;
- response remains bounded.

Avoid fragile absolute millisecond thresholds; prefer call counts, overlap instrumentation and generous upper bounds.

## 12. Regression suite

Run relevant existing tests for:

```text
Admin v2 / HTMX
AdminAggregationService
Trace API
Events API
Diagnostics
ProjectConfig
Supervisor/Maintenance
Packet/Worker/Merge APIs touched by controls
safe parallel TZ03-TZ06 regressions
filesystem/artifact/log readers
frontend acceptance
migrations/schema if changed
```

Also run:

```text
Ruff
python3 -m py_compile
applicable grace_lint.py
git diff --check
```

Do not dismiss failing existing tests as legacy without establishing they truly assert superseded behavior and updating the owning spec/test deliberately.

## 13. Documentation

Update operator docs with:

```text
how to register projects
Hub deployment/topology
Unix isolation expectations
per-project API/socket config
offline project behavior
filesystem allowed-root policy
Admin URLs
read-only vs control permissions
OpenAPI Explorer policy
maintenance workflow
troubleshooting
```

Add a final implementation report under `docs/work/` containing:

- implementation SHAs;
- architecture summary;
- project registry format;
- API additions;
- security model;
- tests/checks and results;
- known limitations.

Suggested report:

`docs/work/REPORT_GRACE_ADMIN_CONTROL_CENTER_V3.md`

## 14. Final Definition of Done

ACCEPT only if all are true:

1. one Admin Hub shows all configured projects;
2. project data is isolated under concurrent requests;
3. no request-time global project switching exists;
4. Hub does not directly open other-project SQLite/files;
5. any feature/wave/packet/run/stage can be inspected;
6. sessions are shown or capability-unavailable is explicit;
7. full events and payloads are inspectable;
8. relevant logs can be tailed/filtered;
9. evidence/artifacts/safe operational files can be inspected;
10. Git/worktrees/diffs can be inspected safely;
11. leases/waits/stale-base diagnostics are visible;
12. Raw inspector exposes underlying DTOs;
13. OpenAPI Explorer discovers every project API path;
14. supported controls use domain APIs, confirmation and audit;
15. one offline project does not break the Hub;
16. security tests prevent filesystem/Git/project-context escape;
17. heavy data is lazy/bounded;
18. desktop/mobile operator journeys pass;
19. relevant existing GRACE regressions remain green;
20. final report documents the delivered system.

Not acceptable:

- a cosmetic project selector over a global DB;
- SSH still required for ordinary logs/evidence diagnosis;
- raw API/event/result data hidden;
- arbitrary path/file reader;
- API Explorer capable of arbitrary URL/shell requests;
- cross-project actions without explicit project identity;
- failure of one project causing global Admin 500.
