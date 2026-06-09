# ############################################################################
# AI_HEADER: dev_replay_router
# ROLE: FastAPI router for /api/dev/runs — dev-only pipeline replaying tools.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose REST endpoints to rerun T0/T1/T2, verifier, and reviewer
#          stages on an existing run worktree.
# inputs: HTTP POST requests with JSON payload.
# returns: JSON report containing stage outcome, status, and summary.
# side_effects: Reruns verification commands, updates DB PacketRun.result_json.
# emitted_logs: None.
# error_behavior: Returns 404 on RUN_NOT_FOUND or DEV_TOOLS_DISABLED; 400 on other validation failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#   - class: ReplayAcceptanceRequest
#   - class: RerunVerifierRequest
#   - class: RerunReviewerRequest
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.dev_run_replay_service import DevReplayException, DevRunReplayService

_log = GraceLogger("dev_replay_router")

router = APIRouter(prefix="/api/dev/runs", tags=["dev_replay"])
_service = DevRunReplayService()


class ReplayAcceptanceRequest(BaseModel):
    stage: str = Field(default="t0", description="Stage to rerun: t0, t1, t2, t2_browser, t3_visual, full_acceptance")
    worktree_path: str | None = Field(default=None, description="Optional worktree path override")
    run_dir_suffix: str | None = Field(default=None, description="Optional suffix for run dir")


class RerunVerifierRequest(BaseModel):
    worktree_path: str | None = Field(default=None, description="Optional worktree path override")
    acceptance_report_path: str | None = Field(default=None, description="Optional acceptance report override")


class RerunReviewerRequest(BaseModel):
    worktree_path: str | None = Field(default=None, description="Optional worktree path override")
    acceptance_report_path: str | None = Field(default=None, description="Optional acceptance report override")
    verifier_report_path: str | None = Field(default=None, description="Optional verifier report override")


# START_BLOCK_EXCEPTION_HANDLER
# START_FUNCTION_CONTRACT
# name: handle_replay_exception
# purpose: Map DevReplayException codes to HTTP error responses.
# inputs: e — DevReplayException with code, message, extra.
# returns: Never returns (always raises HTTPException).
# side_effects: Raises HTTP 404 or 400.
# emitted_logs: None.
# error_behavior: All paths raise HTTPException.
# END_FUNCTION_CONTRACT
def handle_replay_exception(e: DevReplayException):
    if e.code in ("DEV_TOOLS_DISABLED", "RUN_NOT_FOUND", "PACKET_NOT_FOUND"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": e.code, "message": e.message}
        )
    elif e.code == "WORKTREE_MISSING":
        detail = {
            "error": e.code,
            "message": e.message
        }
        if "patch_path" in e.extra:
            detail["patch_path"] = e.extra["patch_path"]
            detail["message"] = "worktree was cleaned; rehydrate from patch manually or rerun coder"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": e.code, "message": e.message}
        )

# END_BLOCK_EXCEPTION_HANDLER

# START_BLOCK_ROUTES
# START_FUNCTION_CONTRACT
# name: replay_acceptance
# purpose: Rerun a specific acceptance stage (t0, t1, t2, t2_browser, t3_visual, full_acceptance) on an existing run.
# inputs: run_id (path), req — ReplayAcceptanceRequest body.
# returns: dict with data from the replay service.
# side_effects: Runs acceptance stage commands on the worktree.
# emitted_logs: None.
# error_behavior: Delegates to handle_replay_exception on DevReplayException.
# END_FUNCTION_CONTRACT
@router.post("/{run_id}/replay-acceptance")
async def replay_acceptance(run_id: str, req: ReplayAcceptanceRequest):
    try:
        res = _service.replay_acceptance(
            run_id=run_id,
            stage=req.stage,
            worktree_path_override=req.worktree_path
        )
        return {
            "data": res,
            "timestamp": datetime.now(UTC).isoformat() + "Z"
        }
    except DevReplayException as e:
        handle_replay_exception(e)


# START_FUNCTION_CONTRACT
# name: rerun_verifier
# purpose: Rerun the verifier stage on an existing run's worktree.
# inputs: run_id (path), req — RerunVerifierRequest body.
# returns: dict with data from the verifier service.
# side_effects: Runs verifier commands; may update DB.
# emitted_logs: None.
# error_behavior: Delegates to handle_replay_exception on DevReplayException.
# END_FUNCTION_CONTRACT
@router.post("/{run_id}/rerun-verifier")
async def rerun_verifier(run_id: str, req: RerunVerifierRequest):
    try:
        res = await _service.rerun_verifier(
            run_id=run_id,
            worktree_path_override=req.worktree_path
        )
        return {
            "data": res,
            "timestamp": datetime.now(UTC).isoformat() + "Z"
        }
    except DevReplayException as e:
        handle_replay_exception(e)


# START_FUNCTION_CONTRACT
# name: rerun_reviewer
# purpose: Rerun the reviewer stage on an existing run's worktree.
# inputs: run_id (path), req — RerunReviewerRequest body.
# returns: dict with data from the reviewer service.
# side_effects: Runs reviewer commands; may update DB.
# emitted_logs: None.
# error_behavior: Delegates to handle_replay_exception on DevReplayException.
# END_FUNCTION_CONTRACT
@router.post("/{run_id}/rerun-reviewer")
async def rerun_reviewer(run_id: str, req: RerunReviewerRequest):
    try:
        res = await _service.rerun_reviewer(
            run_id=run_id,
            worktree_path_override=req.worktree_path
        )
        return {
            "data": res,
            "timestamp": datetime.now(UTC).isoformat() + "Z"
        }
    except DevReplayException as e:
        handle_replay_exception(e)

# END_BLOCK_ROUTES
