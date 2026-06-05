# TZ 010 — Golden smoke readiness hardening before live run

Audience: Flash coder / literal executor.

Goal: before running `grace/features/golden-smoke-live-001.yaml` again, fix the small known golden-specific issues and add regression tests for BLOCKED routing.

Do not redesign the pipeline. Do not remove verifier/reviewer. Do not remove acceptance gate.

---

## Current readiness review

The main execution pipeline is now acceptable after review-009, but the current golden smoke file is still not ideal for a safe first live run.

Found issues:

1. `grace/features/golden-smoke-live-001.yaml` still writes to real product-ish paths:
   - `src/date_util.py`
   - `tests/test_date_util.py`
2. It still uses `python -m pytest ...`, while previous golden failed with `python` not available in PATH from worktree cwd.
3. Acceptance T0 still runs default command when `verification.t0` is empty:
   - `python -m py_compile src/grace_control/core/contracts.py`
   - this can fail with `exit_code=127` when `python` is unavailable.
4. BLOCKED routing code looks correct, but dedicated regression tests are missing:
   - API release blocked
   - worker blocked does not retry
   - retry blocked raises
5. First live golden now runs the full TZ-008 flow, so after deterministic PASS it will call:
   - Evidence Verifier via `agy`
   - Reviewer via `opencode`
   Make sure both CLIs are available before running.

---

## Required patch 1 — move golden smoke to sandbox scope

Update:

```text
grace/features/golden-smoke-live-001.yaml
```

Replace the current file with this exact safe version:

```yaml
title: Golden Smoke Live 001
description: "Minimal live golden test: one sandbox utility plus one test."

constraints:
  frozen_scope:
    - src/
    - tests/
    - src/prefect_grace/
    - src/grace_control/

verification:
  t0: []
  t1:
    - python3 -m pytest sandbox/golden/live_001/test_date_util.py -q
  t2: []

waves:
  - title: Sandbox smoke
    packets:
      - title: Add sandbox date utility
        description: >
          Create a tiny date utility in sandbox/golden/live_001/date_util.py
          and a pytest test in sandbox/golden/live_001/test_date_util.py.
          The utility should expose today_iso() returning a YYYY-MM-DD string.
        scope:
          - sandbox/golden/live_001/
        verification:
          t0: []
          t1:
            - python3 -m pytest sandbox/golden/live_001/test_date_util.py -q
          t2: []
        expected_evidence:
          - id: sandbox_date_util_test_green
            kind: command
            required: true
            pattern: sandbox/golden/live_001/test_date_util.py
        acceptance_profile: NORMAL
```

Why:

- Golden smoke should not write into real `src/` or `tests/`.
- `sandbox/golden/live_001/` is internal-only and safe to merge if smoke passes.
- `python3` avoids the previous `python` PATH failure.
- packet-level `verification` avoids ambiguity from root propagation.

---

## Required patch 2 — skip default T0 command when verification.t0 is explicitly empty

File:

```text
src/grace_control/core/acceptance_pipeline.py
```

Current behavior:

```python
for cmd in (packet.verification.get("t0", []) if packet.verification.get("t0", []) else self._t0_commands):
    ...
```

This means explicit `t0: []` still runs default `_t0_commands`.

Required behavior:

```text
if verification.t0 key exists and value is []:
    skip command execution, but still run contract + scope guard
if verification.t0 key missing:
    use default _t0_commands only for backward compatibility
```

Suggested implementation:

```python
if "t0" in packet.verification:
    t0_cmds = packet.verification.get("t0", []) or []
else:
    t0_cmds = self._t0_commands

for cmd in t0_cmds:
    ...
```

Stage summary should distinguish this case:

```python
summary="T0 passed: scope clean, contract valid, no cheap commands configured"
```

Do not skip scope guard or contract validation.

---

## Required patch 3 — add tests for explicit empty T0

Update or add tests in:

```text
tests/grace_control/core/test_acceptance_pipeline.py
```

Add test:

```text
test_explicit_empty_t0_skips_default_commands_but_runs_scope_guard
```

Test requirements:

- packet.verification has `{"t0": [], "t1": ["..."]}` or equivalent;
- command runner must not be called for default `python -m py_compile ...` in T0;
- T0 stage passes/skips command execution;
- if changed_files includes out-of-scope file, scope guard still fails.

Recommended two assertions/cases:

1. Clean sandbox change:

```text
allowed_write_scope = ["sandbox/golden/live_001/"]
changed_files = ["sandbox/golden/live_001/date_util.py"]
T0 passes
no default py_compile command executed
```

2. Out-of-scope change:

```text
allowed_write_scope = ["sandbox/golden/live_001/"]
changed_files = ["src/grace_control/core/contracts.py"]
T0 fails with scope guard failed
```

---

## Required patch 4 — add BLOCKED routing regression tests

### 4.1 API release blocked

Update:

```text
tests/api/test_packets_api.py
```

Add:

```text
test_release_blocked
```

Flow:

```text
create plan
register worker
claim packet -> RUNNING
POST /api/packets/{pid}/release with:
  worker_id: w1
  status: blocked
  result: {accepted: false, domain_status: blocked, reason: scope impossible}
assert response state == blocked
GET packet and assert state == blocked
```

Also assert cancel on blocked returns 400, if convenient.

### 4.2 retry blocked raises

Update:

```text
tests/test_worker_retry.py
```

Add:

```text
test_retry_blocked_raises
```

Flow:

```text
insert packet with state=PacketState.BLOCKED.value
call retry_packet(packet_id)
assert StateTransitionError
assert state remains blocked
```

### 4.3 worker blocked does not retry

Add or update worker tests. Use whichever test location already exists; otherwise create:

```text
tests/test_worker_blocked_routing.py
```

Add:

```text
test_worker_blocked_does_not_call_handle_rejection
```

Use mocks. Requirements:

- fake executor returns `ExecutionResult(accepted=False, domain_status="blocked", reason="scope impossible")`;
- fake api client records release status;
- run one worker loop iteration or directly test the status mapping helper if a helper exists;
- assert release status is `blocked`;
- assert `_handle_rejection` is not called.

If current worker is hard to test because `_main_loop` is continuous, extract a small helper:

```python
def _status_from_result(result: ExecutionResult) -> str:
    if result.accepted:
        return "accepted"
    if result.domain_status == "blocked":
        return "blocked"
    return "rejected"
```

Then test helper directly and add one test that blocked status does not call `_handle_rejection` if feasible.

---

## Required patch 5 — preflight documentation for live golden

Add a short section to README or create:

```text
docs/codex/golden-smoke-runbook.md
```

Content should say:

```bash
command -v python3
command -v agy
command -v opencode
```

All three must exist before the full TZ-008 golden smoke, because:

- deterministic T1 uses `python3`;
- Evidence Verifier uses `agy`;
- Reviewer uses `opencode`.

---

## Tests to run

Run:

```bash
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/api/test_packets_api.py -q
pytest tests/test_worker_retry.py -q
pytest tests/test_worker_blocked_routing.py -q  # if created
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/grace_control/core/test_evidence_verifier.py -q
pytest tests/grace_control/core/test_reviewer_gate.py -q
pytest tests -q
```

If `tests/test_worker_blocked_routing.py` is not created, omit that command but make sure equivalent worker blocked-routing coverage exists elsewhere.

---

## Acceptance criteria

Done only if:

1. `golden-smoke-live-001.yaml` writes only to `sandbox/golden/live_001/`.
2. `golden-smoke-live-001.yaml` uses `python3`, not `python`.
3. explicit `verification.t0: []` no longer runs default py_compile.
4. scope guard still runs when T0 commands are empty.
5. API release blocked is tested.
6. retry blocked raises is tested.
7. worker blocked does not retry coder is tested or at least status mapping is covered.
8. all targeted tests pass.

---

## After this TZ is fixed: run golden smoke

Use this sequence after tests pass:

```bash
git pull --ff-only origin main
git checkout -b golden/live-001

rm -f /tmp/grace-golden-live.db
export GRACE_DB_URL=sqlite:////tmp/grace-golden-live.db
export GRACE_AGENT_TIMEOUT=1200
export GRACE_CONTEXT_DISABLED=true

command -v python3
command -v agy
command -v opencode
```

Terminal 1:

```bash
grace api start
```

Terminal 2:

```bash
mkdir -p artifacts

grace eval run grace/features/golden-smoke-live-001.yaml \
  --workers 1 \
  --timeout 1200 \
  --report artifacts/golden-live-001.json
```

After run:

```bash
git status --short
git log --oneline -5
cat artifacts/golden-live-001.json
find sandbox/golden/live_001 -maxdepth 2 -type f -print
```

Expected high-level result:

```text
one packet should reach merged
changes should be only under sandbox/golden/live_001/
report JSON should show no failed packet
```
