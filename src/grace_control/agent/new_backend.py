# ############################################################################
# AI_HEADER: new_backend
# ROLE: Stub for the future non-prefect execution backend.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Stand-in for a future direct-subprocess / multi-agent backend that
#          does not depend on prefect_grace. Not yet wired in production —
#          kept for the architecture to compile and for future agents to
#          implement.
# inputs: ExecutionRequest.
# returns: ExecutionResult.accepted=False with reason "not implemented".
# side_effects: None.
# emitted_logs: new_backend_unimplemented.
# error_behavior: Never raises; returns failure result.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: NewDirectBackend
# END_MODULE_MAP

from grace_control.agent.backend import ExecutionBackend, ExecutionRequest, ExecutionResult
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("new_backend")


class NewDirectBackend:
    """Future replacement for LegacyPrefectBackend. Not yet implemented."""

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        _log.error("new_backend_unimplemented", packet_id=request.packet_id)
        return ExecutionResult(
            accepted=False,
            domain_status="failed",
            worktree_path=request.worktree_path,
            branch_name=request.branch_name,
            commit_sha="",
            stdout="",
            stderr="",
            duration_ms=0,
            reason="NewDirectBackend not yet implemented; legacy backend required",
        )

    async def cancel(self, request: ExecutionRequest) -> None:
        _log.warn("new_cancel_noop", packet_id=request.packet_id)
