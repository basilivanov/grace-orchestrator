---
feature_id: Feat_1
wave_id: W07
submission_attempt: 2
status: READY_FOR_REVIEW
created_at: 2026-06-16T12:00:00Z
---

# W07 Rework Submission: Worker Error Handling and Retry Semantics

Rework for review W07_001_REVIEW (REWORK_REQUIRED).

## Blocking Issue 1: Stale accepted release can still proceed to merge

**Problem:** `_phase_execute()` set `exec_state.release_status = "accepted"` from the execution result. If the API later rejected the release as stale, `_phase_release()` set `failure_type = STALE_LEASE` but did NOT clear `release_status`. This left `release_status == "accepted"`, causing `_run_one_cycle()` to call `_phase_merge()` — violating the W01/W07 fencing invariant.

**Fix (3 changes in `src/grace_control/worker/worker.py`):**

1. **`_phase_release()` — clear `release_status` on stale lease:**
   When `release_result.get("stale_lease")` is True, now also sets `exec_state.release_status = ""` so the merge guard cannot fire.

2. **`_run_one_cycle()` — double-guard merge with failure_type check:**
   Changed merge condition from `if exec_state.release_status == "accepted"` to:
   ```python
   if (exec_state.release_status == "accepted"
           and exec_state.failure_type != WorkerFailureType.STALE_LEASE):
   ```
   This provides defense-in-depth: even if `release_status` were somehow left as `"accepted"`, the STALE_LEASE failure_type still prevents merge.

## Blocking Issue 2: Result-based failures are not classified in the active execution path

**Problem:** `_phase_execute()` called `release_status_from_result(result)` for non-accepted results but never called `classify_worker_failure(result=result)`. This meant `failure_type` stayed `None` for normal rejected results, so `to_release_result()` produced payloads without `failure_type` or `retryable` flags.

**Fix in `src/grace_control/worker/worker.py`:**

3. **`_phase_execute()` — classify failure for non-accepted results:**
   After setting `release_status`, added:
   ```python
   if not result.accepted:
       exec_state.failure_type = classify_worker_failure(result=result)
       exec_state.error_message = result.reason or ""
   ```
   This ensures:
   - Scope violations → `failure_type=scope_violation`, `retryable=false`
   - Generic rejections → `failure_type=agent_nonzero`, `retryable=true`
   - All classifications propagate into `to_release_result()` payload

## Rework Tests Added (4 new tests)

| Test | Description |
|------|-------------|
| `test_worker_stale_accepted_release_does_not_merge` | Accepted result + stale release → release_status cleared, failure_type=STALE_LEASE, merge NOT called |
| `test_phase_execute_classifies_agent_nonzero_result` | _phase_execute sets failure_type=AGENT_NONZERO for generic rejected results |
| `test_phase_execute_classifies_scope_violation_result` | _phase_execute sets failure_type=SCOPE_VIOLATION for scope/blocked results |
| `test_release_payload_includes_failure_type_and_retryable_for_result_failures` | Release payload includes failure_type and retryable for both scope_violation (false) and agent_nonzero (true) |

## Test Results

```
tests/test_w07_worker_error_handling.py ................ (16 passed)
tests/test_w06_process_command_hardening.py ........... (11 passed)
tests/test_w05_evidence_contract.py .............. (14 passed)
Total: 41 passed
```

## Changed Files

- `src/grace_control/worker/worker.py` — 3 code changes (stale release status clear, merge guard, execute phase classification)
- `tests/test_w07_worker_error_handling.py` — 4 new rework tests (16 total)
