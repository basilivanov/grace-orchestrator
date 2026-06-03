# Codex Review 009 — BLOCKED routing after `a33d7d3`

Commit reviewed: `a33d7d3aeeaab0c547cccc62c7adefc340c973b0`

Previous review: `docs/codex/review-008-evidence-verifier-pipeline-2b1d7cd.md`

Verdict: **PASS — review-008 P0 is fixed.**

The main blocker from review-008 was that `RETURN_TO_ARCHITECT` locally returned `domain_status="blocked"`, but the worker/API still released it as `rejected`, causing the coder retry loop to run again. That is now fixed end-to-end.

---

## P0-1 — BLOCKED state + routing

Status: **fixed.**

### DB enum

`PacketState.BLOCKED = "blocked"` now exists.

### State machine

`RUNNING → BLOCKED` is now a valid transition.

`BLOCKED` is terminal and has no outgoing transitions.

### API release

`release_packet(...)` now routes to `PacketState.BLOCKED` when:

```python
status == "blocked" or result.get("domain_status") == "blocked"
```

This means a worker can release a packet as blocked explicitly, and a safety fallback exists if status is wrong but result domain status is blocked.

### Worker

Worker now maps execution result to release status as:

```python
if result.accepted:
    status = "accepted"
elif result.domain_status == "blocked":
    status = "blocked"
else:
    status = "rejected"
```

Worker only calls `_handle_rejection(...)` for `status == "rejected"`.

For `status == "blocked"`, it logs `packet_blocked` and does **not** retry the coder.

### Adapter

Both architect-return branches now persist `PacketRun.status = "blocked"`:

- Evidence Verifier `RETURN_TO_ARCHITECT`;
- Reviewer `RETURN_TO_ARCHITECT`.

This closes the previous coder retry loop.

---

## P1-1 — Self-evolution guard result_json shape

Status: **fixed enough.**

Self-evolution guard failure now calls `_update_packet_run_result(...)` and stores all four reports:

```text
legacy_result
acceptance_report
evidence_verifier_report
reviewer_report
```

The branch still returns `domain_status="rejected"`, which is okay because self-evolution guard failure is a coder/rework-style failure, not necessarily architect replan.

---

## P1-2 — Acceptance pipeline exception result_json shape

Status: **fixed enough.**

Acceptance pipeline exception now calls `_update_packet_run_result(...)` with:

```python
status="blocked"
acceptance_report=None
```

The helper stores a minimal acceptance report object:

```json
{"error": "acceptance pipeline failed"}
```

and skipped verifier/reviewer reports.

This satisfies the four-report result_json shape for exception paths.

---

## P1-3 — Misleading mocked legacy tests renamed

Status: **fixed.**

The old misleading tests were renamed to make it clear they are adapter-only tests where the acceptance pipeline is mocked and therefore trusted by the adapter.

---

## P1-4 — Prompt path hardening

Status: **fixed.**

Prompt paths now use:

```python
Path(__file__).resolve().parents[3]
```

instead of the more fragile parent chain.

---

## Remaining P1 hardening

I did not find obvious dedicated regression tests for these exact end-to-end cases:

1. API `release_packet(... status="blocked")` moves `RUNNING → BLOCKED`.
2. Worker receives `ExecutionResult(domain_status="blocked")` and does not call `_handle_rejection(...)`.
3. `retry_packet(...)` cannot retry a `BLOCKED` packet.

The code path itself looks correct, so this is not a blocker. Still, add these tests soon to protect the new behavior.

Suggested tests:

```bash
pytest tests/api/test_packets_api.py -q
pytest tests/test_worker_retry.py -q
```

Add specific test names:

```text
test_release_blocked
test_worker_blocked_does_not_retry
test_retry_blocked_raises
```

---

## CI evidence

GitHub combined status for `a33d7d3aeeaab0c547cccc62c7adefc340c973b0` has no attached statuses, so I cannot independently verify the claimed `168 passed` from GitHub Actions.

---

## Final verdict

**PASS.**

The review-008 P0 is fixed: `RETURN_TO_ARCHITECT` can now become a real terminal `blocked` packet instead of silently looping back to the coder.

Proceed with the next controlled smoke/golden run, but add the three P1 regression tests before relying on this behavior long-term.
