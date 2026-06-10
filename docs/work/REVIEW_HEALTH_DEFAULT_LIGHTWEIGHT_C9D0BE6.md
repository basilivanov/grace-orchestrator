# Review: default lightweight `/health` (`c9d0be6`)

Date: 2026-06-10
Reviewer: ChatGPT
Commit reviewed: `c9d0be6fb958b526052ac107b1eb86c71d5193c5`
Task: `docs/work/TZ_HEALTH_DEFAULT_LIGHTWEIGHT.md`

## Verdict

**ACCEPTED.**

This patch satisfies the P0 goal: the conventional `GET /health` endpoint is now lightweight, DB-free, and side-effect-free. The legacy DB-backed diagnostic behavior remains available through an explicit endpoint: `GET /health/diagnostic`.

The full test suite result reported by implementation is acceptable:

```text
889 passed, 0 failed
```

## What was reviewed

Files inspected:

```text
src/grace_control/api/routers/health.py
src/grace_control/api/auth.py
tests/grace_control/api/test_health.py
tests/test_db_schema.py
```

## Positive findings

### 1. `/health` is now lightweight

`GET /health` now returns the shared liveness payload directly:

```python
@router.get("/health", include_in_schema=False)
async def health() -> dict:
    return _liveness_payload()
```

The payload is minimal:

```python
def _liveness_payload() -> dict:
    return {"status": "ok"}
```

This satisfies the main requirement: `/health` is safe for Docker, Kubernetes, load balancers, uptime monitors, and simple operator scripts.

### 2. `/health/liveness` remains a lightweight alias

`GET /health/liveness` now uses the same helper as `/health`:

```python
@router.get("/health/liveness", include_in_schema=False)
async def liveness() -> dict:
    return _liveness_payload()
```

This keeps existing watchdog/live-runner usage valid while also making the default `/health` convention safe.

### 3. Legacy diagnostic behavior was preserved explicitly

The old DB-backed `check_health()` behavior is no longer behind `/health`. It was moved to:

```text
GET /health/diagnostic
```

Implementation:

```python
@router.get("/health/diagnostic", include_in_schema=False)
async def health_diagnostic() -> dict:
    return await check_health()
```

This is the right tradeoff: old diagnostic information remains reachable, but only through an explicit diagnostic path.

### 4. Readiness endpoint remains separate

`GET /health/readiness` remains available and returns 503 when the DB engine is not initialized:

```python
from grace_control.db import engine
if engine is None:
    raise HTTPException(status_code=503, detail="not ready")
return {"status": "ready"}
```

This keeps liveness/readiness/diagnostics properly separated.

### 5. Public auth behavior is consistent

`AuthMiddleware` now treats all intended health endpoints as public:

```python
if path in ("/health", "/health/liveness", "/health/readiness", "/health/diagnostic"):
    return True
```

This matches the implementation note: `/health/diagnostic` is public for backward compatibility.

### 6. Tests cover the important behavior

New tests cover:

- `/health` returns `{"status": "ok"}`;
- `/health/liveness` returns `{"status": "ok"}`;
- `/health/readiness` returns 200 when DB initialized;
- `/health/readiness` returns 503 when DB engine is missing;
- `/health/diagnostic` returns legacy diagnostic fields.

## Minor notes / non-blocking issues

### Minor 1 — Typo in health router comment

The comment says:

```text
DEB-backed, NOT safe for frequent polling.
```

It should be:

```text
DB-backed, NOT safe for frequent polling.
```

Not a blocker.

### Minor 2 — `/health` regression test monkeypatch is weaker than intended

The test monkeypatches:

```python
grace_control.core.health.check_health = raiser
```

But `health.py` imports `check_health` directly:

```python
from grace_control.core.health import check_health
```

Because of that direct import, monkeypatching `grace_control.core.health.check_health` does not necessarily prove that the router-bound `check_health` symbol is not used. In the current implementation `/health` clearly does not call it, so this is not a blocker.

If improving later, monkeypatch the router symbol directly:

```python
import grace_control.api.routers.health as health_router
monkeypatch.setattr(health_router, "check_health", raiser)
```

Then assert `/health` still returns 200.

### Minor 3 — `test_health.py` manually mutates global DB engine

`test_readiness_503_when_no_db` sets:

```python
db_mod.engine = None
```

and restores it in `finally`, which is acceptable but brittle. Prefer pytest `monkeypatch` in future cleanup.

Not a blocker because the test restores state and the full suite passes.

## Acceptance criteria check

| Criterion | Status |
|---|---|
| `GET /health` lightweight and DB-free | PASS |
| `GET /health/liveness` remains lightweight | PASS |
| `GET /health/readiness` still works | PASS |
| Old diagnostic health remains available explicitly | PASS (`/health/diagnostic`) |
| No state mutation on `/health` | PASS |
| Operational probes can keep using liveness | PASS |
| Tests cover default `/health` convention | PASS |
| No direct DB side-channel added | PASS |

## Final decision

Accept this patch.

Recommended next step: run the live scenario again and verify operational behavior rather than unit tests only:

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

Watchdog evidence to check after the run:

```bash
tail -200 /tmp/grace-watchdog.log
journalctl -k --since "30 min ago" | grep -Ei 'oom|out of memory|killed process' || true
```

Expected result: no false API restarts caused by health checks.
