# ############################################################################
# AI_HEADER: api_routers_agents
# ROLE: HTTP binding for AgentGatewayService — POST /api/agents/run.
#       W7 of source/codex/tz-api-first-cleanup-waves-w0-w11.md.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose AgentGatewayService over HTTP for direct invocation and
#          for the ApiAgentBackend smoke path. Never imports provider SDKs.
# inputs: RunRequest JSON body {packet_id, role, model, provider,
#         worktree_path, packet_markdown, timeout_seconds}.
# returns: RunResponse JSON — see payload below.
# side_effects: Writes .agent_gateway.log to worktree_path.
# emitted_logs: agent_run_request.
# error_behavior: 400 on invalid provider; never raises otherwise.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - POST /run
#   - class: RunRequest
#   - class: RunResponse
#   - function: _to_response
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.agent_gateway_service import (
    VALID_PROVIDERS,
    AgentGatewayService,
)

_log = GraceLogger("agents_router")

router = APIRouter(tags=["agents"])
_svc = AgentGatewayService()


class RunRequest(BaseModel):
    """Body of POST /api/agents/run."""
    packet_id: str
    role: str = "coder"
    model: str = ""
    provider: str = "mock"
    worktree_path: str = ""
    packet_markdown: str = ""
    timeout_seconds: int = 600
    max_retries: int = 0


class RunResponse(BaseModel):
    """Response of POST /api/agents/run. Mirrors the gateway output."""
    accepted: bool
    domain_status: str
    stdout: str
    stderr: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    reason: str = ""
    duration_ms: int = 0
    attempts: int = 0
    artifacts: list[str] = Field(default_factory=list)


# START_FUNCTION_CONTRACT
# name: _to_response
# purpose: Map a gateway output dict to the public RunResponse shape.
# inputs: out (dict — AgentGatewayService.dispatch output).
# returns: RunResponse.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _to_response(out: dict[str, Any]) -> RunResponse:
    accepted = bool(out.get("accepted"))
    return RunResponse(
        accepted=accepted,
        domain_status="accepted" if accepted else "rejected",
        stdout=out.get("stdout", ""),
        stderr=out.get("stderr", ""),
        messages=list(out.get("messages") or []),
        changed_files=list(out.get("changed_files") or []),
        reason=out.get("reason", "") or "",
        duration_ms=int(out.get("duration_ms", 0)),
        attempts=int(out.get("attempts", 0)),
        artifacts=[str(p) for p in (out.get("changed_files") or [])],
    )


# START_FUNCTION_CONTRACT
# name: run_agent
# purpose: HTTP wrapper around AgentGatewayService.dispatch.
# inputs: req (RunRequest).
# returns: RunResponse.
# side_effects: Writes .agent_gateway.log to req.worktree_path.
# emitted_logs: agent_run_request, agent_run_response.
# error_behavior: 400 on invalid provider; never raises otherwise.
# END_FUNCTION_CONTRACT
@router.post("/run", response_model=RunResponse)
def run_agent(req: RunRequest) -> RunResponse:
    if req.provider not in VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown provider: {req.provider!r}; expected one of {sorted(VALID_PROVIDERS)}",
        )
    _log.info("agent_run_request", packet_id=req.packet_id,
        provider=req.provider, model=req.model, role=req.role,
        timeout_s=req.timeout_seconds, max_retries=req.max_retries)
    out = _svc.dispatch(
        provider=req.provider, model=req.model, role=req.role,
        packet_id=req.packet_id, packet_markdown=req.packet_markdown,
        worktree_path=Path(req.worktree_path) if req.worktree_path else Path("."),
        timeout_seconds=req.timeout_seconds, max_retries=req.max_retries,
    )
    _log.info("agent_run_response", packet_id=req.packet_id,
        accepted=out.get("accepted"), attempts=out.get("attempts", 0),
        duration_ms=out.get("duration_ms", 0))
    return _to_response(out)
