# TZ: Split liveness/readiness health checks to stop false API restarts

Date: 2026-06-10
Status: ready for coder
Priority: P0 live-test unblocker
Scope: small stabilization patch, no control-plane rewrite

## 1. Problem

Live runner intermittently sees:

```text
URL error on GET /api/packets/...: [Errno 111] Connection refused
URL error on GET /health: [Errno 111] Connection refused
API not ready, retrying...
API recovered
```

Watchdog log shows API restarts:

```text
[watchdog] API down at 12:36:52
[watchdog] Restarted PID ...
[watchdog] API down at 12:39:21
[watchdog] Restarted PID ...
```

Kernel OOM log is empty:

```bash
journalctl -k --since "1 hour ago" | grep -Ei 'oom|out of memory|killed process'
# no output
```

Therefore this incident is not proven to be a kernel OOM kill. Current suspicion: watchdog uses `/health` as liveness, but `/health` performs DB-dependent and state-mutating work. During live worker activity SQLite/DB contention, slow worker cleanup, or health-side effects can make watchdog decide the API is down and restart it.

Current `/health` path:

```text
src/grace_control/api/routers/health.py
  GET /health -> grace_control.core.health.check_health()

src/grace_control/core/health.py
  check_health() opens DB
  reads workers
  detects dead workers
  mutates packet state RUNNING -> READY
  mutates worker status active -> dead
  deletes leases
  counts ready/running packets
```

This mixes three responsibilities:

1. Liveness: is the API process alive?
2. Readiness/diagnostics: is DB/queue/worker state healthy?
3. Lifecycle cleanup: release dead workers/leases.

For watchdog/liveness, only #1 is allowed.

## 2. Goal

Make API liveness cheap, side-effect-free, and independent of DB/worker state, so watchdog does not restart API during normal worker activity.

Do this without rewriting the orchestrator, backend, worker, packet lifecycle, or agent execution pipeline.

## 3. Non-goals

Do not implement systemd hardening in this task.
Do not modify OOMScoreAdjust, zram, swap, cgroups, or Linux users.
Do not replace OpenCode, LiteLLM, or the execution backend.
Do not rewrite worker lease logic.
Do not add broad process cleanup commands such as `pkill`, `killall`, `fuser -k`, or `systemctl restart`.
Do not change packet execution semantics except where tests require adapting to the new health endpoint split.

## 4. Required behavior

### 4.1 `/health` must become pure liveness

`GET /health` must:

- not open the DB;
- not query workers/packets/leases;
- not mutate any state;
- not perform cleanup;
- return quickly even while worker is busy;
- be excluded from OpenAPI as before;
- return HTTP 200 with a minimal stable JSON body.

Recommended response:

```json
{
  "status": "ok",
  "service": "grace-control-plane"
}
```

Optional fields are allowed if they are cheap and side-effect-free, e.g. timestamp, version, pid.

### 4.2 Move current deep health behavior out of `/health`

Move the current DB-backed `check_health()` behavior to a new endpoint, for example:

```text
GET /api/diagnostics/health
```

or:

```text
GET /api/diagnostics/health-deep
```

Use the name that best fits the existing diagnostics router style.

This endpoint may call the existing DB-backed logic, but it must not be used by watchdog as liveness.

### 4.3 Prefer separating cleanup from diagnostics if small enough

Best version:

```text
/health                         -> pure liveness, no DB, no side effects
/api/diagnostics/health         -> DB-backed diagnostics, read-only if possible
/api/diagnostics/cleanup-dead-workers or existing lifecycle path -> state mutation cleanup
```

If separating cleanup is too large for this patch, keep the old mutation behavior only behind the new diagnostics/deep endpoint and clearly document it. The P0 requirement is that `/health` must not mutate anything.

### 4.4 Watchdog must use only liveness

Any local watchdog script or supervisor helper that checks API availability must call the new lightweight `/health`.

If `scripts/api_watchdog.py` exists only in the exported runtime but not in repository, document that runtime watchdog must continue to call `/health` after this patch.

Do not make watchdog call DB-backed diagnostics.

## 5. Files likely involved

Known files:

```text
src/grace_control/api/routers/health.py
src/grace_control/core/health.py
src/grace_control/api/routers/diagnostics.py
src/grace_control/api/app_factory.py
```

Potential tests:

```text
tests/grace_control/api/test_health.py
tests/grace_control/api/test_diagnostics.py
tests_live/runner/wave_resume_runner.py
```

Use existing test layout if exact filenames differ.

## 6. Implementation guidance

### 6.1 Keep health router small

Suggested structure:

```python
@router.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok", "service": "grace-control-plane"}
```

Do not import `get_db` or `check_health` into `api/routers/health.py` after this change.

### 6.2 Rename old function if helpful

The current `check_health()` name is misleading if it mutates DB state. Prefer one of:

```python
check_deep_health()
check_worker_health()
check_health_with_worker_cleanup()
```

If renaming is too invasive, keep the function name but only call it from diagnostics and add a comment warning that it is not liveness-safe.

### 6.3 Preserve current deep response shape where possible

The old deep health response contains:

```json
{
  "status": "healthy|degraded|unhealthy",
  "workers": {"active": 0, "idle": 0, "dead": 0},
  "queue_depth": 0,
  "running": 0,
  "timestamp": "...Z"
}
```

Keep this shape on the new diagnostics endpoint unless tests force otherwise.

## 7. Tests required

Add or update tests to prove the split.

### 7.1 `/health` liveness test

Assert:

- `GET /health` returns 200;
- response contains `status == "ok"`;
- no DB setup is required;
- no worker rows are required;
- endpoint does not mutate packets/workers/leases.

### 7.2 Health router import boundary test

Add a lightweight regression test that prevents `/health` from depending on DB-backed health logic.

Acceptable options:

- monkeypatch `grace_control.core.health.check_health` to raise and assert `/health` still returns 200;
- or inspect/source-test that `api/routers/health.py` does not import `get_db` and does not call `check_health`.

Prefer behavioral monkeypatch if easy.

### 7.3 Deep diagnostics test

Assert new diagnostics endpoint returns old deep health shape and can still report workers/queue/running.

If the old behavior mutates dead workers, either:

- test that behavior explicitly on diagnostics endpoint; or
- if cleanup was separated, test cleanup endpoint separately.

### 7.4 Live runner compatibility

Run at least the targeted scenario:

```bash
PYTHONPATH=. GRACE_LIVE_AGENT_TESTS=1 GRACE_DEV_TOOLS_ENABLED=1 GRACE_FAST_FAIL=1 \
  python3 -u tests_live/runner/wave_resume_runner.py \
    --scenario backend-1w \
    --api-url http://127.0.0.1:8042 \
    --source-dir . \
    --target-dir /tmp/grace-live-test \
    --timeout 900 \
    --keep-artifacts
```

Acceptance is not necessarily that the agent completes the business task on first try. Acceptance for this patch is:

- API must not be restarted by watchdog because `/health` is slow/DB-blocked;
- runner must not see repeated `Connection refused` on `/health` during normal worker execution;
- if agent fails, failure is recorded as packet/agent failure, not API process death.

## 8. Acceptance criteria

Patch is accepted when all are true:

1. `/health` is DB-free, side-effect-free, and returns 200 quickly.
2. Current DB-backed worker/queue health information is still available under diagnostics/deep endpoint.
3. No lifecycle cleanup is triggered by `/health`.
4. Existing OpenAPI/API-first architecture remains intact.
5. Unit tests cover liveness split.
6. Target live runner no longer causes watchdog API restarts due to `/health` probe.
7. No broad process-kill commands are introduced.

## 9. Suggested verification commands

```bash
pytest tests/grace_control/api -q
pytest tests/grace_control -q
```

Runtime check:

```bash
curl -s http://127.0.0.1:8042/health
curl -s http://127.0.0.1:8042/api/diagnostics/health || true
```

Watchdog evidence:

```bash
tail -200 /tmp/grace-watchdog.log
journalctl -k --since "30 min ago" | grep -Ei 'oom|out of memory|killed process' || true
```

## 10. Developer notes

This is a stabilization patch. Keep it small.

The goal is to unblock internal live tests and normal auto-loop work. Do not use this task as an opportunity to redesign the process supervisor, agent harness, OpenCode backend, or worker state machine.
