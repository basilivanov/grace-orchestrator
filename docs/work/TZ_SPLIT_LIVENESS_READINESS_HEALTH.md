# TZ: Split Liveness / Readiness / Health endpoints

Separate the monolithic `/health` into three Kubernetes-style probes.

## Motivation

Kubernetes (and other orchestrators) expect three distinct probe types:

| Probe | Purpose | Behaviour |
|-------|---------|-----------|
| **liveness** | "Is the process alive?" | 200 / 503 immediately, no DB |
| **readiness** | "Can it serve traffic?" | 200 / 503 after DB init |
| **health** (full) | "What's the system state?" | Full diagnostic payload |

Currently `/health` returns a full diagnostic payload (workers, queue depth, etc.) which is
fine for display but inappropriate for liveness/readiness probes that expect a fast 200/503.

## Spec

### 1. `GET /health/liveness` — liveness probe

- **Purpose**: Lightweight "process up" check.
- **Implementation**: Returns `{"status": "ok"}` with 200 immediately. No DB access, no async.
- **Fast**: No DB queries, no worker lookups.
- **Contract**:
  ```json
  HTTP 200
  {"status": "ok"}
  ```
- **Public**: No auth required (same as current `/health`).
- **OpenAPI**: `include_in_schema=False`.

### 2. `GET /health/readiness` — readiness probe

- **Purpose**: "Is the API fully initialized and able to serve?"
- **Implementation**: Returns 200 if DB is initialized (`init_db` called, engine non-null).
  Returns 503 if DB is not initialized.
- **Fast**: Single boolean check, no DB queries.
- **Contract**:
  ```json
  HTTP 200 / 503
  {"status": "ready" | "not ready"}
  ```
- **Public**: No auth required.
- **OpenAPI**: `include_in_schema=False`.

### 3. `GET /health` — full health (unchanged)

- **Purpose**: Full diagnostic snapshot for monitoring / admin UI.
- **Implementation**: Keep the current `check_health()` logic — workers, queue depth, running
  count, timestamp.
- **Contract**: Same as today.
- **Public**: No auth required.
- **OpenAPI**: `include_in_schema=False`.

### 4. `GET /health/full` — deep health (unchanged)

Already exists in `lifecycle.py`. Keep as-is.

## File changes

### `src/grace_control/api/routers/health.py`

Add two new routes before the existing `/health`:

```python
@router.get("/health/liveness", include_in_schema=False)
async def liveness() -> dict:
    return {"status": "ok"}

@router.get("/health/readiness", include_in_schema=False)
async def readiness() -> dict:
    from grace_control.db import engine
    if engine is None:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}
```

### `src/grace_control/api/auth.py`

Keep both `/health/liveness` and `/health/readiness` in `_PUBLIC_PATHS` (inherited
via the regex or exact path).

### Tests

Verify:
- `GET /health/liveness` → 200 `{"status": "ok"}`
- `GET /health/readiness` → 200 `{"status": "ready"}` when initialized, 503 when not
- `GET /health` → 200 + full payload (unchanged)
