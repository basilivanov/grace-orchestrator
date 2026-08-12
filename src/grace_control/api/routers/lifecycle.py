# ############################################################################
# AI_HEADER: lifecycle_router — public HTTP adapter for lifecycle operations
# ROLE: Registers the stable lifecycle API and maps requests to the explicit
#      LifecycleService composition. Mutations continue through Admin audit.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose lifecycle read and control endpoints while keeping HTTP
#          extraction, authorization/audit delegation, and error translation
#          at the API boundary.
# inputs: FastAPI lifecycle requests, bounded bodies, and query parameters.
# returns: Stable lifecycle JSON DTOs and audited control results.
# side_effects: Reads through LifecycleService; confirmed restart/reload
#               operations continue through the canonical Admin dispatcher.
# emitted_logs: Existing Admin control/audit logs.
# error_behavior: Typed service errors map to the historical 400/501/502/503
#                 HTTP semantics.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /api/admin/lifecycle/status
#       - GET /api/admin/lifecycle/versions
#       - GET /api/admin/lifecycle/health/full
#       - POST /api/admin/lifecycle/restart/{target}
#       - POST /api/admin/lifecycle/cleanup
#       - POST /api/admin/lifecycle/shutdown
#       - POST /api/admin/lifecycle/reload
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

from grace_control.api.routers.admin_controls import legacy_admin_action
from grace_control.core.structured_logger import GraceLogger
from grace_control.lifecycle_composition import build_lifecycle_service
from grace_control.services.lifecycle_service import LifecycleStateMissingError

_log = GraceLogger("lifecycle_router")

router = APIRouter(
    prefix="/api/admin/lifecycle",
    tags=["lifecycle"],
    responses={
        401: {"description": "Unauthorized"},
        502: {"description": "Supervisor socket unreachable"},
        503: {"description": "Supervisor not running"},
    },
)


# START_BLOCK_READS
# START_FUNCTION_CONTRACT
# name: status
# purpose: Return the combined supervisor, worker, and version lifecycle DTO.
# inputs: None.
# returns: Historical status response.
# side_effects: Reads the composed lifecycle service ports.
# emitted_logs: None.
# error_behavior: Missing state maps to HTTP 503.
# END_FUNCTION_CONTRACT
@router.get("/status")
async def status() -> dict[str, Any]:
    try:
        return build_lifecycle_service().status()
    except LifecycleStateMissingError as exc:
        raise HTTPException(503, str(exc)) from exc


# START_FUNCTION_CONTRACT
# name: versions
# purpose: Return current code and supervisor-child version details.
# inputs: None.
# returns: Historical versions response.
# side_effects: Reads the composed lifecycle service ports.
# emitted_logs: None.
# error_behavior: Missing state maps to HTTP 503.
# END_FUNCTION_CONTRACT
@router.get("/versions")
async def versions() -> dict[str, Any]:
    try:
        return build_lifecycle_service().versions()
    except LifecycleStateMissingError as exc:
        raise HTTPException(503, str(exc)) from exc


# START_FUNCTION_CONTRACT
# name: health_full
# purpose: Return the full degraded-safe lifecycle health snapshot.
# inputs: None.
# returns: Historical health response, including issue list and liveness flags.
# side_effects: Reads the composed lifecycle service ports.
# emitted_logs: None.
# error_behavior: Degraded runtime is represented in a normal HTTP 200 DTO.
# END_FUNCTION_CONTRACT
@router.get("/health/full")
async def health_full() -> dict[str, Any]:
    return build_lifecycle_service().health_full()


# END_BLOCK_READS


# START_BLOCK_MUTATIONS
# START_FUNCTION_CONTRACT
# name: restart_endpoint
# purpose: Route a confirmed restart through the canonical Admin control and
#          audit path.
# inputs: request, target (api/workers/all), and bounded body.
# returns: Audited local-control response.
# side_effects: May issue one supervisor restart through the local dispatcher.
# emitted_logs: Admin action requested/completed/failed.
# error_behavior: Invalid targets return HTTP 400 before any mutation.
# END_FUNCTION_CONTRACT
@router.post("/restart/{target}")
async def restart_endpoint(
    request: Request,
    target: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    action = {
        "api": "restart_api",
        "workers": "restart_workers",
        "all": "restart_all",
    }.get(target)
    if action is None:
        from grace_control.services.admin_control_security import require_control_request

        require_control_request(request)
        raise HTTPException(400, f"target must be api|workers|all, got {target!r}")
    return await legacy_admin_action(
        request,
        action=action,
        entity_type="project",
        entity_id=None,
        body=body,
    )


# START_FUNCTION_CONTRACT
# name: cleanup_endpoint
# purpose: Preserve the audited but unavailable legacy cleanup alias.
# inputs: request, bounded body, and cleanup query parameters.
# returns: Audited unavailable response.
# side_effects: Writes the existing Admin audit outcome; does not clean up.
# emitted_logs: Admin action requested/failed.
# error_behavior: Legacy action remains HTTP 501 through the dispatcher.
# END_FUNCTION_CONTRACT
@router.post("/cleanup")
async def cleanup_endpoint(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    worktrees: bool = Query(True, description="Clean orphaned git worktrees."),
    state_files: bool = Query(True, description="Remove .grace_state/ entries older than `stale_state_days`."),
    stale_leases: bool = Query(True, description="Release DB leases older than `stale_lease_minutes`."),
    stale_lease_minutes: int = Query(30, ge=1, description="Lease age threshold in minutes."),
    stale_state_days: int = Query(7, ge=1, description="State-file age threshold in days."),
) -> Any:
    return await legacy_admin_action(
        request,
        action="lifecycle_cleanup",
        entity_type="project",
        entity_id=None,
        body=body,
        parameters={
            "worktrees": str(worktrees).lower(),
            "state_files": str(state_files).lower(),
            "stale_leases": str(stale_leases).lower(),
            "stale_lease_minutes": stale_lease_minutes,
            "stale_state_days": stale_state_days,
        },
    )


# START_FUNCTION_CONTRACT
# name: shutdown_endpoint
# purpose: Preserve the audited but unavailable legacy shutdown alias.
# inputs: request and bounded body.
# returns: Audited unavailable response.
# side_effects: Writes the existing Admin audit outcome; does not stop anything.
# emitted_logs: Admin action requested/failed.
# error_behavior: Legacy action remains HTTP 501 through the dispatcher.
# END_FUNCTION_CONTRACT
@router.post("/shutdown")
async def shutdown_endpoint(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    return await legacy_admin_action(
        request,
        action="shutdown",
        entity_type="project",
        entity_id=None,
        body=body,
    )


# START_FUNCTION_CONTRACT
# name: reload_endpoint
# purpose: Route a confirmed watcher reload through the canonical Admin control
#          and audit path.
# inputs: request and bounded body.
# returns: Audited local-control response.
# side_effects: May issue one supervisor reload through the local dispatcher.
# emitted_logs: Admin action requested/completed/failed.
# error_behavior: Typed control failures are translated by the local boundary.
# END_FUNCTION_CONTRACT
@router.post("/reload")
async def reload_endpoint(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    return await legacy_admin_action(
        request,
        action="reload",
        entity_type="project",
        entity_id=None,
        body=body,
    )


# END_BLOCK_MUTATIONS
