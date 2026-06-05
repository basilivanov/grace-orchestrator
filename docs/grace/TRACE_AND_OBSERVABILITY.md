# Trace and Observability API

Date: 2026-06-05
Status: shipped (W4 of `source/codex/tz-api-first-cleanup-waves-w0-w11.md`)

## What this surface replaces

This document describes the OpenAPI trace surface that replaces the deleted
`grace trace --packet/--feature/--wave` CLI from W2 and the ad-hoc DB
queries that the dashboard and acceptance tests used to perform.

```text
GET /api/trace/packets/{packet_id}   -> packet state, runs, timeline, last failure
GET /api/trace/features/{feature_id} -> feature → waves → packets grouped summary
GET /api/trace/runs/{run_id}         -> one run with its full result_json
GET /api/trace/search?q=...          -> cross-entity substring search
GET /api/events                      -> event log with filtering + pagination
GET /api/diagnostics/state           -> system-state snapshot
```

## Why this is an API, not a CLI

- Agents and humans can discover it through `/openapi.json`.
- Dashboard, IDE plugins, and external UIs reuse the same endpoints
  without re-implementing SQL aggregation.
- All queries go through services (`TraceService`, `EventQueryService`,
  `DiagnosticsService`) — routers contain no DB aggregation loops.

## Endpoint contracts

### `GET /api/trace/packets/{packet_id}`

```json
{
  "data": {
    "packet_id": "pkt_...",
    "feature_id": "feat_...",
    "wave_id": "wave_...",
    "title": "...",
    "slug": "...",
    "current_state": "running",
    "attempt_count": 1,
    "max_attempts": 3,
    "runs": [
      {
        "run_id": "...",
        "run_number": 1,
        "status": "rejected",
        "executor_id": "...",
        "worker_id": "...",
        "started_at": "2026-06-05T10:00:00Z",
        "finished_at": "2026-06-05T10:00:01Z",
        "duration_ms": 1234,
        "evidence_path": "/tmp/..."
      }
    ],
    "timeline": [
      {
        "timestamp": "2026-06-05T10:00:00Z",
        "event_type": "packet_claimed",
        "entity_type": "packet",
        "entity_id": "pkt_...",
        "payload": {...},
        "trace_id": "trace-001"
      }
    ],
    "last_failure": {
      "stage": "acceptance",
      "summary": "...",
      "blocking_issues": ["..."]
    },
    "recommended_next_action": "retry | review | manual | merge | none"
  }
}
```

`recommended_next_action` is computed by `TraceService._recommend`:

| condition                                          | action   |
|----------------------------------------------------|----------|
| `state == "merged"`                                | `none`   |
| no `last_failure`                                  | `none`   |
| `attempt_count >= max_attempts`                    | `manual` |
| otherwise (e.g. `RUNNING`, `READY`, `REJECTED`)    | `retry`  |

### `GET /api/trace/features/{feature_id}`

Returns the feature summary + waves + per-wave packet groups + the
feature's own event timeline.

### `GET /api/trace/runs/{run_id}`

Returns one `PacketRun` row, with the full `result_json` exposed as
`acceptance_verdict` and `acceptance_summary` for quick inspection.

### `GET /api/trace/search?q=...`

Substring search over `Packet.id`, `Packet.title`, `Feature.title`,
`PacketRun.executor_id`. MVP — no full-text engine. `q` is required
(non-empty); `limit` defaults to 25, capped at 200.

### `GET /api/events`

Query parameters:

| param         | type    | description                                |
|---------------|---------|--------------------------------------------|
| `entity_id`   | string  | exact match on `events.entity_id`          |
| `entity_type` | string  | exact match on `events.entity_type`        |
| `event_type`  | string  | exact match. `recovery_*` → `LIKE` match.  |
| `trace_id`    | string  | exact match                                |
| `since`       | ISO8601 | inclusive lower timestamp bound            |
| `until`       | ISO8601 | inclusive upper timestamp bound            |
| `limit`       | int     | 1..1000, default 100                       |
| `offset`      | int     | >= 0, default 0                            |

Response includes `total`, `limit`, `offset`, `events[]` (most recent
first).

### `GET /api/diagnostics/state`

Returns counts:

```json
{
  "data": {
    "packets_by_state": {"draft": 0, "ready": 4, "running": 1, ...},
    "active_leases": 1,
    "workers": {"total": 2, "idle": 1, "busy": 1},
    "runs_total": 17,
    "features_by_status": {"IN_PROGRESS": 3, "DONE": 1}
  }
}
```

## Service rules

```text
- TraceService.get_packet_trace / get_feature_trace / get_run_trace / search
  are the only SQL-aggregation points. Routers call them and shape the
  response.
- EventQueryService.query is the only place that builds an Event query
  with filters; new filters land there, not in the router.
- DiagnosticsService.get_state is the only place that computes the
  /api/diagnostics/state snapshot. New counters land there.
- No router file under api/routers/ contains a `db.query(...)` call
  outside a service wrapper (GraceLint GRC104 enforces this in W10).
```

## Acceptance tests

`tests/grace_control/api/test_w4_trace_api.py` covers:

1. packet trace returns state + runs + timeline + last_failure + recommendation;
2. feature trace groups packets by wave;
3. search by packet title and by run executor_id;
4. events endpoint supports filtering (entity_id, event_type) and pagination;
5. diagnostics/state returns correct counts;
6. OpenAPI document contains every new path;
7. 404 for missing packet / feature / run.

## Migration status

The W2-deprecated `grace trace --packet/--feature/--wave` CLI command is
**fully replaced** by these endpoints. Any consumer that used the old
CLI should switch to:

```text
grace trace --packet p1          -> GET /api/trace/packets/p1
grace trace --feature f1         -> GET /api/trace/features/f1
grace trace --wave w1            -> GET /api/trace/search?q=w1   (or aggregate via /features)
```

`docs/grace/CLI_DEPRECATION_INVENTORY.md` row `trace --packet/--feature/--wave`
is now `done (W2)` with this wave as the API backing.
