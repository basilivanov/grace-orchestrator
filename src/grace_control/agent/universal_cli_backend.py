# AI_HEADER: universal_cli_backend — UniversalCliAgentBackend (W7)
# START_MODULE_CONTRACT
# purpose: Implementation of ExecutionBackend that runs a local CLI agent
#          via AgentRunService. Configured entirely through agent profiles;
#          no hardcoded CLI names (opencode/codex/agy/gemini/claude).
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
from grace_control.config.settings import settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.agent_run_service import AgentRunService

_log = GraceLogger("cli_backend")

_OPENCODE_ENV_KEYS = {
    "OPENCODE_SERVER_URL": "opencode_server_url",
    "OPENCODE_SERVER_PASSWORD": "opencode_server_password",
}


def _profile_references_env(executor: dict, env_name: str) -> bool:
    """Return True if the profile's command/extras reference ${env_name}.

    Used to decide whether to inject OPENCODE_SERVER_URL etc. into the
    subprocess env. We only inject when the profile actually uses the
    placeholder — otherwise `opencode run` picks up the env var and tries
    to attach to a non-existent server session, exiting with
    "Session not found".
    """
    needle = "${" + env_name + "}"
    cmd = executor.get("command") or []
    extras = executor.get("extras") or []
    return any(needle in str(t) for t in list(cmd) + list(extras))


class UniversalCliAgentBackend(ExecutionBackend):
    def __init__(self, run_service: AgentRunService | None = None) -> None:
        self._run_service = run_service or AgentRunService()

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        executor = request.executor or {}
        # Inject opencode server attach vars from settings into agent env
        # ONLY if the profile's command/extras reference them. Unconditional
        # injection caused `opencode run` to try attaching to a stale server
        # session and fail with "Session not found" (since `opencode run`
        # reads these env vars regardless of flags).
        executor_env = executor.get("env", {})
        for env_name, setting_name in _OPENCODE_ENV_KEYS.items():
            if not _profile_references_env(executor, env_name):
                continue
            val = getattr(settings, setting_name, "")
            if val:
                executor_env[env_name] = val
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
        )

    async def cancel(self, request: ExecutionRequest) -> None:
        _log.warn("cli_cancel_noop", packet_id=request.packet_id)
