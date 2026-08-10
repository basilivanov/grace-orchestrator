# TZ 03 — Cross-project observability aggregation

Depends on Stages 01-02.

## Objective

Add Hub-level aggregation for the data an operator needs across projects: project overview, events, logs, search and diagnostics.

This stage builds JSON/service contracts. The full explorer UI comes later.

## 1. AdminCrossProjectService

Implement a Hub service that fans out to selected enabled projects via `ProjectClient`.

Conceptual methods:

```text
get_projects_overview()
query_events(...)
query_logs(...)
search(...)
get_diagnostics(...)
```

Never put fan-out loops and merge/sort logic directly in Jinja routers.

Every returned row must carry `project_key` and preferably `project_name`.

## 2. Cross-project overview

Add:

```text
GET /api/admin-hub/overview
```

Return per-project cards plus aggregate counts.

Per-project minimum:

```text
key/name
status online/degraded/offline/disabled
runtime identity/version/code SHA
workers active/total
packets by state
active ordinary leases
active parallel leases
merge lease owner/packet if present
latest event
latest error/attention item
state/worktree/evidence size if project returns summaries
fetched_at/error
```

Aggregate totals must not pretend offline projects are zeros. Include coverage metadata such as:

```json
{
  "projects_total": 4,
  "projects_responded": 3,
  "projects_failed": 1
}
```

## 3. Global Events query

Add:

```text
GET /api/admin-hub/events
```

Filters:

```text
project (one/many/all)
entity_id
entity_type
event_type
trace_id
since
until
limit
cursor or offset strategy
```

Requirements:

- fan out only to requested/enabled projects;
- merge event rows by timestamp descending;
- preserve full payload for drill-down;
- include per-project errors separately;
- stable pagination semantics documented and tested.

Because each project owns its own pagination, do not implement incorrect global pagination by asking each project for exactly `limit` then discarding arbitrary rows without a continuation strategy. For MVP a bounded per-project fetch + explicit `partial=true`/continuation metadata is acceptable if documented; a proper cursor is preferred.

## 4. Global Logs query

Add:

```text
GET /api/admin-hub/logs
```

Normalize heterogeneous log sources to rows such as:

```json
{
  "project_key": "astro",
  "source": "worker|api|supervisor|packet|stage|agent|acceptance|merge|...",
  "timestamp": "...",
  "level": "INFO",
  "packet_id": "...",
  "run_id": "...",
  "stage_id": "...",
  "worker_id": "...",
  "trace_id": "...",
  "message": "...",
  "raw": "..."
}
```

Not every source has every field; normalize missing values to null/empty.

Filters:

```text
project
source
worker
packet
run
stage
level
trace_id
contains
regex (where project-local API safely supports it)
since
until
tail/cursor
```

Do not make the Hub mount/read project log files directly. Use project-local read APIs from Stage 02.

## 5. Cross-project search

Add:

```text
GET /api/admin-hub/search?q=...
```

Search at minimum over project-local canonical search plus project metadata.

Normalize result kinds:

```text
project
feature
wave
packet
run
stage
worker
trace/event if supported
```

Every result carries a canonical Hub URL target.

Search scope:

```text
all projects
one selected project
```

One failed project appears in `errors`, not as an overall failure.

## 6. Diagnostics aggregation

Add:

```text
GET /api/admin-hub/diagnostics
GET /api/admin-hub/projects/{project_key}/diagnostics
```

Global page aggregates counts only when mathematically valid and always retains per-project snapshots.

Required project snapshot includes the project-local diagnostics from Stage 02, especially:

- effective max concurrency;
- workers;
- packet counts;
- ordinary/parallel/merge leases;
- wait reasons;
- stale-base/integration-recheck metadata summaries;
- system health.

## 7. Attention model

Create one normalized read-only `attention` concept for the Projects dashboard.

Examples:

```text
offline project
DB unhealthy
supervisor/API unhealthy
BLOCKED_FINAL
FAILED
BLOCKED_RECOVERABLE
merge lease stuck/expired-recovery deferred
parallel safety disabled in multi-worker mode
identity mismatch
recent repeated merge/recheck failure
```

Do not invent business state or mutate packets. This is a UI/read-model classification only.

Each item:

```text
severity
project_key
kind
entity_type/entity_id
title
reason
timestamp
detail_url
```

## 8. Ordering and clock assumptions

Projects may have small clock skew. Preserve original project timestamps and project key. Global ordering by timestamp is acceptable, but never rewrite source timestamps to force an order.

## 9. Resilience

Cross-project service must handle independently:

```text
connect error
timeout
HTTP 4xx/5xx
malformed JSON
capability missing
partial project response
```

A project error object must include enough diagnostic context to display without exposing secrets.

## 10. Caching

Short TTL cache is allowed for expensive stable data such as OpenAPI/project metadata. Do not cache active packet/log/event state so aggressively that a 2-5 second operator poll looks stale.

Cache keys always include project key.

## 11. Tests

Required minimum with at least two independent project API fixtures:

1. overview aggregates healthy projects;
2. offline project produces partial result, not 500;
3. aggregate coverage metadata is correct;
4. global events merge ordering and project attribution;
5. event filters are forwarded correctly;
6. pagination/continuation behavior is deterministic;
7. logs from two projects normalize and retain source/project;
8. one malformed log/event response does not corrupt other project results;
9. cross-project search returns canonical project-aware links;
10. diagnostics preserve per-project concurrency/lease state;
11. attention classification flags blocked/offline and ignores healthy idle project;
12. concurrent fan-out avoids serial timeout amplification;
13. cache entries cannot leak across project keys.

## 12. Acceptance

Stage 03 is complete when a JSON client can build the future global Projects, Events, Logs, Search and Diagnostics screens without direct project DB/filesystem access and without one broken project breaking healthy data.
