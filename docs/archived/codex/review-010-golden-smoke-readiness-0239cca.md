# Codex Review 010 — Golden smoke readiness hardening after `0239cca`

Commit reviewed: `0239ccac70107da755bc30150ba8a35d37f3bf67`

Spec: `docs/codex/tz-010-golden-smoke-readiness-tests.md`

Verdict: **PASS WITH P1 FOLLOW-UPS**.

TZ-010 is implemented well enough. The known golden blockers are fixed: sandbox scope, `python3`, explicit empty T0 handling, and BLOCKED routing regression coverage.

Do **not** treat this as the final cheap golden setup until TZ-011 is also implemented, because the current golden packet still has `acceptance_profile: NORMAL`, and current adapter behavior still runs Evidence Verifier + Reviewer for NORMAL.

---

## Patch 1 — golden smoke YAML sandbox scope / python3 / explicit T0

Status: **fixed.**

`grace/features/golden-smoke-live-001.yaml` now writes only under:

```text
sandbox/golden/live_001/
```

It uses:

```yaml
verification:
  t0: []
  t1:
    - python3 -m pytest sandbox/golden/live_001/test_date_util.py -q
  t2: []
```

The packet-level scope is:

```yaml
scope:
  - sandbox/golden/live_001/
```

and product paths are frozen:

```yaml
constraints:
  frozen_scope:
    - src/
    - tests/
    - src/prefect_grace/
    - src/grace_control/
```

This makes the golden smoke safe to merge if it passes: expected changes should be only under `sandbox/golden/live_001/`.

---

## Patch 2 — explicit empty T0 no longer runs default command

Status: **fixed.**

`AcceptancePipeline._run_t0()` now distinguishes:

```text
`t0` key exists and is [] → run no T0 commands
`t0` key missing → use default _t0_commands
```

The relevant implementation is:

```python
if "t0" in packet.verification:
    t0_cmds = packet.verification.get("t0", []) or []
else:
    t0_cmds = self._t0_commands
```

Scope guard and contract validation still run before command execution, which is correct.

---

## Patch 3 — explicit empty T0 tests

Status: **mostly fixed.**

Added tests cover:

- explicit `t0: []` skips default `py_compile`;
- scope guard still blocks out-of-scope changes.

P1 cleanup: `test_explicit_empty_t0_skips_default_commands_scope_clean` passes `changed_files=["sandbox/date_util.py"]` while `allowed_write_scope=["sandbox/golden/"]`. The current `FakeScope` ignores actual scope patterns, so the test still passes, but the fixture is misleading.

Recommended cleanup:

```python
changed_files=["sandbox/golden/live_001/date_util.py"]
allowed_write_scope=["sandbox/golden/"]
```

or use the real `ScopeGuard` for this specific test.

This is not a blocker because the out-of-scope case is covered by explicit fake violation, and production `ScopeGuard` uses the real paths.

---

## Patch 4 — BLOCKED routing regression tests

Status: **fixed enough.**

Added:

- API `test_release_blocked`;
- `test_retry_blocked_raises`;
- `tests/test_worker_blocked_routing.py` with `release_status_from_result(...)` tests.

This covers the main regression risk from review-009: `blocked` should not silently become `rejected`.

P1 hardening: current worker test covers the extracted status mapping helper, not a full loop assertion that `_handle_rejection` is not called. This is acceptable for now because the main loop only calls `_handle_rejection` inside `if status == "rejected"`, but a future integration test would be stronger.

---

## Patch 5 — golden smoke runbook

Status: **fixed.**

`docs/codex/golden-smoke-runbook.md` exists and includes:

```bash
command -v python3
command -v agy
command -v opencode
```

That is correct for current NORMAL-profile behavior because NORMAL still runs Evidence Verifier + Reviewer until TZ-011 lands.

After TZ-011, if the golden packet becomes FAST, `agy` and `opencode` should no longer be required for this specific golden smoke, but they will still be required for NORMAL/STRICT pipeline checks.

---

## Important readiness note before running golden

Current `golden-smoke-live-001.yaml` still says:

```yaml
acceptance_profile: NORMAL
```

At the current code state, NORMAL still means:

```text
deterministic acceptance
→ evidence verifier
→ reviewer
```

So running this golden now is possible only if:

```bash
command -v python3
command -v agy
command -v opencode
```

all pass.

If the goal is a cheap first smoke that tests only coder + deterministic + merge, merge TZ-011 first and change the golden packet to FAST.

---

## Remaining P1 follow-ups

### P1-1 — adjust misleading clean-scope test path

Change:

```python
changed_files=["sandbox/date_util.py"]
```

to:

```python
changed_files=["sandbox/golden/live_001/date_util.py"]
```

in `test_explicit_empty_t0_skips_default_commands_scope_clean`.

### P1-2 — add full worker loop blocked test later

Current helper tests are good enough for now. Later add a worker loop-style test proving:

```text
ExecutionResult(domain_status="blocked")
→ release status blocked
→ _handle_rejection not called
```

---

## Suggested command before golden

Run targeted tests locally:

```bash
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/api/test_packets_api.py -q
pytest tests/test_worker_retry.py -q
pytest tests/test_worker_blocked_routing.py -q
pytest tests -q
```

---

## Final verdict

**PASS WITH P1 FOLLOW-UPS.**

TZ-010 is good enough. The next decision is operational:

- If running before TZ-011: ensure `agy` and `opencode` are available, because NORMAL will invoke them.
- If you want the first golden to be cheap and deterministic-only: implement TZ-011 first, set golden smoke to FAST, then run.
