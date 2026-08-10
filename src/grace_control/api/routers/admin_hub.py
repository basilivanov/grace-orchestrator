# ############################################################################
# AI_HEADER: admin_hub_router — central multi-project health JSON surface
# ROLE: Exposes the Admin Hub namespace and delegates every project lookup or
#       fan-out to AdminProjectService. It never reads project-local DB/files.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve the Stage 01 Admin Hub project and health endpoints without
#          changing existing single-project /admin contracts.
# inputs: HTTP request and validated project_key path parameter.
# returns: JSON project, health and aggregate Hub DTOs.
# side_effects: Delegates bounded project-local API reads to the service layer.
# emitted_logs: None; service owns fan-out logs.
# error_behavior: 404 for an unknown project key; remote failures are per-
#                 project JSON results rather than router exceptions.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /api/admin-hub/projects
#       - GET /api/admin-hub/projects/{project_key}
#       - GET /api/admin-hub/projects/{project_key}/health
#       - GET /api/admin-hub/health
# END_MODULE_MAP

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_project_service import AdminProjectService

router = APIRouter()
_log = GraceLogger("admin_hub_router")


# START_BLOCK_PROJECTS
def _service(request: Request) -> AdminProjectService:
    app_state = request.app.__dict__["state"]
    service = getattr(app_state, "admin_project_service", None)
    if not isinstance(service, AdminProjectService):
        raise HTTPException(status_code=503, detail="Admin Hub project service is unavailable")
    return service


# START_FUNCTION_CONTRACT
# name: list_projects
# purpose: List configured projects with isolated default health results.
# inputs: request — current FastAPI request carrying the Hub service.
# returns: JSON project list DTO.
# side_effects: Performs bounded concurrent health fan-out for enabled projects.
# emitted_logs: Service-level fan-out logs.
# error_behavior: Per-project transport failures remain in the response.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/projects")
async def list_projects(request: Request) -> dict:
    return await _service(request).list_projects()


# START_FUNCTION_CONTRACT
# name: project_detail
# purpose: Return one configured project and its current isolated health.
# inputs: request — current request; project_key — safe registry key.
# returns: JSON project DTO.
# side_effects: Queries only the selected enabled project API.
# emitted_logs: Service-level project error logs.
# error_behavior: 404 when project_key is not configured.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/projects/{project_key}")
async def project_detail(request: Request, project_key: str) -> dict:
    service = _service(request)
    try:
        return await service.get_project_details(project_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


# START_FUNCTION_CONTRACT
# name: project_health
# purpose: Return one project's normalized health and registry/runtime identity.
# inputs: request — current request; project_key — safe registry key.
# returns: JSON project health DTO.
# side_effects: Queries only the selected enabled project API.
# emitted_logs: Service-level project error logs.
# error_behavior: 404 when project_key is not configured.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/projects/{project_key}/health")
async def project_health(request: Request, project_key: str) -> dict:
    service = _service(request)
    try:
        return await service.get_project_health(project_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


# END_BLOCK_PROJECTS


# START_BLOCK_HEALTH
# START_FUNCTION_CONTRACT
# name: hub_health
# purpose: Return aggregate Hub status and all per-project health results.
# inputs: request — current FastAPI request carrying the Hub service.
# returns: JSON aggregate health DTO.
# side_effects: Performs bounded concurrent health fan-out.
# emitted_logs: Service-level fan-out logs.
# error_behavior: Isolates project failures in the returned health list.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/health")
async def hub_health(request: Request) -> dict:
    return await _service(request).get_hub_health()


# END_BLOCK_HEALTH
