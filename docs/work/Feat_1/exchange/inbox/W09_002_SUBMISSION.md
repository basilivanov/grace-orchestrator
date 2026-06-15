---
feature_id: Feat_1
wave_id: W09
submission_attempt: 2
status: READY_FOR_REVIEW
created_at: 2026-06-16T16:00:00Z
---

# W09 Submission (attempt 2): Profile Cleanup and Agent Input Validation — Rework

Reviewed commit: `31f852d`
Review decision: REWORK_REQUIRED

## Blocking Issue Addressed

### 1. `GRACE_LIVE_EXECUTOR_PROFILE` now rejects disabled profiles

**Problem:** In `select_executor()`, the live override branch ran before the disabled-profile filter:

```python
# Before: disabled profile returned via live override
if live_profile:
    match = get_agent_profile(live_profile)
    if match:
        return match.to_dict()  # ← disabled profiles returned here
```

Setting `GRACE_LIVE_EXECUTOR_PROFILE=opencode` would return the disabled `opencode` profile, bypassing the W09 disabled-profile skip logic. This violated the acceptance criteria: disabled profiles must not be runnable by hidden override.

**Fix:** Added a fail-closed check in the live override branch. If the requested profile is disabled, `select_executor()` raises `ValueError` instead of silently returning it or falling back:

```python
# After: fail-closed on disabled profile via live override
if match:
    if match.disabled:
        raise ValueError(
            f"GRACE_LIVE_EXECUTOR_PROFILE={live_profile!r} selects a "
            f"disabled profile. Disabled profiles must not be used for "
            f"execution. Either enable the profile in agent_profiles.yaml "
            f"or choose a different live profile."
        )
    return match.to_dict()
```

This is fail-closed: an explicitly requested disabled profile causes an immediate error, rather than silently falling back to another executor (which could mask the misconfiguration).

**File changed:** `src/grace_control/core/executor_selector.py` — `select_executor()` lines 28-35

## Regression Test Added

**File:** `tests/test_w09_profile_cleanup.py` — 1 new regression test (8 total)

| Test | Description |
|------|-------------|
| `test_live_executor_profile_cannot_select_disabled_profile` | `GRACE_LIVE_EXECUTOR_PROFILE=opencode` (disabled) → `ValueError` raised |

The test sets `GRACE_LIVE_EXECUTOR_PROFILE=opencode` (which is marked `disabled: true` in the YAML) and asserts that `select_executor("coder")` raises `ValueError` with message containing "selects a disabled profile".

## Test Results

```
tests/test_w05_evidence_contract.py .............. (14 passed)
tests/test_w06_process_command_hardening.py ........... (11 passed)
tests/test_w07_worker_error_handling.py ................ (16 passed)
tests/test_w08_stuck_scanner.py .......... (10 passed)
tests/test_w09_profile_cleanup.py ........ (8 passed)
Total: 59 passed
```

## Changed Files

- `src/grace_control/core/executor_selector.py` — `select_executor()`: fail-closed check for disabled profiles in live override branch
- `tests/test_w09_profile_cleanup.py` — 1 new regression test for live override disabled profile rejection
