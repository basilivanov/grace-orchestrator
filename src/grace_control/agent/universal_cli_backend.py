# AI_HEADER: universal_cli_backend — UniversalCliAgentBackend (W7)
# START_MODULE_CONTRACT
# purpose: Implementation of ExecutionBackend that runs a local CLI agent
#          via AgentRunService. Configured entirely through agent profiles;
#          no hardcoded CLI tool names.
# inputs: ExecutionRequest with executor={executor_id, ...}.
# returns: ExecutionResult with accepted, stdout, stderr, exit_code, etc.
# side_effects: Spawns subprocess via AgentRunService.
# error_behavior: Never raises; failures encoded in result.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: UniversalCliAgentBackend
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from grace_control.agent.backend import ExecutionBackend, ExecutionRequest, ExecutionResult
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.agent_run_service import AgentRunService

_log = GraceLogger("cli_backend")

class UniversalCliAgentBackend(ExecutionBackend):
    def __init__(self, run_service: AgentRunService | None = None,
                 stdout_log_path: Path | str | None = None,
                 stderr_log_path: Path | str | None = None) -> None:
        self._run_service = run_service or AgentRunService()
        self._stdout_log_path = stdout_log_path
        self._stderr_log_path = stderr_log_path

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        executor = request.executor or {}
        executor_env = executor.get("env", {})
        executor["env"] = executor_env

        _log.info("cli_run_start", packet_id=request.packet_id, executor_id=executor.get("executor_id", "?"))

        packet_markdown = (request.spec or {}).get("packet_markdown", "")
        if not packet_markdown and request.session_dir is not None:
            candidate = Path(request.session_dir) / "packets" / request.packet_id / "EXECUTION_PACKET.md"
            if candidate.exists():
                packet_markdown = candidate.read_text()

        out = await self._run_service.run(
            executor,
            packet_id=request.packet_id,
            worktree_path=Path(request.worktree_path) if request.worktree_path else Path("."),
            state_root=request.session_dir or (Path(request.worktree_path) if request.worktree_path else Path(".")),
            packet_markdown=packet_markdown,
            timeout_seconds=request.timeout_s,
            run_dir=request.evidence_dir,
            resume_session_id=request.resume_session_id,
            fork=request.fork_session,
            stdout_log_path=self._stdout_log_path,
            stderr_log_path=self._stderr_log_path,
        )

        accepted = bool(out.get("accepted"))
        _log.info("cli_run_done", packet_id=request.packet_id,
            accepted=accepted, domain_status=out.get("domain_status"), exit_code=out.get("exit_code"))

        return ExecutionResult(
            accepted=accepted,
            domain_status=out.get("domain_status", "failed"),
            worktree_path=Path(out.get("worktree_path", "")) if out.get("worktree_path") else request.worktree_path,
            branch_name=request.branch_name,
            commit_sha="",
            stdout=out.get("stdout", ""),
            stderr=out.get("stderr", ""),
            duration_ms=int(out.get("duration_ms", 0)),
            changed_files=[],
            evidence=out,
            reason=out.get("reason", ""),
            errors=[out.get("reason")] if out.get("reason") else [],
            registry_reason="",
            model=out.get("model", ""),
            command_preview=out.get("command_preview", []),
            prompt=out.get("prompt", ""),
        )

    async def cancel(self, request: ExecutionRequest) -> None:
        _log.warn("cli_cancel_noop", packet_id=request.packet_id)
