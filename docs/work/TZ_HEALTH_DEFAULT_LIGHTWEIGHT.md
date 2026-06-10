# TZ: Make `/health` the default lightweight liveness endpoint

Date: 2026-06-10
Status: ready for coder
Priority: P0 stabilization follow-up
Scope: small API compatibility hardening patch

## 1. Problem

The project now has separate health endpoints:

```text
/health/liveness  -> lightweight process liveness
/health/readiness -> readiness / DB initialized
/health           -> legacy full diagnostic
/health/full      -> deep lifecycle diagnostic
```

This fixed the known watchdog/runner issue after they were moved to `/health/liveness`.

However, keeping `/health` as a heavy diagnostic endpoint is still risky because `/health` is the default path used by many tools and operators by convention:

```text
Docker HEALTHCHECK
Kubernetes livenessProbe examples
nginx / load balancer checks
uptime monitors
curl smoke scripts
manual operator checks
third-party process supervisors
```

A default `/health` endpoint should be safe to call frequently and should never trigger DB work or lifecycle cleanup.

## 2. Goal

Make `GET /health` a lightweight, DB-free, side-effect-free liveness endpoint.

Keep the existing heavy diagnostic behavior available under an explicit non-default path.

## 3. Required endpoint behavior

### 3.1 `GET /health`

Must become the default lightweight liveness endpoint.

Required behavior:

- HTTP 200 when the API process is alive;
- response body should be stable and minimal;
- no DB access;
- no worker lookup;
- no packet/lease lookup;
- no cleanup;
- no lifecycle mutation;
- no supervisor socket calls;
- no expensive diagnostics;
- `include_in_schema=False` as before.

Recommended response:

```json
{"status": "ok"}
```

Optional cheap fields are allowed, e.g. service name, version, pid, but keep it minimal.

### 3.2 `GET /health/liveness`

Must remain available as an alias of `/health`.

It should return the same liveness payload as `/health`.

### 3.3 `GET /health/readiness`

Keep existing readiness behavior:

- HTTP 200 when API is initialized enough to serve requests;
- HTTP 503 when not ready;
- no heavy DB queries;
- no lifecycle mutation.

### 3.4 Full/deep diagnostics

Move or keep the old DB-backed full health behavior under an explicit path, for example:

```text
/health/full
```

If `/health/full` already exists and has a different lifecycle diagnostic payload, choose one of the following:

Option A, preferred:

```text
/health/full              -> legacy check_health() workers/queue/leases diagnostic
/api/admin/lifecycle/health/full -> existing lifecycle deep health
```

Option B, acceptable if less invasive:

```text
/health/diagnostic        -> legacy check_health() workers/queue/leases diagnostic
/health/full              -> existing lifecycle deep health unchanged
```

The important rule: heavy diagnostics must not live at `/health`.

## 4. Non-goals

Do not rewrite the worker lifecycle.
Do not change packet state machine semantics.
Do not change watchdog behavior except if tests need path expectations updated.
Do not add direct SQLite mutations.
Do not add broad process-kill commands.
Do not implement systemd, Docker, cgroup, or OOM hardening in this task.
Do not remove `/health/liveness` because it is already used by watchdog/runner.

## 5. Files likely involved

```text
src/grace_control/api/routers/health.py
src/grace_control/core/health.py
src/grace_control/api/routers/lifecycle.py
src/grace_control/api/app_factory.py
tests/grace_control/api/test_auth.py
tests/grace_control/api/test_health.py  # or nearest existing API test file
scripts/api_watchdog.py
tests_live/runner/wave_resume_runner.py
```

Do not modify more than needed.

## 6. Implementation guidance

### 6.1 Health router

Recommended shape:

```python
@router.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}


@router.get("/health/liveness", include_in_schema=False)
async def liveness() -> dict:
    return {"status": "ok"}
```

Avoid importing `check_health` into the lightweight route path.

If possible, use a tiny helper to avoid duplication:

```python
def _liveness_payload() -> dict:
    return {"status": "ok"}
```

### 6.2 Legacy diagnostic route

If keeping legacy `check_health()`, expose it explicitly:

```python
@router.get("/health/diagnostic", include_in_schema=False)
async def health_diagnostic() -> dict:
    return await check_health()
```

or use `/health/full` if that does not conflict with existing lifecycle route behavior.

Document clearly that this endpoint is diagnostic and DB-backed, not liveness-safe.

### 6.3 Watchdog and live runner

They may continue using `/health/liveness`.

Do not move them back to `/health` unless tests intentionally verify both are equivalent lightweight endpoints.

## 7. Tests required

Add/update tests proving:

### 7.1 `/health` is lightweight

Test that `GET /health` returns:

```json
{"status": "ok"}
```

and HTTP 200.

### 7.2 `/health` does not call DB-backed `check_health()`

Add a regression test such as:

```python
monkeypatch.setattr("grace_control.core.health.check_health", raising_function)
resp = client.get("/health")
assert resp.status_code == 200
assert resp.json()["status"] == "ok"
```

If import binding makes this hard, test the actual router module dependency instead. The goal is to prevent accidental re-coupling.

### 7.3 `/health/liveness` remains lightweight

Same expectations as `/health`.

### 7.4 Legacy diagnostic remains reachable

If legacy diagnostic is moved to `/health/diagnostic` or `/health/full`, assert that endpoint still returns the old diagnostic shape, e.g. fields like:

```text
status
workers
queue_depth
running
timestamp
```

Adjust field expectations to the actual chosen route.

### 7.5 Auth behavior

When auth is enabled, `/health`, `/health/liveness`, and `/health/readiness` should remain public.

For heavy diagnostics, decide intentionally:

- either public for backward compatibility;
- or auth-protected if mounted under admin/diagnostics.

Document the choice in the test.

## 8. Acceptance criteria

The patch is accepted when:

1. `GET /health` is lightweight and DB-free.
2. `GET /health/liveness` remains lightweight and DB-free.
3. `GET /health/readiness` still works.
4. Old diagnostic health information remains available under an explicit non-default route.
5. No state mutation happens when calling `/health`.
6. Watchdog and live runner still use `/health/liveness` or another lightweight endpoint.
7. Tests cover the default `/health` convention.
8. No new broad process cleanup or direct DB side-channel is introduced.

## 9. Suggested verification commands

```bash
pytest tests/grace_control/api -q
pytest tests/grace_control -q
```

Runtime smoke:

```bash
curl -s http://127.0.0.1:8042/health
curl -s http://127.0.0.1:8042/health/liveness
curl -s -i http://127.0.0.1:8042/health/readiness
curl -s http://127.0.0.1:8042/health/diagnostic || true
curl -s http://127.0.0.1:8042/health/full || true
```

Expected:

```text
/health           -> 200 {"status":"ok"}
/health/liveness  -> 200 {"status":"ok"}
/health/readiness -> 200 ready or 503 not ready depending on DB init
heavy diagnostic  -> available only on explicit diagnostic/full route
```

## 10. Developer notes

This is a convention hardening patch.

The previous blocker was fixed by moving known operational consumers to `/health/liveness`. This task prevents future accidental breakage from default tooling that assumes `/health` is safe liveness.

Keep it small. Do not reopen the broader process isolation or worker recovery design here.
