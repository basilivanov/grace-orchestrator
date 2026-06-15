---
feature_id: Feat_1
wave_id: W08
submission_attempt: 1
status: READY_FOR_REVIEW
created_at: 2026-06-16T12:00:00Z
---

# W08 Submission: Recovery Controller and Proactive Stuck Scanner

## Changes

### 1. `StuckScanner` — proactive background scanner

**File:** `src/grace_control/core/stuck_scanner.py` (new)

New background scanner that detects and handles stuck runtime states:

| Scanner | Detection | Action |
|---------|-----------|--------|
| `_scan_stuck_running_with_expired_leases` | RUNNING packet with expired/missing lease | Set packet to READY, delete lease, clear worker reference |
| `_scan_stale_workers` | Active worker with heartbeat older than 5 min | Mark worker as inactive |
| `_scan_worker_packet_mismatches` | Active worker with current_packet but no lease | Clear current_packet_id |
| `_scan_orphan_leases` | Lease for non-RUNNING packet (READY, ACCEPTED, MERGED, etc.) | Delete lease, clear worker reference |
| `_scan_blocked_recoverable` | BLOCKED_RECOVERABLE packet | Emit diagnostics event (no auto-action) |
| `_scan_plan_failed_repairable` | PLAN_FAILED feature with repairable compiler errors | Emit diagnostics event (no auto-action) |
| `_scan_features_no_progress` | IN_PROGRESS feature with no progressing packets | Emit diagnostics event |

Key design decisions:
- **Deterministic safe recovery only**: Only stuck RUNNING + expired lease and stale workers get auto-actions. Blocked/PLAN_FAILED cases only emit diagnostics.
- **LLM repair guarded by config**: `_is_llm_repair_allowed()` requires `GRACE_LLM_REPAIR_ENABLED=true`. Default is `false`.
- **Never raises**: `run_stuck_scan()` wraps each scanner in try/except and returns counts dict.
- **Timezone-safe**: Uses `_utcnow()` helper (naive UTC) to match DB schema's `datetime.utcnow()` convention.

### 2. `run_stuck_scan()` — synchronous entry point

Returns a counts dict: `{"stuck_running_recovered": N, "stale_workers_deactivated": N, ...}`. Can be called from any context.

### 3. `stuck_scan_loop()` — async background loop

Runs `run_stuck_scan()` every 60 seconds. Wired into `api/lifespan.py` alongside the existing lease_expiration_loop.

### 4. Plan repair path fix — compiler rejection now routes to repair

**File:** `src/grace_control/services/feature_planning_service.py`

**Problem:** `approve_plan()` raises `ValueError` when the plan compiler rejects. This means `try_approve_or_repair_plan()` would get an exception instead of a `{"status": "PLAN_FAILED"}` result, making the repair path unreachable. Features with repairable compiler errors would stay stuck in PLAN_FAILED forever.

**Fix (3 changes):**

1. **Catch ValueError from approve_plan**: `try_approve_or_repair_plan()` now wraps `approve_plan()` in try/except and treats compiler rejection ValueError as PLAN_FAILED.

2. **Extract compiler errors from feature spec**: When the ValueError is caught, compiler errors are extracted from `feature.spec_json._plan_compiler.errors` instead of the non-existent result dict.

3. **Reset feature status for repair**: When repair is attempted, feature status is reset from PLAN_FAILED back to PLAN_READY so `approve_plan()` can be called again after the plan is fixed.

### 5. Recovery event types registered

**File:** `src/grace_control/core/event_recorder.py`

Added 7 new event types to `RECOVERY_EVENT_TYPES`:
- `stuck_running_recovered`
- `worker_stale_heartbeat_deactivated`
- `worker_packet_mismatch_cleaned`
- `orphan_lease_cleaned`
- `blocked_recoverable_waiting`
- `plan_failed_repairable_detected`
- `feature_no_progress_detected`

### 6. Startup wiring

**File:** `src/grace_control/api/lifespan.py`

Added `stuck_scan_loop()` as a background task alongside the existing lease/wave_gate/feature_gate loops.

### 7. Tests

**File:** `tests/test_w08_stuck_scanner.py` — 8 tests (6 required + 2 additional):

| Test | Description |
|------|-------------|
| `test_stuck_running_with_expired_lease_recovered_by_scanner` | RUNNING + expired lease → READY |
| `test_worker_stale_heartbeat_marks_worker_inactive` | Stale heartbeat → inactive |
| `test_lease_without_running_packet_is_cleaned` | Orphan lease → deleted |
| `test_blocked_recoverable_emits_recovery_waiting_event` | Diagnostics event emitted |
| `test_try_approve_or_repair_plan_handles_compiler_rejection` | ValueError caught, repair path reachable |
| `test_recovery_scanner_does_not_apply_unsafe_llm_repair_by_default` | LLM repair disabled by default |
| `test_run_stuck_scan_never_raises` | DB error → safe return |
| `test_plan_failed_repairable_detected_by_scanner` | PLAN_FAILED repairable → diagnostics event |

## Acceptance Checklist

- [x] Stale RUNNING packets are detected by scanner
- [x] Dead workers become inactive
- [x] Orphan leases are cleaned safely
- [x] Recoverable blocked packets produce actionable diagnostics
- [x] Unsafe LLM repair is not auto-applied by default
- [x] Plan repair path handles compiler rejection (was unreachable, now fixed)

## Test Results

```
tests/test_w05_evidence_contract.py .............. (14 passed)
tests/test_w06_process_command_hardening.py ........... (11 passed)
tests/test_w07_worker_error_handling.py ................ (16 passed)
tests/test_w08_stuck_scanner.py ........ (8 passed)
Total: 49 passed
```

## Changed Files

- `src/grace_control/core/stuck_scanner.py` — NEW: stuck scanner with 7 scanners + background loop
- `src/grace_control/core/event_recorder.py` — 7 new event types
- `src/grace_control/api/lifespan.py` — stuck_scan_loop wired at startup
- `src/grace_control/services/feature_planning_service.py` — plan repair path fix (ValueError catch, error extraction, status reset)
- `tests/test_w08_stuck_scanner.py` — NEW: 8 tests

## Known Limitations

- LLM repair for PLAN_FAILED features detected by the scanner is not auto-applied — requires `GRACE_LLM_REPAIR_ENABLED=true`. Future work: integrate with RecoveryController for safe LLM repair under explicit config.
- Worker stale heartbeat threshold (5 min) is a constant. Should become configurable via settings.
- Scanner uses `_utcnow()` (naive) to match DB convention. When the DB schema migrates to timezone-aware datetimes, the helper should be updated.
