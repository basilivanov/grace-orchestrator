# Task 013 — Admin Control Center Stage 07: Final Integration and Acceptance

Status: READY

Source of truth:
- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_07_INTEGRATION_ACCEPTANCE.md`
- Admin Control Center master/index documents
- Accepted Tasks 007–012

## Objective

Implement **only Stage 07**: final integrated proof, resilience/security acceptance, operator journeys, regression coverage and delivery documentation for the complete multi-project Admin Control Center.

This stage must test the real production boundaries built in Stages 01–06. Do not replace missing earlier behavior with test-only shortcuts, global DB labels, direct Hub filesystem/DB access or mocked project identity. If an integrated test exposes a defect, fix it at the owning service/UI layer.

## Required implementation

### 1. Real independent two-project topology

Build final acceptance fixtures with at least two genuinely independent projects, each with its own:

- project root;
- SQLite DB;
- state root;
- worktree root;
- real target Git repository;
- project-local API/runtime boundary.

Populate distinct project data and deliberately reuse at least one identical entity ID (for example the same packet ID) in both projects.

The Hub must talk to both via the same project API/client interfaces used in production. Do not model this with one global DB plus project labels.

### 2. Concurrent project isolation

Prove under concurrent Hub requests:

- A returns only A DB/runtime data and B only B data;
- the same packet ID resolves independently in A and B;
- A files/evidence cannot be opened through B;
- A Git cannot be read through B context;
- controls sent to A cannot mutate B;
- caches, if any, are project-key scoped;
- request handling never switches process-global DB/root/settings state.

Include simultaneous/concurrent requests, not only sequential assertions.

### 3. Failure/offline isolation

Exercise connection refused, timeout, HTTP 500, malformed JSON, missing capability and runtime identity mismatch.

Verify the Projects page and healthy project remain usable; global Events/Logs/Search/Diagnostics return partial data with explicit project errors; no stale data is substituted from another project; and mutation to an unavailable/mismatched project is never rerouted.

### 4. End-to-end operator journeys

Automate/smoke at minimum:

A. Healthy parallel work: Projects -> project -> packet -> Pipeline/Stages -> Events -> Logs -> leases/diagnostics -> merged result.

B. Failure diagnosis: Attention -> blocked packet -> blocking decision -> failed StageRun -> stderr/log tail -> raw event payload -> evidence/artifact -> recommended action.

C. Stale-base diagnosis: packet -> base/current HEAD -> stale-base -> integration recheck/evidence -> Git diff -> final state.

D. Cross-project observability: Global Events/Logs/Search -> A+B -> filter B -> open B entity -> browser back to global view.

E. Safe control: retryable/blocked entity -> confirmation -> project-local mutation -> canonical audit -> refreshed state.

### 5. Complete read-surface fixture

Populate one rich project with representative:

- Feature/Wave/Packet;
- PacketRun result JSON;
- StageRun;
- session when capability exists (otherwise explicit unavailable path remains tested);
- Event full payload;
- stdout/stderr/agent logs;
- parsed and raw evidence;
- image, Markdown/text and binary artifacts;
- worktree and Git diff;
- ordinary/parallel/merge lease data;
- stale-base metadata.

Prove each is inspectable through dedicated pretty UI or Raw/API Explorer without SSH or direct DB access from the Hub.

### 6. Dynamic OpenAPI completeness

Add a synthetic project-local GET path that frontend navigation does not hard-code. Prove it appears automatically from `/openapi.json` and its bounded response is inspectable through API Explorer.

Preserve Stage 05/06 same-origin, arbitrary-URL and mutation gates.

### 7. Filesystem and Git security acceptance

With real temp roots/repos prove filesystem denial for traversal, absolute paths, symlink escape, `.env`, private-key/credential patterns, and cross-project roots. Prove large file/tail/binary reads are bounded while allowed evidence/stdout remains readable.

With real Git repos prove tracked-file view, diff/stat, packet/base/integration SHAs, worktrees, malicious ref/path/options rejection, A-via-B denial, and explicit bounded/truncated large diff behavior.

### 8. Final control safety

Prove integrated behavior for:

- read-only user cannot mutate;
- authorized + confirmed control succeeds when valid;
- canonical audit event is visible afterwards;
- timeout/unknown outcome has no automatic retry;
- planned/501 remains unavailable;
- manual merge cannot bypass state, parallel/merge fencing or stale-base protection;
- maintenance cannot delete live/uncertain ownership;
- API Explorer cannot become arbitrary URL, method or shell execution;
- Stage 06 runtime-identity and audit-integrity protections remain intact.

### 9. Browser/UI acceptance

Use the repository's existing frontend acceptance infrastructure where available.

Desktop and mobile smoke must cover Projects, selector/tree, packet tabs, Events/Logs, long JSON/log handling, offline card, control confirmation, back/forward/deep links and HTMX polling without project-context loss.

Include accessibility smoke for keyboard-reachable selectors/tabs/actions and text/non-color status meaning; modal focus/escape where supported by current frontend policy.

Do not replace browser acceptance with CSS-string assertions. Environment-dependent browser tests may explicitly skip only when the existing harness/browser is unavailable; deterministic ASGI/service/security coverage must remain runnable.

### 10. Performance/boundedness smoke

Use representative scale (roughly 10–20 configured projects, several offline, hundreds of packets, thousands of events, large logs/artifact directories) and assert behavior through call counts/overlap/bounds rather than fragile absolute timing.

Prove:

- overview fan-out is concurrent;
- a dead project does not serialize timeouts across all projects;
- overview does not eagerly recursively read evidence/log files;
- heavy explorers paginate/tail/truncate;
- response sizes remain bounded;
- any OpenAPI cache is project-key scoped and short-lived.

### 11. Regression and documentation

Run relevant regressions for Admin v2/HTMX, aggregation, trace/events/diagnostics, ProjectConfig, supervisor/maintenance, packet/worker/merge, safe-parallel execution, filesystem/artifact/log readers, frontend acceptance and migrations/schema if touched.

Update operator documentation for project registration, Hub topology, Unix isolation expectations, per-project API/socket config, offline behavior, filesystem allowed roots, Admin URLs, read/control permissions, OpenAPI policy, maintenance workflow and troubleshooting.

Create the final implementation report:

`docs/work/REPORT_GRACE_ADMIN_CONTROL_CENTER_V3.md`

It must include implementation SHAs, architecture summary, registry format, API additions, security model, tests/results and known limitations.

## Required acceptance criteria

Stage 07 is complete only when all final TZ07 Definition-of-Done items are proven, including:

1. one Hub shows all configured projects;
2. concurrent project data isolation;
3. no request-time global project switching;
4. no direct Hub access to another project's SQLite/private filesystem;
5. complete Feature->Wave->Packet->Run->Stage inspectability;
6. sessions shown or explicitly unavailable;
7. full event payloads and bounded logs/evidence/artifacts/files/Git inspection;
8. lease/wait/stale-base diagnostics and Raw inspector;
9. dynamic OpenAPI discovery;
10. safe domain-backed controls with confirmation/audit;
11. offline/failing project isolation;
12. filesystem/Git/project-context escape prevention;
13. lazy/bounded heavy data;
14. desktop/mobile journeys;
15. relevant existing GRACE regressions green;
16. final operator/report documentation delivered.

## Checks

Run and report at minimum:

- final Stage 07 integration/acceptance suite;
- relevant Task 007–012 acceptance/regression suites;
- existing Admin/auth/events/diagnostics/filesystem/artifact/log/Git/maintenance/supervisor/packet/worker/merge/safe-parallel tests;
- frontend/browser acceptance where the harness is available;
- Ruff on changed/new Python files;
- `python3 -m py_compile` on changed/new Python files;
- applicable `grace_lint.py` checks;
- `git diff --check`.

Do not dismiss a failing existing test as legacy without establishing that it asserts superseded behavior and updating the owning spec/test deliberately.

## Required result

Commit and push the Stage 07 implementation/acceptance/documentation work, then create:

`docs/work/agent_exchange/outbox/013_SUBMISSION.md`

Keep the report concise and include:

- final implementation commit SHA;
- topology/isolation proof;
- offline/failure proof;
- operator journeys/read-surface proof;
- filesystem/Git/control security proof;
- browser/performance smoke results;
- regression/check results;
- path to `docs/work/REPORT_GRACE_ADMIN_CONTROL_CENTER_V3.md`;
- any genuine known limitations.

Do not invent Task 014. Task 013 is the final Admin Control Center stage.