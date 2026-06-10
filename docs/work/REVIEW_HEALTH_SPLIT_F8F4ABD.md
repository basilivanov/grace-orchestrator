# Review: health split implementation (`f8f4abd`)

Date: 2026-06-10
Reviewer: ChatGPT
Scope reviewed:

- `f8f4abd2fd6cf3b9d89565605654a9558a8102c7`
- compared against `cf52e765dbd2833f9760d96fcb4586189542de14`
- main files inspected:
  - `src/grace_control/api/routers/health.py`
  - `src/grace_control/core/health.py`
  - `scripts/api_watchdog.py`
  - `tests_live/runner/wave_resume_runner.py`
  - `src/grace_control/api/auth.py`
  - `scripts/run_api.py`
  - `src/grace_control/core/command_runner.py`

## Verdict

**BLOCKED / not accepted for the original P0 objective.**

The implementation adds `/health/liveness` and `/health/readiness`, but the actual watchdog and live runner still use the old heavy `/health`. The original production symptom was watchdog/live-runner instability around `/health`; therefore the risk remains.

Additionally, the new watchdog introduces direct SQLite mutation of packet state outside the API/service lifecycle, which is a serious control-plane side channel.

## Summary

Good:

- `/health/liveness` was added and is cheap: returns `{"status": "ok"}`.
- `/health/readiness` was added and checks whether DB engine exists.
- auth middleware now allows the new health paths publicly.
- tests reportedly pass: `883 passed, 0 failed`.

Not good enough:

- `/health` still calls DB-backed `check_health()`.
- `check_health()` still performs dead-worker cleanup and mutates packets/workers/leases.
- `scripts/api_watchdog.py` still polls `/health`, not `/health/liveness`.
- `tests_live/runner/wave_resume_runner.py` still checks `/health`, not `/health/liveness` or `/health/readiness`.
- `scripts/api_watchdog.py` directly updates SQLite: `UPDATE packets SET state='failed' WHERE state='running'`.
- The task document was rewritten to make `/health` remaining heavy look intentional. That weakens the original acceptance criteria instead of satisfying them.

## Findings

### BLOCKER 1 — Watchdog still uses heavy `/health`

`scripts/api_watchdog.py` defines:

```python
API_URL = "http://127.0.0.1:8042/health"
```

and `_alive()` probes that URL.

But `/health` is still implemented as:

```python
@router.get("/health", include_in_schema=False)
async def health() -> dict:
    return await check_health()
```

`check_health()` still opens DB, reads workers, detects dead workers, mutates packet/worker state, deletes leases, and counts packets.

That means the watchdog is still coupled to the DB-backed and state-mutating health path. The original failure mode is not eliminated.

Required fix:

```python
API_URL = "http://127.0.0.1:8042/health/liveness"
```

The watchdog must only use liveness. It must not use `/health`, `/health/full`, or any diagnostics endpoint.

### BLOCKER 2 — Live runner still uses heavy `/health`

`tests_live/runner/wave_resume_runner.py::_check_api()` still does:

```python
resp = _api_call(self.api_url, "GET", "/health", timeout=5)
```

It then interprets diagnostic fields such as `status == "unhealthy"` and `api_alive`.

That means the live runner still treats the old diagnostic endpoint as API availability. During worker activity, this can still create false “API not ready” / restart behavior.

Required fix:

- Use `/health/liveness` to answer “is API process alive?”
- Optionally use `/health/readiness` to answer “is API initialized enough to accept work?”
- Do not use `/health` in watchdog or runner liveness paths.

Suggested `_check_api()` logic:

```python
resp = _api_call(self.api_url, "GET", "/health/liveness", timeout=2)
if "_error" not in resp and resp.get("status") == "ok":
    return True
return False
```

Readiness may be checked separately before feature submission, but liveness/restart decisions must not depend on DB-backed diagnostics.

### BLOCKER 3 — `/health` still has side effects

`src/grace_control/core/health.py::check_health()` still performs cleanup:

```python
packet.state = PacketState.READY.value
worker.status = "dead"
worker.current_packet_id = None
db.query(Lease).filter_by(packet_id=pkt_id).delete()
```

This is unsafe for a route named `/health`, especially when used by watchdogs and runners.

Original P0 requirement was: `/health` must be DB-free and side-effect-free. The implementation changed the spec to keep `/health` full diagnostic instead of meeting that requirement.

Acceptable options:

1. Preferred: make `/health` the cheap liveness endpoint and move old behavior to `/api/diagnostics/health` or `/health/full`.
2. Compatibility compromise: keep `/health` as legacy diagnostic only if all watchdogs/runners/monitors are changed to use `/health/liveness`, and document `/health` as unsafe for liveness.

Given the current code, option 2 is incomplete because watchdog/runner still use `/health`.

### BLOCKER 4 — Watchdog directly mutates SQLite packet state

`scripts/api_watchdog.py::_cleanup_stale_packets()` does:

```python
conn.execute("UPDATE packets SET state='failed' WHERE state='running'")
```

This bypasses:

- `PacketService`
- lease semantics
- run/attempt lifecycle
- evidence persistence
- reviewer/verifier state
- trace/audit expectations

It also marks **all** running packets as failed after an API restart, regardless of whether their worker is alive, whether a run is still producing artifacts, or whether recovery should be `READY`, `FAILED`, `TIMEOUT`, or retry-specific.

This can corrupt exactly the auto-loop we are trying to stabilize.

Required fix:

- Remove direct SQLite mutation from `api_watchdog.py`.
- If cleanup is required, call an explicit API endpoint or service-controlled recovery path.
- At minimum, replace mutation with logging only for now.

For this P0 patch, simplest safe behavior:

```python
def _cleanup_stale_packets():
    return
```

or delete the function and its call.

### MAJOR 1 — Task document was rewritten to weaken acceptance

`docs/work/TZ_SPLIT_LIVENESS_READINESS_HEALTH.md` originally required `/health` itself to become pure liveness. The implementation rewrote the document to state:

```text
GET /health — full health (unchanged)
```

This hides the mismatch between the requested fix and the delivered behavior.

Required fix:

- Restore the original intent in the work doc or add an explicit “implementation deviation” section.
- Do not rewrite acceptance criteria after the fact to match a partial implementation.

### MAJOR 2 — `run_api.py` OOM protection is misleading

`scripts/run_api.py` attempts:

```python
with open("/proc/self/oom_score_adj", "w") as _f:
    _f.write("-1000\n")
```

but silently ignores `OSError`.

In normal non-root execution this will fail. That is fine, but the comment says the API is protected from the OOM killer, which may be false at runtime.

Required fix:

- Log whether the write succeeded or failed.
- Do not rely on this for protection.
- Real OOM protection should be systemd/root-level configuration.

Suggested minimal improvement:

```python
try:
    ...
    print("[run_api] oom_score_adj=-1000 applied", flush=True)
except OSError as e:
    print(f"[run_api] oom_score_adj not applied: {e}", flush=True)
```

### MAJOR 3 — `command_runner` PATH fix only covers string command path

The free function `run_command()` now prepends `.venv/bin` to PATH, but `CommandRunner.run()` list-command branch still calls `subprocess.run(..., env=...)` without the same PATH enrichment.

If acceptance commands are sometimes passed as `list[str]`, this fix may be incomplete.

Required fix:

- Extract PATH enrichment into a helper.
- Apply it to both string and list command execution paths.

Example:

```python
def _build_command_env(cwd: Path, env: dict[str, str] | None = None) -> dict[str, str]:
    ...
```

### MINOR 1 — `_PUBLIC_PATHS` is stale

`src/grace_control/api/auth.py` still has:

```python
_PUBLIC_PATHS = {"/health", "/openapi.json"}
```

but `_is_public()` has hardcoded tuple logic for `/health/liveness` and `/health/readiness`.

This is not breaking, but the constant is now misleading. Either use the constant or remove it.

## Required follow-up patch

Minimum patch to unblock P0:

1. Change watchdog to poll `/health/liveness`.
2. Change live runner `_check_api()` to poll `/health/liveness`.
3. Remove direct SQLite mutation from `scripts/api_watchdog.py`.
4. Add tests that fail if watchdog/runner use `/health` for liveness.
5. Add a regression test that `/health/liveness` still returns 200 even if `check_health()` raises.
6. Document `/health` as legacy/deep diagnostic if it remains heavy.

## Suggested acceptance test after follow-up

```bash
# API starts
curl -s http://127.0.0.1:8042/health/liveness
# expected: {"status":"ok"}

# Optional readiness
curl -s -i http://127.0.0.1:8042/health/readiness
# expected: 200 ready, or 503 not ready before init

# Watchdog log should not show API restart caused by DB-backed /health
 tail -200 /tmp/grace-watchdog.log

# Live scenario
PYTHONPATH=. GRACE_LIVE_AGENT_TESTS=1 GRACE_DEV_TOOLS_ENABLED=1 GRACE_FAST_FAIL=1 \
  python3 -u tests_live/runner/wave_resume_runner.py \
    --scenario backend-1w \
    --api-url http://127.0.0.1:8042 \
    --source-dir . \
    --target-dir /tmp/grace-live-test \
    --timeout 900 \
    --keep-artifacts
```

Expected P0 result:

- No watchdog restart due to `/health` diagnostic slowness/DB lock.
- Runner no longer reports false API-down based on diagnostic health.
- Agent failure, if any, is recorded as agent/packet failure, not API process death.

## Final decision

Do not merge/accept as P0-complete yet.

This patch added useful endpoints, but did not wire the operational consumers to them and introduced a dangerous direct-DB cleanup path. A small follow-up patch should be enough; no broad rewrite is needed.
