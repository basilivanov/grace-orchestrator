# ############################################################################
# AI_HEADER: admin_hub_router — central multi-project health JSON surface
# ROLE: Exposes the Admin Hub namespace and delegates every project lookup or
#       fan-out to AdminProjectService. It never reads project-local DB/files.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve Stage 01 project/health endpoints and Stage 03 cross-project
#          observability JSON endpoints without changing single-project APIs.
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
#       - GET /api/admin-hub/overview
#       - GET /api/admin-hub/events
#       - GET /api/admin-hub/logs
#       - GET /api/admin-hub/search
#       - GET /api/admin-hub/diagnostics
#       - GET /api/admin-hub/projects/{project_key}/diagnostics
#       - GET /api/admin-hub/attention
# END_MODULE_MAP

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
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


def _cross_service(request: Request) -> AdminCrossProjectService:
    app_state = request.app.__dict__["state"]
    service = getattr(app_state, "admin_cross_project_service", None)
    if not isinstance(service, AdminCrossProjectService):
        raise HTTPException(status_code=503, detail="Admin Hub cross-project service is unavailable")
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


# START_BLOCK_CROSS_PROJECT
# START_FUNCTION_CONTRACT
# name: overview
# purpose: Return cross-project cards, aggregate counts, coverage and attention.
# inputs: request and optional repeated project selectors.
# returns: Stage 03 overview JSON DTO.
# side_effects: Service-owned bounded concurrent project API fan-out.
# emitted_logs: Service-level fan-out logs.
# error_behavior: 400 for invalid selection; project failures stay in JSON.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/overview")
async def overview(
    request: Request,
    project: list[str] | None = Query(None),
) -> dict:
    try:
        return await _cross_service(request).get_projects_overview(project)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


# START_FUNCTION_CONTRACT
# name: events
# purpose: Return a deterministic bounded global event page with full payloads.
# inputs: Canonical event filters, project selection, limit/offset/cursor.
# returns: Stage 03 normalized events DTO.
# side_effects: Service-owned concurrent project event requests.
# emitted_logs: Service-level fan-out logs.
# error_behavior: 400 for invalid cursor/offset; project errors are isolated.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/events")
async def events(
    request: Request,
    project: list[str] | None = Query(None),
    entity_id: str | None = Query(None),
    entity_type: str | None = Query(None),
    event_type: str | None = Query(None),
    trace_id: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(None),
) -> dict:
    try:
        return await _cross_service(request).query_events(
            project=project,
            entity_id=entity_id,
            entity_type=entity_type,
            event_type=event_type,
            trace_id=trace_id,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
            cursor=cursor,
        )
    except (KeyError, ValueError) as exc:
        status = 404 if isinstance(exc, KeyError) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# START_FUNCTION_CONTRACT
# name: logs
# purpose: Return normalized cross-project bounded log rows.
# inputs: Project/source/entity/time/text filters, tail and cursor.
# returns: Stage 03 normalized logs DTO.
# side_effects: Service-owned concurrent project-local log API requests.
# emitted_logs: Service-level fan-out logs.
# error_behavior: 400 for invalid regex/cursor; project errors are isolated.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/logs")
async def logs(
    request: Request,
    project: list[str] | None = Query(None),
    source: str | None = Query(None),
    worker: str | None = Query(None),
    packet: str | None = Query(None),
    run: str | None = Query(None),
    stage: str | None = Query(None),
    level: str | None = Query(None),
    trace_id: str | None = Query(None),
    contains: str | None = Query(None),
    regex: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    tail: int = Query(200, ge=1, le=500),
    cursor: str | None = Query(None),
) -> dict:
    try:
        return await _cross_service(request).query_logs(
            project=project,
            source=source,
            worker=worker,
            packet=packet,
            run=run,
            stage=stage,
            level=level,
            trace_id=trace_id,
            contains=contains,
            regex=regex,
            since=since,
            until=until,
            tail=tail,
            cursor=cursor,
        )
    except (KeyError, ValueError) as exc:
        status = 404 if isinstance(exc, KeyError) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# START_FUNCTION_CONTRACT
# name: search
# purpose: Return project-aware normalized canonical search results.
# inputs: q, optional project selectors and bounded limit.
# returns: Stage 03 search result DTO with Hub target URLs.
# side_effects: Service-owned concurrent project-local Admin search requests.
# emitted_logs: Service-level fan-out logs.
# error_behavior: 404 for unknown project; project failures remain in errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/search")
async def search(
    request: Request,
    q: str = Query(""),
    project: list[str] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    try:
        return await _cross_service(request).search(q, project=project, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


# START_FUNCTION_CONTRACT
# name: diagnostics
# purpose: Return global or explicitly selected project diagnostics snapshots.
# inputs: request and optional one-project selector.
# returns: Stage 03 diagnostics/aggregate DTO.
# side_effects: Service-owned concurrent project diagnostics requests.
# emitted_logs: Service-level fan-out logs.
# error_behavior: 404 for unknown project; failures remain in JSON.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/diagnostics")
async def diagnostics(
    request: Request,
    project: str | None = Query(None),
) -> dict:
    try:
        return await _cross_service(request).get_diagnostics(project)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


# START_FUNCTION_CONTRACT
# name: project_diagnostics
# purpose: Return one immutable project's complete diagnostic snapshot.
# inputs: request and explicit project_key.
# returns: Stage 03 selected-project diagnostics DTO.
# side_effects: One project-local diagnostics API request.
# emitted_logs: Service-level fan-out logs.
# error_behavior: 404 for unknown project; remote failures remain in JSON.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/projects/{project_key}/diagnostics")
async def project_diagnostics(request: Request, project_key: str) -> dict:
    try:
        return await _cross_service(request).get_diagnostics(project_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


# START_FUNCTION_CONTRACT
# name: attention
# purpose: Return normalized read-only operator attention items.
# inputs: request and optional repeated project selectors.
# returns: Stage 03 attention DTO.
# side_effects: Service-owned bounded project API reads.
# emitted_logs: Service-level fan-out logs.
# error_behavior: 404 for unknown project; project failures remain in JSON.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/attention")
async def attention(
    request: Request,
    project: list[str] | None = Query(None),
) -> dict:
    try:
        return await _cross_service(request).get_attention(project)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


# END_BLOCK_CROSS_PROJECT
