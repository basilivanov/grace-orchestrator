# Codex Review 011 — Acceptance profile routing after `b5489d8`

Commit reviewed: `b5489d8b2338628587d2f116859ac372a39c28ad` / current `origin/main`

Spec: `docs/codex/tz-011-acceptance-profile-routing.md`

Verdict: **PASS — ready for first cheap golden smoke.**

The TZ-011 behavior is implemented in current `origin/main`: `acceptance_profile` now controls the expensive LLM gates after deterministic acceptance.

---

## Profile routing status

### FAST

Status: **fixed.**

Current adapter behavior:

```python
if profile == AcceptanceProfile.FAST:
    ev_report = skipped_evidence_report("FAST profile skips evidence verifier")
    rv_report = skipped_reviewer_report("FAST profile skips reviewer")
    execution_result = ExecutionResult(accepted=True, ...)
    _update_packet_run_result(... status="accepted", ...)
    return execution_result
```

So FAST is now:

```text
deterministic acceptance only
no Evidence Verifier
no Reviewer
```

This matches TZ-011.

---

### NORMAL

Status: **fixed.**

Current adapter behavior:

```text
run Evidence Verifier
if REWORK_TO_CODER → rejected
if RETURN_TO_ARCHITECT → blocked
if PASS and profile == NORMAL → skip Reviewer and accept
```

So NORMAL is now:

```text
deterministic acceptance
cheap Evidence Verifier
Reviewer skipped by default
```

This matches TZ-011.

---

### STRICT

Status: **fixed.**

Current adapter behavior after verifier PASS falls through to:

```python
reviewer_report = await run_reviewer_gate(...)
```

So STRICT remains:

```text
deterministic acceptance
Evidence Verifier
Reviewer always
```

This matches TZ-011.

---

## Deterministic failure remains authoritative

Status: **fixed.**

The deterministic failure branch remains before profile routing. If acceptance report is not accepted, adapter returns immediately and uses skipped reports.

So no profile can turn deterministic failure into PASS.

---

## Golden smoke profile

Status: **fixed.**

`grace/features/golden-smoke-live-001.yaml` now has:

```yaml
acceptance_profile: FAST
```

The smoke also remains sandboxed:

```yaml
scope:
  - sandbox/golden/live_001/
```

and uses:

```yaml
python3 -m pytest sandbox/golden/live_001/test_date_util.py -q
```

This means the first golden smoke should now exercise:

```text
coder
→ deterministic acceptance
→ skipped evidence verifier
→ skipped reviewer
→ merge
```

No `agy` / `opencode` should be needed for this specific FAST golden smoke.

---

## Tests

Status: **fixed enough.**

Adapter tests now cover:

- FAST skips verifier and reviewer;
- NORMAL verifier PASS skips reviewer;
- NORMAL verifier REWORK rejects and skips reviewer;
- NORMAL verifier RETURN_TO_ARCHITECT blocks and skips reviewer;
- STRICT verifier PASS calls reviewer;
- deterministic failure skips both gates.

The test helper passes `profile` through the mocked packet's `acceptance_profile`; `build_packet_contract()` reads `packet_data.get("acceptance_profile", "NORMAL")`, so this exercises the actual routing field.

---

## Remaining P1 follow-ups

### P1-1 — runbook is now stricter than necessary for FAST golden

`docs/codex/golden-smoke-runbook.md` still says to check:

```bash
command -v agy
command -v opencode
```

After TZ-011, FAST golden should not need these. This is not a blocker, but update the runbook later:

```text
FAST golden requires: python3
NORMAL/STRICT pipeline requires: python3 + agy + opencode
```

### P1-2 — old P1 from review-010 still applies

In `test_explicit_empty_t0_skips_default_commands_scope_clean`, the clean changed file path should be adjusted from:

```python
sandbox/date_util.py
```

to:

```python
sandbox/golden/live_001/date_util.py
```

Not a blocker.

---

## Pre-golden command

Before launching golden, run:

```bash
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/api/test_packets_api.py -q
pytest tests/test_worker_retry.py -q
pytest tests/test_worker_blocked_routing.py -q
pytest tests -q
```

I cannot independently verify the claimed `181 passed` because no CI status was available through the connector.

---

## Final verdict

**PASS.**

The profile routing is implemented and the golden smoke is now FAST. The repo is ready for the first controlled cheap golden smoke run.
