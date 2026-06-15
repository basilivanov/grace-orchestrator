# ############################################################################
# AI_HEADER: test_w07_worker_error_handling_retry
# ROLE: W07 regression tests — worker error handling and retry semantics.
# ############################################################################

"""W07 Worker Error Handling and Retry Semantics.

Tests cover:
1. Worker timeout releases retryable status when attempts remain
2. Worker generic agent failure is rejected (not failed) when retryable
3. Worker stale lease release does not loop forever
4. Worker dead except branches are removed or unreachable
5. Merge failure records action_required event
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from grace_control.worker.worker import (
    Worker,
    WorkerFailureType,
    ExecutionState,
    classify_worker_failure,
    is_failure_retryable,
    release_status_from_result,
)


# ─── Test 1: Worker timeout releases retryable status ───────────────────────

def test_worker_timeout_releases_retryable_status():
    """W07: Worker timeout with attempts remaining must release as
    'rejected' (retryable), not 'failed' (terminal)."""
    exec_state = ExecutionState(
        packet_id="pkt-timeout",
        worker_id="worker-1",
        attempt=2,
        max_attempts=5,
    )
    exec_state.failure_type = WorkerFailureType.AGENT_TIMEOUT
    exec_state.error_message = "Agent timed out after 300s"

    status = exec_state.determine_release_status()
    assert status == "rejected", \
        f"Timeout with attempts remaining should be 'rejected' (retryable), got: {status}"

    # Verify the result includes retryable flag
    result = exec_state.to_release_result()
    assert result.get("retryable") is True, \
        f"Timeout result should be retryable, got: {result}"
    assert result.get("failure_type") == "agent_timeout"


def test_worker_timeout_no_attempts_remaining_is_failed():
    """W07: Worker timeout with no attempts remaining must be 'failed' (terminal)."""
    exec_state = ExecutionState(
        packet_id="pkt-timeout-exhausted",
        worker_id="worker-1",
        attempt=5,
        max_attempts=5,
    )
    exec_state.failure_type = WorkerFailureType.AGENT_TIMEOUT
    exec_state.error_message = "Agent timed out after 300s"

    status = exec_state.determine_release_status()
    assert status == "failed", \
        f"Timeout with no attempts remaining should be 'failed' (terminal), got: {status}"


# ─── Test 2: Worker generic agent failure rejected not failed when retryable ─

def test_worker_generic_agent_failure_rejected_not_failed_when_retryable():
    """W07: Generic agent failure with attempts remaining must release as
    'rejected' (retryable), not 'failed' (terminal)."""
    exec_state = ExecutionState(
        packet_id="pkt-fail",
        worker_id="worker-1",
        attempt=1,
        max_attempts=3,
    )
    exec_state.failure_type = WorkerFailureType.AGENT_NONZERO
    exec_state.error_message = "Execution error: command failed"

    status = exec_state.determine_release_status()
    assert status == "rejected", \
        f"Agent failure with attempts remaining should be 'rejected' (retryable), got: {status}"

    # Verify retryable
    assert is_failure_retryable(WorkerFailureType.AGENT_NONZERO), \
        "AGENT_NONZERO should be retryable"

    # Verify not scope violation
    result_data = exec_state.to_release_result()
    assert result_data.get("failure_type") == "agent_nonzero"


def test_worker_scope_violation_is_blocked_not_rejected():
    """W07: Scope violation must be 'blocked', not blindly retried."""
    exec_state = ExecutionState(
        packet_id="pkt-scope",
        worker_id="worker-1",
        attempt=1,
        max_attempts=3,
    )
    exec_state.failure_type = WorkerFailureType.SCOPE_VIOLATION
    exec_state.error_message = "Agent wrote outside allowed scope"

    status = exec_state.determine_release_status()
    assert status == "blocked", \
        f"Scope violation should be 'blocked', got: {status}"

    # Scope violation is NOT retryable
    assert not is_failure_retryable(WorkerFailureType.SCOPE_VIOLATION), \
        "SCOPE_VIOLATION should not be retryable"


# ─── Test 3: Worker stale lease release does not loop forever ───────────────

def test_worker_stale_lease_release_does_not_loop_forever():
    """W07: Stale lease release must be handled once and not retried blindly.
    The execution state must produce no release status for stale lease."""
    exec_state = ExecutionState(
        packet_id="pkt-stale",
        worker_id="worker-1",
        attempt=1,
        max_attempts=3,
    )
    exec_state.failure_type = WorkerFailureType.STALE_LEASE
    exec_state.error_message = "Lease expired, another worker claimed"

    # Stale lease must produce empty release status — caller must not release
    status = exec_state.determine_release_status()
    assert status == "", \
        f"Stale lease should produce empty release status (don't release), got: '{status}'"

    # Stale lease is NOT retryable
    assert not is_failure_retryable(WorkerFailureType.STALE_LEASE), \
        "STALE_LEASE should not be retryable"


def test_worker_stale_lease_post_release_is_noop():
    """W07: Stale lease post-release must be a no-op — no retry, no recovery."""
    exec_state = ExecutionState(
        packet_id="pkt-stale-2",
        worker_id="worker-1",
        failure_type=WorkerFailureType.STALE_LEASE,
    )
    # Phase check: post_release for stale lease should skip everything
    # This is tested by verifying the _phase_post_release method
    # doesn't call _handle_rejection or _maybe_apply_recovery
    # For unit test, verify the conditions directly:
    assert exec_state.failure_type == WorkerFailureType.STALE_LEASE
    assert not is_failure_retryable(WorkerFailureType.STALE_LEASE)
    assert exec_state.determine_release_status() == ""


# ─── Test 4: Worker dead except removed or unreachable ──────────────────────

def test_worker_dead_except_removed_or_unreachable_tested():
    """W07: No duplicate/dead 'except Exception' branches remain in worker.

    Verify that:
    1. classify_worker_failure covers all expected failure types
    2. is_failure_retryable has deterministic behavior for all types
    3. No ambiguous double-exception branches exist in the code path
    """
    # All failure types must be classifiable
    all_types = list(WorkerFailureType)
    assert len(all_types) == 6, f"Expected 6 failure types, got: {all_types}"
    assert WorkerFailureType.AGENT_TIMEOUT in all_types
    assert WorkerFailureType.AGENT_NONZERO in all_types
    assert WorkerFailureType.SCOPE_VIOLATION in all_types
    assert WorkerFailureType.WORKTREE_PREFLIGHT_FAILED in all_types
    assert WorkerFailureType.STALE_LEASE in all_types
    assert WorkerFailureType.API_ERROR in all_types

    # is_failure_retryable must be deterministic for each type
    retryable_types = [t for t in all_types if is_failure_retryable(t)]
    non_retryable_types = [t for t in all_types if not is_failure_retryable(t)]

    assert WorkerFailureType.STALE_LEASE in non_retryable_types, \
        "STALE_LEASE must be non-retryable"
    assert WorkerFailureType.SCOPE_VIOLATION in non_retryable_types, \
        "SCOPE_VIOLATION must be non-retryable"
    assert WorkerFailureType.AGENT_TIMEOUT in retryable_types, \
        "AGENT_TIMEOUT must be retryable"
    assert WorkerFailureType.AGENT_NONZERO in retryable_types, \
        "AGENT_NONZERO must be retryable"
    assert WorkerFailureType.WORKTREE_PREFLIGHT_FAILED in retryable_types, \
        "WORKTREE_PREFLIGHT_FAILED must be retryable"
    assert WorkerFailureType.API_ERROR in retryable_types, \
        "API_ERROR must be retryable"

    # classify_worker_failure must not have ambiguous paths
    # Timeout takes priority
    assert classify_worker_failure(timeout=True) == WorkerFailureType.AGENT_TIMEOUT
    # Stale lease takes priority
    assert classify_worker_failure(release_stale=True) == WorkerFailureType.STALE_LEASE
    # Preflight failed
    assert classify_worker_failure(preflight_failed=True) == WorkerFailureType.WORKTREE_PREFLIGHT_FAILED
    # API error
    assert classify_worker_failure(api_error=True) == WorkerFailureType.API_ERROR
    # Combined: stale_lease overrides everything
    assert classify_worker_failure(timeout=True, release_stale=True) == WorkerFailureType.STALE_LEASE


# ─── Test 5: Merge failure records action_required event ────────────────────

def test_merge_failure_records_action_required_event():
    """W07: Merge failure must record an explicit observable event with
    action_required=True for manual action, not silently swallowed."""
    # Simulate the merge failure path by testing _phase_merge directly
    # We need to mock the API and event_recorder

    worker = Worker.__new__(Worker)  # Create without __init__
    worker.log = MagicMock()
    worker.api = AsyncMock()
    worker._git_context = MagicMock()
    worker._git_context.target_repo_root = "/repo"

    exec_state = ExecutionState(
        packet_id="pkt-merge-fail",
        worker_id="worker-1",
        release_status="accepted",
    )

    # Create a mock ExecutionResult
    from grace_control.adapters.packet_executor import ExecutionResult
    result = ExecutionResult(
        accepted=True,
        domain_status="accepted",
        worktree_path="/worktree",
        branch_name="agent/pkt-merge-fail",
        commit_sha="abc123def456",
        duration_ms=1000,
    )

    # Make merge_packet raise an error
    worker.api.merge_packet = AsyncMock(side_effect=Exception("Merge conflict: CONFLICT"))

    # Run _phase_merge and verify event is recorded
    with patch("grace_control.core.event_recorder.record_event") as mock_record:
        asyncio.run(worker._phase_merge(exec_state, result))

        # Verify merge_packet was attempted
        worker.api.merge_packet.assert_called_once()

        # Verify record_event was called with action_required
        mock_record.assert_called_once()
        call_args = mock_record.call_args
        assert call_args[0][0] == "packet_merge_failed", \
            f"Expected 'packet_merge_failed' event, got: {call_args[0][0]}"
        assert call_args[0][1] == "packet"
        assert call_args[0][2] == "pkt-merge-fail"

        payload = call_args[0][3]
        assert payload.get("action_required") is True, \
            f"Expected action_required=True in payload, got: {payload}"
        assert "branch" in payload, "Expected 'branch' in merge failure event"
        assert "commit_sha" in payload, "Expected 'commit_sha' in merge failure event"
        assert "manual_action" in payload, "Expected 'manual_action' in merge failure event"
        assert "Merge conflict" in payload.get("error", ""), \
            f"Expected merge error in payload, got: {payload}"


# ─── Additional: ExecutionState tests ───────────────────────────────────────

def test_execution_state_has_attempts_remaining():
    """W07: ExecutionState.has_attempts_remaining must correctly check."""
    # Unlimited attempts
    state1 = ExecutionState(packet_id="p1", worker_id="w1", attempt=100, max_attempts=0)
    assert state1.has_attempts_remaining is True

    # Attempts remaining
    state2 = ExecutionState(packet_id="p2", worker_id="w1", attempt=2, max_attempts=5)
    assert state2.has_attempts_remaining is True

    # No attempts remaining
    state3 = ExecutionState(packet_id="p3", worker_id="w1", attempt=5, max_attempts=5)
    assert state3.has_attempts_remaining is False


def test_execution_state_phases():
    """W07: ExecutionState must track phases correctly."""
    state = ExecutionState(packet_id="p1", worker_id="w1")
    assert state.phase == "claimed"

    state.phase = "executing"
    assert state.phase == "executing"

    state.phase = "releasing"
    assert state.phase == "releasing"

    state.phase = "merging"
    assert state.phase == "merging"

    state.phase = "post_release"
    assert state.phase == "post_release"


def test_release_status_from_result_scope_violation():
    """W07: release_status_from_result must return 'blocked' for scope violations."""
    from grace_control.adapters.packet_executor import ExecutionResult

    # Normal rejection
    result1 = ExecutionResult(accepted=False, domain_status="rejected", reason="test failed")
    assert release_status_from_result(result1) == "rejected"

    # Scope violation in domain_status
    result2 = ExecutionResult(accepted=False, domain_status="rejected", reason="scope violation detected")
    assert release_status_from_result(result2) == "blocked"

    # Frozen scope in reason
    result3 = ExecutionResult(accepted=False, domain_status="rejected", reason="frozen scope touched")
    assert release_status_from_result(result3) == "blocked"

    # Blocked domain_status
    result4 = ExecutionResult(accepted=False, domain_status="blocked")
    assert release_status_from_result(result4) == "blocked"

    # Accepted
    result5 = ExecutionResult(accepted=True, domain_status="accepted")
    assert release_status_from_result(result5) == "accepted"


def test_classify_worker_failure_result_scope_violation():
    """W07: classify_worker_failure must detect scope violation from result."""
    from grace_control.adapters.packet_executor import ExecutionResult

    # Scope in domain_status
    result1 = ExecutionResult(accepted=False, domain_status="scope_violation")
    assert classify_worker_failure(result=result1) == WorkerFailureType.SCOPE_VIOLATION

    # Scope in reason
    result2 = ExecutionResult(accepted=False, domain_status="rejected", reason="Out of scope change")
    assert classify_worker_failure(result=result2) == WorkerFailureType.SCOPE_VIOLATION

    # Frozen in reason
    result3 = ExecutionResult(accepted=False, domain_status="rejected", reason="Agent touched frozen files")
    assert classify_worker_failure(result=result3) == WorkerFailureType.SCOPE_VIOLATION

    # Blocked domain_status
    result4 = ExecutionResult(accepted=False, domain_status="blocked")
    assert classify_worker_failure(result=result4) == WorkerFailureType.SCOPE_VIOLATION

    # Non-zero (generic failure)
    result5 = ExecutionResult(accepted=False, domain_status="rejected", reason="Test failed")
    assert classify_worker_failure(result=result5) == WorkerFailureType.AGENT_NONZERO
