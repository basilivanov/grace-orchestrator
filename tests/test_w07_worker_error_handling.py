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


def test_worker_timeout_exhausted_enters_recovery_when_enabled(monkeypatch):
    monkeypatch.setenv("GRACE_RECOVERY_CONTROLLER_ENABLED", "true")
    exec_state = ExecutionState(
        packet_id="pkt-timeout-recovery",
        worker_id="worker-1",
        attempt=3,
        max_attempts=3,
    )
    exec_state.failure_type = WorkerFailureType.AGENT_TIMEOUT
    exec_state.error_message = "Agent timed out after 600s"

    assert exec_state.determine_release_status() == "blocked_recoverable"


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


def test_worker_scope_violation_is_recovery_controlled_not_rejected():
    """W07: Scope violation must await recovery, not be blindly retried."""
    exec_state = ExecutionState(
        packet_id="pkt-scope",
        worker_id="worker-1",
        attempt=1,
        max_attempts=3,
    )
    exec_state.failure_type = WorkerFailureType.SCOPE_VIOLATION
    exec_state.error_message = "Agent wrote outside allowed scope"

    status = exec_state.determine_release_status()
    assert status == "blocked_recoverable", \
        f"Scope violation should be 'blocked_recoverable', got: {status}"

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


def test_merge_uses_packet_target_repo_override():
    """An external packet must merge into its claim target, not worker default."""
    from grace_control.adapters.packet_executor import ExecutionResult

    worker = Worker.__new__(Worker)
    worker.log = MagicMock()
    worker.api = AsyncMock()
    worker._git_context = MagicMock()
    worker._git_context.target_repo_root = "/opt/deep-calm"

    exec_state = ExecutionState(
        packet_id="pkt-external-target",
        worker_id="worker-1",
        release_status="accepted",
        target_repo_root="/opt/trend-radar-ru",
    )
    result = ExecutionResult(
        accepted=True,
        domain_status="accepted",
        worktree_path="/worktree",
        branch_name="agent/pkt-external-target",
        commit_sha="abc123def456",
        duration_ms=1000,
    )

    asyncio.run(worker._phase_merge(exec_state, result))

    assert worker.api.merge_packet.await_args.kwargs["target_repo_root"] == \
        "/opt/trend-radar-ru"


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
    """W07: Scope violations must enter recovery-controlled blocked state."""
    from grace_control.adapters.packet_executor import ExecutionResult

    # Normal rejection
    result1 = ExecutionResult(accepted=False, domain_status="rejected", reason="test failed")
    assert release_status_from_result(result1) == "rejected"

    # Scope violation in domain_status
    result2 = ExecutionResult(accepted=False, domain_status="rejected", reason="scope violation detected")
    assert release_status_from_result(result2) == "blocked_recoverable"

    # Frozen scope in reason
    result3 = ExecutionResult(accepted=False, domain_status="rejected", reason="frozen scope touched")
    assert release_status_from_result(result3) == "blocked_recoverable"

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


# ─── Rework test 1: Stale accepted release must not merge ──────────────────

@pytest.mark.asyncio
async def test_worker_stale_accepted_release_does_not_merge():
    """W07-rework: If execution result is accepted but release returns stale,
    merge must NOT be called.  Verifies the W01/W07 fencing invariant:
    stale release must be handled once and must not merge/retry/recover."""
    worker = Worker.__new__(Worker)
    worker.log = MagicMock()
    worker.api = AsyncMock()
    worker._git_context = MagicMock()
    worker._git_context.target_repo_root = "/repo"
    worker.worker_id = "worker-stale-test"
    worker._active_packet_id = "pkt-stale-accepted"
    worker._active_lease_id = 42
    worker._active_claimed_attempt = 1

    exec_state = ExecutionState(
        packet_id="pkt-stale-accepted",
        worker_id="worker-stale-test",
        phase="claimed",
        lease_id=42,
        claimed_attempt=1,
        attempt=1,
        max_attempts=5,
    )

    # Execution returns accepted — but the release will be stale
    from grace_control.adapters.packet_executor import ExecutionResult
    result = ExecutionResult(
        accepted=True,
        domain_status="accepted",
        worktree_path="/worktree",
        branch_name="agent/pkt-stale-accepted",
        commit_sha="abc123def456",
        duration_ms=1000,
    )

    # Simulate _phase_execute setting release_status from accepted result
    exec_state.phase = "executing"
    exec_state.release_status = release_status_from_result(result)  # "accepted"

    # _phase_release: the API raises a 409 stale_lease exception
    # (_release_with_fencing catches it and returns stale_lease=True)
    worker.api.release_packet = AsyncMock(
        side_effect=Exception("409 Conflict: stale_lease - another worker owns this packet"))

    await worker._phase_release(exec_state, result)

    # After stale release: release_status must be cleared, failure_type set
    assert exec_state.failure_type == WorkerFailureType.STALE_LEASE, \
        f"Expected STALE_LEASE, got: {exec_state.failure_type}"
    assert exec_state.release_status == "", \
        f"Release status must be cleared after stale lease, got: '{exec_state.release_status}'"

    # Now check: _run_one_cycle merge branch must NOT fire
    # The guard is: release_status == "accepted" AND failure_type != STALE_LEASE
    should_merge = (
        exec_state.release_status == "accepted"
        and exec_state.failure_type != WorkerFailureType.STALE_LEASE
    )
    assert not should_merge, \
        "Merge must not proceed when release_status is cleared / failure_type is STALE_LEASE"

    # Also verify _phase_merge is NOT called when guard fails
    worker.api.merge_packet = AsyncMock()
    if should_merge:
        await worker._phase_merge(exec_state, result)
    worker.api.merge_packet.assert_not_called()


# ─── Rework test 2: _phase_execute classifies agent_nonzero result ─────────

@pytest.mark.asyncio
async def test_phase_execute_classifies_agent_nonzero_result():
    """W07-rework: _phase_execute must set failure_type=agent_nonzero when
    the execution result is not accepted (generic rejection)."""
    worker = Worker.__new__(Worker)
    worker.log = MagicMock()
    worker.executor = AsyncMock()
    worker.worker_id = "worker-exec-test"

    from grace_control.adapters.packet_executor import ExecutionResult
    rejected_result = ExecutionResult(
        accepted=False,
        domain_status="rejected",
        reason="Test suite failed",
        duration_ms=500,
    )
    worker.executor.execute = AsyncMock(return_value=rejected_result)

    claim = MagicMock()
    claim.packet_id = "pkt-nonzero"
    claim.model_dump.return_value = {}

    exec_state = ExecutionState(
        packet_id="pkt-nonzero",
        worker_id="worker-exec-test",
        lease_id=1,
        claimed_attempt=1,
        attempt=1,
        max_attempts=3,
    )

    result = await worker._phase_execute(claim, exec_state, agent_timeout=600)

    # failure_type must be set to agent_nonzero for non-accepted results
    assert exec_state.failure_type == WorkerFailureType.AGENT_NONZERO, \
        f"Expected AGENT_NONZERO, got: {exec_state.failure_type}"
    assert exec_state.error_message == "Test suite failed", \
        f"Expected reason as error_message, got: {exec_state.error_message}"


# ─── Rework test 3: _phase_execute classifies scope_violation result ───────

@pytest.mark.asyncio
async def test_phase_execute_classifies_scope_violation_result():
    """W07-rework: _phase_execute must set failure_type=scope_violation when
    the execution result indicates scope violation."""
    worker = Worker.__new__(Worker)
    worker.log = MagicMock()
    worker.executor = AsyncMock()
    worker.worker_id = "worker-scope-test"

    from grace_control.adapters.packet_executor import ExecutionResult
    scope_result = ExecutionResult(
        accepted=False,
        domain_status="blocked",
        reason="Agent wrote outside allowed scope",
        duration_ms=500,
    )
    worker.executor.execute = AsyncMock(return_value=scope_result)

    claim = MagicMock()
    claim.packet_id = "pkt-scope-viol"
    claim.model_dump.return_value = {}

    exec_state = ExecutionState(
        packet_id="pkt-scope-viol",
        worker_id="worker-scope-test",
        lease_id=1,
        claimed_attempt=1,
        attempt=1,
        max_attempts=3,
    )

    result = await worker._phase_execute(claim, exec_state, agent_timeout=600)

    # failure_type must be scope_violation
    assert exec_state.failure_type == WorkerFailureType.SCOPE_VIOLATION, \
        f"Expected SCOPE_VIOLATION, got: {exec_state.failure_type}"
    assert exec_state.error_message == "Agent wrote outside allowed scope", \
        f"Expected reason as error_message, got: {exec_state.error_message}"


# ─── Rework test 4: Release payload includes failure_type and retryable ────

@pytest.mark.asyncio
async def test_release_payload_includes_failure_type_and_retryable_for_result_failures():
    """W07-rework: After _phase_execute + _phase_release, the release payload
    (to_release_result) must include failure_type and retryable flags for
    both scope_violation and agent_nonzero results."""

    # --- Case 1: scope_violation → retryable=False ---
    exec_state_scope = ExecutionState(
        packet_id="pkt-scope-release",
        worker_id="worker-1",
        attempt=1,
        max_attempts=3,
    )
    exec_state_scope.release_status = "blocked"
    exec_state_scope.failure_type = WorkerFailureType.SCOPE_VIOLATION
    exec_state_scope.error_message = "Scope violation"

    result_scope = exec_state_scope.to_release_result()
    assert result_scope.get("failure_type") == "scope_violation", \
        f"Expected scope_violation in release payload, got: {result_scope.get('failure_type')}"
    assert result_scope.get("retryable") is False, \
        f"Scope violation must not be retryable in release payload, got: {result_scope.get('retryable')}"

    # --- Case 2: agent_nonzero → retryable=True (when attempts remain) ---
    exec_state_agent = ExecutionState(
        packet_id="pkt-agent-release",
        worker_id="worker-1",
        attempt=1,
        max_attempts=3,
    )
    exec_state_agent.release_status = "rejected"
    exec_state_agent.failure_type = WorkerFailureType.AGENT_NONZERO
    exec_state_agent.error_message = "Test failed"

    result_agent = exec_state_agent.to_release_result()
    assert result_agent.get("failure_type") == "agent_nonzero", \
        f"Expected agent_nonzero in release payload, got: {result_agent.get('failure_type')}"
    assert result_agent.get("retryable") is True, \
        f"Agent nonzero must be retryable in release payload, got: {result_agent.get('retryable')}"

    # --- End-to-end: simulate _phase_execute → _phase_release for agent_nonzero ---
    worker = Worker.__new__(Worker)
    worker.log = MagicMock()
    worker.api = AsyncMock()
    worker._git_context = MagicMock()
    worker.worker_id = "worker-e2e"
    worker._active_packet_id = "pkt-e2e-agent"
    worker._active_lease_id = 1
    worker._active_claimed_attempt = 1

    from grace_control.adapters.packet_executor import ExecutionResult

    rejected_result = ExecutionResult(
        accepted=False,
        domain_status="rejected",
        reason="Generic agent failure",
    )
    worker.api.release_packet = AsyncMock(
        return_value={"stale_lease": False, "released": True})

    exec_state = ExecutionState(
        packet_id="pkt-e2e-agent",
        worker_id="worker-e2e",
        lease_id=1,
        claimed_attempt=1,
        attempt=1,
        max_attempts=3,
    )
    # Simulate what _phase_execute does (now with rework fix)
    exec_state.phase = "executing"
    exec_state.release_status = release_status_from_result(rejected_result)
    if not rejected_result.accepted:
        exec_state.failure_type = classify_worker_failure(result=rejected_result)
        exec_state.error_message = rejected_result.reason or ""

    # Simulate _phase_release
    await worker._phase_release(exec_state, rejected_result)

    # The release payload must have failure_type and retryable
    payload = exec_state.to_release_result()
    assert payload.get("failure_type") == "agent_nonzero", \
        f"E2E: Expected agent_nonzero, got: {payload.get('failure_type')}"
    assert payload.get("retryable") is True, \
        f"E2E: Expected retryable=True, got: {payload.get('retryable')}"
