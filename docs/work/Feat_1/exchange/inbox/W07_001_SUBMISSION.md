---
feature_id: Feat_1
wave_id: W07
submission_attempt: 1
status: READY_FOR_REVIEW
created_at: 2026-06-16T16:00:00Z
---

# W07 Submission: Worker Error Handling and Retry Semantics

## Changes

### 1. `WorkerFailureType` enum — classified failure types

**File:** `src/grace_control/worker/worker.py`

New enum with 6 classified failure types:
- `AGENT_TIMEOUT` — agent exceeded execution timeout
- `AGENT_NONZERO` — agent returned non-zero exit / generic execution error
- `SCOPE_VIOLATION` — agent wrote outside allowed scope or touched frozen scope
- `WORKTREE_PREFLIGHT_FAILED` — git worktree setup failed
- `STALE_LEASE` — lease expired, another worker claimed the packet
- `API_ERROR` — API call failed (release, retry, etc.)

### 2. `classify_worker_failure()` — deterministic failure classification

**File:** `src/grace_control/worker/worker.py`

Pure function that classifies failures based on context (timeout, result, stale lease, API error, preflight). Priority: stale_lease > timeout > preflight_failed > api_error > result-based (scope_violation vs agent_nonzero).

### 3. `is_failure_retryable()` — retry decision per failure type

**File:** `src/grace_control/worker/worker.py`

Determines whether a failure type should be released as retryable:
- `STALE_LEASE` → NOT retryable (another worker owns the packet)
- `SCOPE_VIOLATION` → NOT automatically retryable (needs human/recovery)
- All others → retryable when attempts remain

### 4. `ExecutionState` dataclass — replaces ad-hoc status handling

**File:** `src/grace_control/worker/worker.py`

New dataclass tracking execution phase and metadata:
- `phase`: claimed → executing → releasing → merging → post_release → done
- `failure_type`: classified `WorkerFailureType`
- `release_status`: accepted, rejected, blocked, failed
- `has_attempts_remaining`: checks attempt vs max_attempts
- `determine_release_status()`: computes correct release status based on failure type and attempts
- `to_release_result()`: builds result dict with failure_type and retryable flags

### 5. Worker loop refactored into clear phases

**File:** `src/grace_control/worker/worker.py`

The `_main_loop` → `_run_one_cycle` is now decomposed into 5 explicit phases:
1. **`_phase_claim()`** — claim packet from queue
2. **`_phase_execute()`** — execute with timeout, classify failures
3. **`_phase_release()`** — release with fencing, handle stale lease
4. **`_phase_merge()`** — merge on accepted, record failure events
5. **`_phase_post_release()`** — retry/recovery based on classification

### 6. Dead/duplicate exception branches removed

**File:** `src/grace_control/worker/worker.py`

- Previously: inner `except asyncio.TimeoutError` + `except Exception` each had their own release logic with duplicate `_release_with_fencing` calls
- Previously: outer `except Exception` in main loop could mask inner errors
- Now: single top-level `except Exception` in `_main_loop` for truly unexpected errors only. Each phase handles its own errors with classified failure types.
- No more duplicate `except Exception: log.warn("release_after_timeout_failed")` + `except Exception: log.warn("release_after_error_failed")` — both replaced by `_phase_release()` which handles all cases.

### 7. Merge failure records explicit observable event

**File:** `src/grace_control/worker/worker.py`

When `_phase_merge()` catches a merge exception:
- Logs with `merge_failed_action_required` (not just `merge_failed_keep_accepted`)
- Records `packet_merge_failed` event via `record_event()` with:
  - `action_required: True`
  - `branch`, `commit_sha`, `target_repo`
  - `error` message
  - `manual_action` hint (e.g., "Manually merge branch X into target")
- This makes merge failures observable and actionable

### 8. `release_status_from_result()` — scope violation awareness

**File:** `src/grace_control/worker/worker.py`

Updated to return "blocked" for scope violations (out of scope, frozen scope) instead of blindly retrying as "rejected".

### 9. Tests

**File:** `tests/test_w07_worker_error_handling.py` — 12 tests:

| Test | Description |
|------|-------------|
| `test_worker_timeout_releases_retryable_status` | timeout with attempts → "rejected" (retryable) |
| `test_worker_timeout_no_attempts_remaining_is_failed` | timeout with no attempts → "failed" (terminal) |
| `test_worker_generic_agent_failure_rejected_not_failed_when_retryable` | generic failure → "rejected" when retryable |
| `test_worker_scope_violation_is_blocked_not_rejected` | scope violation → "blocked" (not blindly retried) |
| `test_worker_stale_lease_release_does_not_loop_forever` | stale lease → empty release status (no retry) |
| `test_worker_stale_lease_post_release_is_noop` | stale lease post-release is no-op |
| `test_worker_dead_except_removed_or_unreachable_tested` | all failure types classified, no ambiguous paths |
| `test_merge_failure_records_action_required_event` | merge failure records observable event with action_required |
| `test_execution_state_has_attempts_remaining` | attempts remaining logic |
| `test_execution_state_phases` | phase tracking |
| `test_release_status_from_result_scope_violation` | scope violation detection in release_status_from_result |
| `test_classify_worker_failure_result_scope_violation` | classify_worker_failure detects scope from result |

## Acceptance Checklist

- [x] Worker timeout goes to retryable status when attempts remain
- [x] Generic agent failure is retryable when safe
- [x] Stale release is handled once and not retried blindly
- [x] Merge failure is observable (records action_required event)
- [x] No dead duplicate exception branch remains
