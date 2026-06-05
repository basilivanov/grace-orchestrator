# AI_HEADER: api_routers_agents — POST /api/agents/run (W7 UniversalCliAgentBackend)
# START_MODULE_CONTRACT
# purpose: Execute a CLI agent via UniversalCliAgentBackend using
#          declarative profiles from `agents:` in agent_profiles.yaml.
#          Resolves executor_id from profiles, not from codex.executors.
#          Async route, no asyncio.run().
# inputs: RunRequest {packet_id, executor_id, ...}.
# returns: RunResponse.
# side_effects: Spawns subprocess via UniversalCliAgentBackend.
# error_behavior: 400 on unknown executor_id, backend errors in body.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - router: APIRouter   - class: RunRequest   - class: RunResponse
# END_MODULE_MAP

from __future__ import annotations
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from grace_control.agent import select_backend
from grace_control.agent.backend import ExecutionRequest
from grace_control.config.agent_profiles import get_agent_profile, load_agent_profiles
from grace_control.services.agent_profile_validator import AgentProfileValidator
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
    accepted: bool; domain_status: str = ""; executor_id: str = ""
    command_preview: list[str] = Field(default_factory=list)
    exit_code: int = -1; stdout: str = ""; stderr: str = ""
    stdout_path: str = ""; stderr_path: str = ""
    worktree_path: str = ""; branch_name: str = ""
    duration_ms: int = 0; reason: str = ""
    artifacts: list[str] = Field(default_factory=list)


@router.post("/run", response_model=RunResponse)
async def run_agent(req: RunRequest) -> RunResponse:
    _log.info("agent_run_request", packet_id=req.packet_id, executor_id=req.executor_id)
    profile = get_agent_profile(req.executor_id)
    if not profile:
        raise HTTPException(status_code=400, detail=f"unknown executor_id: {req.executor_id}")
    if not req.worktree_path:
        raise HTTPException(status_code=400, detail="worktree_path is required")

    executor = profile.to_dict()
    if req.model:
        executor["model"] = req.model
    if req.effort:
        executor["effort"] = req.effort

    backend = select_backend("cli")
    er = ExecutionRequest(
        packet_id=req.packet_id,
        spec={"role": req.role, "packet_markdown": req.packet_markdown},
        worktree_path=Path(req.worktree_path),
        branch_name="",
        executor=executor,
        timeout_s=req.timeout_seconds,
    )
    result = await backend.run(er)

    return RunResponse(
        accepted=result.accepted,
        domain_status=result.domain_status,
        executor_id=profile.executor_id,
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


# ── Agent profile inspection (W14.3) ──────────────────────────────────


@router.get("/profiles")
def list_profiles() -> dict:
    profiles = load_agent_profiles()
    return {"data": [
        {
            "executor_id": pid,
            "backend": p.backend,
            "model": p.model,
            "effort": p.effort,
            "command_preview": list(p.command) if p.command else [],
            "input_mode": p.input_mode,
            "timeout_seconds": p.timeout_seconds,
        }
        for pid, p in sorted(profiles.items())
    ]}


@router.get("/profiles/{executor_id}")
def get_profile(executor_id: str) -> dict:
    p = get_agent_profile(executor_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"profile {executor_id} not found")
    return {
        "data": {
            "executor_id": p.executor_id,
            "backend": p.backend,
            "model": p.model,
            "effort": p.effort,
            "command": list(p.command) if p.command else [],
            "cwd": p.cwd_template,
            "input_mode": p.input_mode,
            "timeout_seconds": p.timeout_seconds,
            "env_preview": {k: "****" if "KEY" in k.upper() or "TOKEN" in k.upper() else v
                           for k, v in p.env.items()},
        }
    }


@router.post("/profiles/{executor_id}/validate")
def validate_profile(executor_id: str, body: dict | None = None) -> dict:
    p = get_agent_profile(executor_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"profile {executor_id} not found")
    check_exe = (body or {}).get("check_executable", False)
    wt = (body or {}).get("worktree_path", None)
    validator = AgentProfileValidator()
    return {"data": validator.validate(p, check_executable=check_exe, worktree_path=wt)}


@router.post("/profiles/{executor_id}/dry-run")
def dry_run_profile(executor_id: str, body: dict | None = None) -> dict:
    p = get_agent_profile(executor_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"profile {executor_id} not found")
    wt = (body or {}).get("worktree_path", None)
    validator = AgentProfileValidator()
    return {"data": validator.dry_run(p, worktree_path=wt)}
