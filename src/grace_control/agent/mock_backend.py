# ############################################################################
# AI_HEADER: mock_backend
# ROLE: Mock ExecutionBackend — returns success without spawning a process.
#       Used in tests, local dev, and `execution_backend=mock`. W7 of
#       source/codex/tz-api-first-cleanup-waves-w0-w11.md.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Deterministic, side-effect-free implementation of ExecutionBackend
#          for tests and local development. Writes one empty log line to
#          the worktree so the executor's has_changes() check can be exercised
#          (or skipped when scope is empty).
# inputs: ExecutionRequest.
# returns: ExecutionResult with accepted=True.
# side_effects: Optional one-line write to {worktree_path}/.mock_run.log.
# emitted_logs: mock_run_start, mock_run_done.
# error_behavior: Never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: MockBackend
# END_MODULE_MAP

from __future__ import annotations

import time
from pathlib import Path

from grace_control.agent.backend import ExecutionRequest, ExecutionResult
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("mock_backend")


class MockBackend:
    """In-process backend that always succeeds. No subprocess. No LLM.

    Useful for:
      - local smoke tests
      - CI runs without API keys
      - end-to-end pipe tests (router + executor wiring)
    """

    # START_FUNCTION_CONTRACT
    # name: run
    # purpose: Produce a synthetic successful ExecutionResult in ~0ms.
    # inputs: request (ExecutionRequest).
    # returns: ExecutionResult(accepted=True, domain_status="accepted", ...).
    # side_effects: One line written to .mock_run.log inside worktree_path.
    # emitted_logs: mock_run_start, mock_run_done.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        _log.info("mock_run_start", packet_id=request.packet_id)
        t0 = time.time()
        marker: Path | None = None
        try:
            if request.worktree_path:
                wt = Path(request.worktree_path)
                wt.mkdir(parents=True, exist_ok=True)
                marker = wt / ".mock_run.log"
                marker.write_text(
                    f"mock: {request.packet_id} attempt {request.spec.get('attempt_count', 1)}\n"
                )
        except Exception:
            marker = None
        duration_ms = int((time.time() - t0) * 1000)
        _log.info("mock_run_done", packet_id=request.packet_id,
            duration_ms=duration_ms, marker=str(marker) if marker else "")
        return ExecutionResult(
            accepted=True,
            domain_status="accepted",
            worktree_path=request.worktree_path,
            branch_name=request.branch_name,
            commit_sha="",
            stdout=f"mock backend: packet {request.packet_id}\n",
            stderr="",
            duration_ms=duration_ms,
            changed_files=[str(marker)] if marker else [],
            evidence={"mock": True},
            reason="",
            errors=[],
            registry_reason="",
        )

    # START_FUNCTION_CONTRACT
    # name: cancel
    # purpose: No-op. MockBackend has nothing to cancel.
    # inputs: request (ExecutionRequest).
    # returns: None.
    # side_effects: None.
    # emitted_logs: mock_cancel_noop.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    async def cancel(self, request: ExecutionRequest) -> None:
        _log.warn("mock_cancel_noop", packet_id=request.packet_id)
