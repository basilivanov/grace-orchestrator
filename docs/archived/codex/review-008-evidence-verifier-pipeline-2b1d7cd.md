# Codex Review 008 — Evidence Verifier + Reviewer pipeline after `2b1d7cd`

Commit reviewed: `2b1d7cd97b84d175f4509abe4e91ac5600e4f4cb`

Spec: `docs/codex/tz-008-evidence-verifier-reviewer-pipeline.md`

Verdict: **REWORK_REQUIRED**.

The implementation is directionally good and most local pieces exist, but the system-level `RETURN_TO_ARCHITECT` routing is not actually implemented. Architect-return currently becomes normal `rejected` and the worker automatically retries the coder. This violates the main routing requirement of TZ-008.

---

## What is implemented well

### Evidence Verifier module

`src/grace_control/core/evidence_verifier.py` exists and includes:

- `EvidenceVerifierVerdict` with the required three verdicts;
- `EvidenceVerifierReport`;
- `skipped_evidence_report(...)`;
- `parse_evidence_verifier_json(...)`;
- `run_evidence_verifier(...)`.

The parser is fail-closed: invalid/missing JSON and unknown verdict return `REWORK_TO_CODER`, not `PASS`.

### Reviewer Gate module

`src/grace_control/core/reviewer_gate.py` exists and includes:

- `ReviewerVerdict` with the required three verdicts;
- `ReviewerReport`;
- `skipped_reviewer_report(...)`;
- `parse_reviewer_json(...)`;
- `run_reviewer_gate(...)`.

The parser is also fail-closed.

### Adapter call order

`PacketExecutionAdapter.execute()` now has the intended local order:

```text
legacy/coder
→ deterministic acceptance
→ if deterministic fail: skip verifier/reviewer
→ evidence verifier
→ if verifier PASS: reviewer
→ reviewer PASS: accepted
```

This satisfies the important rule that reviewer is not called after deterministic failure or verifier failure.

### result_json shape on main branches

`_update_packet_run_result(...)` writes:

```json
{
  "legacy_result": {},
  "acceptance_report": {},
  "evidence_verifier_report": {},
  "reviewer_report": {}
}
```

This matches the requested result shape for normal deterministic/verifier/reviewer branches.

---

## P0-1 — `RETURN_TO_ARCHITECT` does not actually route to architect

This is the main blocker.

### Current adapter behavior

When Evidence Verifier returns `RETURN_TO_ARCHITECT`, adapter creates:

```python
ExecutionResult(
    accepted=False,
    domain_status="blocked",
    reason=evidence_report.summary,
)
```

But it then stores the `PacketRun` with:

```python
_update_packet_run_result(..., status="rejected", ...)
```

Same issue exists for Reviewer `RETURN_TO_ARCHITECT`: returned `ExecutionResult.domain_status == "blocked"`, but `PacketRun.status == "rejected"`.

### Current worker behavior

Worker ignores `result.domain_status` for release routing:

```python
status = "accepted" if result.accepted else "rejected"
await self.api.release_packet(packet_id, self.worker_id, status, result.model_dump())
```

Then for every rejected packet it calls:

```python
self._handle_rejection(packet_id)
```

and `_handle_rejection(...)` retries the packet:

```python
retry_packet(packet_id)
```

### Current API behavior

`release_packet(...)` maps status only like this:

```python
if status == "accepted" and result.get("accepted"):
    target = PacketState.ACCEPTED
elif status == "rejected":
    target = PacketState.REJECTED
else:
    target = PacketState.FAILED
```

There is no `blocked` / `needs_architect_replan` state.

### Impact

Evidence Verifier can say:

```text
RETURN_TO_ARCHITECT because scope is impossible
```

but the actual system does:

```text
release as rejected
worker retries coder
coder receives impossible packet again
```

So the architect-return path promised by TZ-008 is not working.

### Required fix

Implement real architect-return routing end-to-end.

Preferred minimal design:

1. Add packet state:

```python
PacketState.BLOCKED = "blocked"
```

or:

```python
PacketState.NEEDS_ARCHITECT_REPLAN = "needs_architect_replan"
```

Use one name consistently. `blocked` is shorter and already used in domain_status.

2. Update state machine to allow:

```text
RUNNING → BLOCKED
BLOCKED should not be auto-retried by worker
```

3. Update API release:

```python
elif status == "blocked" or result.get("domain_status") == "blocked":
    target = PacketState.BLOCKED
```

4. Update worker release routing:

```python
if result.accepted:
    status = "accepted"
elif result.domain_status == "blocked":
    status = "blocked"
else:
    status = "rejected"
```

5. Update worker post-release logic:

```python
if status == "rejected":
    self._handle_rejection(packet_id)
elif status == "blocked":
    log/notify architect replan required
    do not retry coder
```

6. Update adapter `_update_packet_run_result(...)` calls for `RETURN_TO_ARCHITECT` branches:

```python
status="blocked"
```

not `status="rejected"`.

7. Add tests:

- Evidence Verifier `RETURN_TO_ARCHITECT` → worker releases `blocked`, not `rejected`.
- Reviewer `RETURN_TO_ARCHITECT` → worker releases `blocked`, not `rejected`.
- `blocked` packet is not retried by `_handle_rejection`.
- API release with `status="blocked"` moves packet to `blocked`.

---

## P1-1 — Self-evolution guard branch bypasses the new four-report result_json shape

Current self-evolution guard failure returns `ExecutionResult` directly:

```python
if not guard_result.passed:
    execution_result = ExecutionResult(...)
    return execution_result
```

It does not call `_update_packet_run_result(...)` and does not store:

```text
legacy_result
acceptance_report
evidence_verifier_report
reviewer_report
```

This violates the general “result_json always has four reports” idea for that branch.

Required fix:

- Build skipped evidence/reviewer reports.
- Store result_json via `_update_packet_run_result(...)` before return.
- Add a test for self-evolution guard blocked branch.

---

## P1-2 — Acceptance pipeline exception branch bypasses result_json report shape

If `run_acceptance_pipeline(...)` raises, adapter returns:

```python
ExecutionResult(
    accepted=False,
    domain_status="blocked",
    reason="Acceptance pipeline error: ...",
)
```

but does not update `PacketRun.result_json` with skipped verifier/reviewer reports.

Required fix:

- Treat acceptance pipeline exception as deterministic failure/blocked.
- Store a minimal failed `acceptance_report` or `acceptance_error` field.
- Store skipped evidence/reviewer reports.
- Add a test.

---

## P1-3 — Tests still encode unsafe adapter behavior for bad legacy status with mocked accepted pipeline

Existing tests still have cases where:

```text
legacy_ok=False or legacy domain_status="rejected"
pipeline_report=_make_accepted_report()
expect_accepted=True
```

This tests that adapter trusts the deterministic pipeline, which is acceptable as an adapter-only unit if the real pipeline is separately tested. But the test names are misleading and can normalize an unsafe mental model.

Required cleanup:

- Rename these tests to explicitly say: `adapter_trusts_acceptance_pipeline_report_when_mocked`.
- Keep real core acceptance tests that prove legacy bad status cannot produce `ACCEPTED`.

---

## P1-4 — Prompt path construction is fragile but currently works

Both new modules use:

```python
Path(__file__).parent.parent.parent.parent / "src" / "prefect_grace" / "prompts" / ...
```

This works for the current `src/grace_control/core/...` layout, but it is brittle.

Recommended:

```python
Path(__file__).resolve().parents[3] / "src" / "prefect_grace" / "prompts" / ...
```

or centralize prompt loading.

Not a blocker.

---

## P1-5 — No CI status attached to commit

GitHub combined status for `2b1d7cd97b84d175f4509abe4e91ac5600e4f4cb` returned no statuses.

I cannot independently verify the claimed `168 tests passing` from GitHub Actions.

---

## Required rework checklist

1. Add real blocked / needs architect state.
2. Update API release to accept `status="blocked"` or `result.domain_status == "blocked"`.
3. Update worker to release blocked when `ExecutionResult.domain_status == "blocked"`.
4. Ensure blocked packets are not auto-retried by `_handle_rejection`.
5. Store PacketRun status `blocked` for verifier/reviewer `RETURN_TO_ARCHITECT` branches.
6. Add tests for verifier architect-return and reviewer architect-return at worker/API level.
7. Fix result_json shape for self-evolution guard branch.
8. Fix result_json shape for acceptance pipeline exception branch.

---

## Suggested focused tests

Run after rework:

```bash
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/grace_control/core/test_evidence_verifier.py -q
pytest tests/grace_control/core/test_reviewer_gate.py -q
pytest tests/api/test_packets_api.py -q
pytest tests/grace_control/worker -q
pytest tests/grace_control -q
pytest tests -q
```

If there is no worker test module yet, add one or extend existing worker tests.

---

## Final verdict

**REWORK_REQUIRED.**

Local verifier/reviewer stages are mostly implemented, but the most important routing branch — `RETURN_TO_ARCHITECT` — currently loops back to the coder because worker/API only understand accepted/rejected/failed. Fix blocked routing before using this pipeline for real autonomous runs.
