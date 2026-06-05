# ############################################################################
# AI_HEADER: api_backend
# ROLE: ApiAgentBackend — non-Prefect execution backend that delegates to
#       AgentGatewayService. W7 of
#       source/codex/tz-api-first-cleanup-waves-w0-w11.md.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Implementation of ExecutionBackend that builds an ExecutionRequest
#          from the orchestrator's spec, calls AgentGatewayService.dispatch,
#          and maps the gateway's normalized result to ExecutionResult.
# inputs: ExecutionRequest — provider/model come from request.executor.
# returns: ExecutionResult.
# side_effects: Writes .agent_gateway.log to worktree.
# emitted_logs: api_run_start, api_run_done, api_run_failed, api_cancel_noop.
# error_behavior: Never raises; failures encoded in result.accepted=False.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ApiAgentBackend
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from grace_control.agent.backend import ExecutionRequest, ExecutionResult
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.agent_gateway_service import AgentGatewayService

_log = GraceLogger("api_backend")


class ApiAgentBackend:
    """Non-Prefect execution backend. All provider/model/timeout policy lives
    in AgentGatewayService — this class is the thin ExecutionBackend binding.
    """

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Initialize the backend with an injectable gateway.
    # inputs: gateway (AgentGatewayService | None).
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self, gateway: AgentGatewayService | None = None) -> None:
        self._gateway = gateway or AgentGatewayService()

    # START_FUNCTION_CONTRACT
    # name: run
    # purpose: Translate request → gateway.dispatch → ExecutionResult.
    # inputs: request (ExecutionRequest). request.executor must contain
    #         {provider, model}; request.spec may contain
    #         {packet_markdown, role}.
    # returns: ExecutionResult.
    # side_effects: Writes .agent_gateway.log to worktree_path.
    # emitted_logs: api_run_start, api_run_done, api_run_failed.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        executor = request.executor or {}
        provider = executor.get("provider", "mock")
        model = executor.get("model", "")
        role = (request.spec or {}).get("role", "coder")
        packet_markdown = (request.spec or {}).get("packet_markdown", "")
        if not packet_markdown and request.session_dir is not None:
            candidate = Path(request.session_dir) / "packets" / request.packet_id / "EXECUTION_PACKET.md"
            if candidate.exists():
                packet_markdown = candidate.read_text()

        _log.info("api_run_start", packet_id=request.packet_id,
            provider=provider, model=model, role=role, timeout_s=request.timeout_s)

        out = self._gateway.dispatch(
            provider=provider, model=model, role=role,
            packet_id=request.packet_id, packet_markdown=packet_markdown,
            worktree_path=request.worktree_path,
            timeout_seconds=request.timeout_s,
            max_retries=int((request.spec or {}).get("max_retries", 0)),
        )

        accepted = bool(out.get("accepted"))
        if not accepted:
            _log.warn("api_run_failed", packet_id=request.packet_id,
                reason=out.get("reason", "")[:200])
        else:
            _log.info("api_run_done", packet_id=request.packet_id,
                duration_ms=out.get("duration_ms", 0))

        return ExecutionResult(
            accepted=accepted,
            domain_status="accepted" if accepted else "rejected",
            worktree_path=request.worktree_path,
            branch_name=request.branch_name,
            commit_sha="",
            stdout=out.get("stdout", ""),
            stderr=out.get("stderr", ""),
            duration_ms=int(out.get("duration_ms", 0)),
            changed_files=list(out.get("changed_files") or []),
            evidence={
                "provider": provider, "model": model, "role": role,
                "messages": out.get("messages") or [],
                "attempts": out.get("attempts", 0),
            },
            reason=out.get("reason") or "",
            errors=[out.get("reason")] if out.get("reason") else [],
            registry_reason="",
        )

    # START_FUNCTION_CONTRACT
    # name: cancel
    # purpose: No-op. ApiAgentBackend has no in-flight subprocess to kill.
    # inputs: request (ExecutionRequest).
    # returns: None.
    # side_effects: None.
    # emitted_logs: api_cancel_noop.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    async def cancel(self, request: ExecutionRequest) -> None:
        _log.warn("api_cancel_noop", packet_id=request.packet_id,
            reason="api backend has no in-flight subprocess to cancel")
