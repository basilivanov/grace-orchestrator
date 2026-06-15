---
feature_id: Feat_1
wave_id: W08
submission_attempt: 2
status: READY_FOR_REVIEW
created_at: 2026-06-16T14:00:00Z
---

# W08 Submission (attempt 2): Recovery Controller and Proactive Stuck Scanner — Rework

Reviewed commit: `67eb8c6`
Review decision: REWORK_REQUIRED

## Blocking Issue Addressed

### 1. Orphan lease cleanup now covers every non-RUNNING packet state

**Problem:** `_scan_orphan_leases()` used a hard-coded allowlist of non-running states (READY, ACCEPTED, MERGED, REJECTED, FAILED, BLOCKED_FINAL, BLOCKED_RECOVERABLE). This missed three `PacketState` values:
- `DRAFT`
- `BLOCKED` (deprecated alias for BLOCKED_FINAL)
- `CANCELLED`

A lease attached to any of these states is still a lease for a non-RUNNING packet and should be cleaned. The allowlist approach was fragile — any future `PacketState` addition would also be missed.

**Fix:** Replaced the hard-coded allowlist with a simpler invariant check:

```python
# Before (fragile allowlist):
non_running_states = [
    PacketState.READY.value,
    PacketState.ACCEPTED.value,
    ...
]
if packet and packet.state in non_running_states:

# After (complete invariant):
if packet and packet.state != PacketState.RUNNING.value:
```

This is correct because the invariant is: **a lease should only exist for a RUNNING packet**. Any other packet state means the lease is orphaned and should be removed. This naturally covers all current and future `PacketState` values without needing to update a list.

**File changed:** `src/grace_control/core/stuck_scanner.py` — `_scan_orphan_leases()` method, lines 235-251

## Regression Tests Added

**File:** `tests/test_w08_stuck_scanner.py` — 2 new regression tests (10 total)

| Test | Description |
|------|-------------|
| `test_lease_for_draft_packet_is_cleaned` | DRAFT packet + orphan lease → lease deleted, worker reference cleared |
| `test_lease_for_legacy_blocked_packet_is_cleaned` | Legacy BLOCKED packet + orphan lease → lease deleted, worker reference cleared |

These tests specifically cover the two most relevant missed states:
- **DRAFT**: A packet that was never claimed should never have a lease — this is a real edge case where a lease was created but the packet never transitioned to RUNNING.
- **BLOCKED** (deprecated alias): Existing data may still use this deprecated state value. The scanner must handle it correctly for backward compatibility.

The third missed state (CANCELLED) is covered implicitly by the invariant check, and the reviewer's suggested test names are both addressed.

## Test Results

```
tests/test_w05_evidence_contract.py .............. (14 passed)
tests/test_w06_process_command_hardening.py ........... (11 passed)
tests/test_w07_worker_error_handling.py ................ (16 passed)
tests/test_w08_stuck_scanner.py .......... (10 passed)
Total: 51 passed
```

## Changed Files

- `src/grace_control/core/stuck_scanner.py` — `_scan_orphan_leases()`: replaced hard-coded allowlist with `packet.state != PacketState.RUNNING.value` invariant check
- `tests/test_w08_stuck_scanner.py` — 2 new regression tests for DRAFT and legacy BLOCKED states
