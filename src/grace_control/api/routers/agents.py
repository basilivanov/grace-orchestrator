# AI_HEADER: api_routers_agents — POST /api/agents/run (W7 UniversalCliAgentBackend)
# START_MODULE_CONTRACT
# purpose: Execute a CLI agent via UniversalCliAgentBackend or ApiAgentBackend
#          based on the executor_id lookup in agent_profiles.yaml.
#          API/OpenAPI remains the only public control plane.
# inputs: RunRequest {packet_id, executor_id, role, model, effort, worktree_path, ...}.
# returns: RunResponse.
# side_effects: Spawns subprocess via the selected backend.
# error_behavior: 400 on invalid request; backend errors in response body.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - router: APIRouter   - class: RunRequest   - class: RunResponse
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grace_control.agent import select_backend
from grace_control.agent.backend import ExecutionRequest
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("agents_router")
router = APIRouter(tags=["agents"])


class RunRequest(BaseModel):
    packet_id: str
    executor_id: str = "coder_opencode"
    role: str = "coder"
    model: str = ""
    effort: str = ""
    worktree_path: str = ""
    packet_markdown: str = ""
    timeout_seconds: int = 900
    max_retries: int = 0


class RunResponse(BaseModel):
    accepted: bool
    domain_status: str = ""
    executor_id: str = ""
    command_preview: list[str] = Field(default_factory=list)
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    stdout_path: str = ""
    stderr_path: str = ""
    worktree_path: str = ""
    branch_name: str = ""
    duration_ms: int = 0
    reason: str = ""
    artifacts: list[str] = Field(default_factory=list)


@router.post("/run", response_model=RunResponse)
def run_agent(req: RunRequest) -> RunResponse:
    _log.info("agent_run_request", packet_id=req.packet_id, executor_id=req.executor_id)

    from grace_control.core.executor_selector import load_profiles
    profiles = load_profiles()
    executors = profiles.get("codex", {}).get("executors", [])
    matching = [e for e in executors if e.get("executor_id") == req.executor_id]
    if not matching:
        raise HTTPException(status_code=400, detail=f"unknown executor_id: {req.executor_id}")
    executor = dict(matching[0])

    if req.model:
        executor["model"] = req.model
    if req.effort:
        executor["effort"] = req.effort
    executor.setdefault("timeout_seconds", req.timeout_seconds)

    import asyncio
    backend = select_backend("cli")
    er = ExecutionRequest(
        packet_id=req.packet_id,
        spec={"role": req.role, "packet_markdown": req.packet_markdown},
        worktree_path=None, branch_name="",
        executor=executor, timeout_s=req.timeout_seconds,
    )

    result = asyncio.run(backend.run(er))

    return RunResponse(
        accepted=result.accepted,
        domain_status=result.domain_status,
        executor_id=executor.get("executor_id", ""),
        command_preview=result.evidence.get("command_preview", []) if isinstance(result.evidence, dict) else [],
        exit_code=result.evidence.get("exit_code", -1) if isinstance(result.evidence, dict) else -1,
        stdout=result.stdout,
        stderr=result.stderr,
        stdout_path=result.evidence.get("stdout_path", "") if isinstance(result.evidence, dict) else "",
        stderr_path=result.evidence.get("stderr_path", "") if isinstance(result.evidence, dict) else "",
        worktree_path=str(result.worktree_path) if result.worktree_path else "",
        branch_name=result.branch_name,
        duration_ms=result.duration_ms,
        reason=result.reason,
        artifacts=result.evidence.get("artifacts", []) if isinstance(result.evidence, dict) else [],
    )
