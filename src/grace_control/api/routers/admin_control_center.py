# ############################################################################
# AI_HEADER: admin_control_center_router — Jinja2/HTMX multi-project UI
# ROLE: Registers the stable Control Center route surface and keeps historical
#       rendering/service seams while focused owner modules compose page reads.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve dashboard, project/entity deep links, explorers and HTMX
#          fragments through explicit project-aware read services.
# inputs: FastAPI requests with project/entity/query selectors.
# returns: Server-rendered HTML and HTMX partial HTML.
# side_effects: Delegates bounded read-only API calls to Admin Hub services.
# emitted_logs: None; service and transport own structured read logs.
# error_behavior: Unknown projects return 404; partial data remains visible.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes: GET /admin, /admin/projects, /admin/_partial/projects,
#             project shell/explorer/global/partial routes under /admin.
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from grace_control.api.routers.admin_control_center_dashboard import (
    admin_landing_impl as _admin_landing_impl,
)
from grace_control.api.routers.admin_control_center_dashboard import (
    admin_projects_impl as _admin_projects_impl,
)
from grace_control.api.routers.admin_control_center_dashboard import (
    partial_projects_impl as _partial_projects_impl,
)
from grace_control.api.routers.admin_control_center_dashboard import (
    project_entity_impl as _project_entity_impl,
)
from grace_control.api.routers.admin_control_center_global import (
    admin_events_impl as _admin_events_impl,
)
from grace_control.api.routers.admin_control_center_global import (
    admin_logs_impl as _admin_logs_impl,
)
from grace_control.api.routers.admin_control_center_global import (
    admin_search_impl as _admin_search_impl,
)
from grace_control.api.routers.admin_control_center_partials import (
    partial_project_impl as _partial_project_impl,
)
from grace_control.api.routers.admin_control_center_partials import (
    partial_project_query_impl as _partial_project_query_impl,
)
from grace_control.api.routers.admin_control_center_partials import (
    partial_system_impl as _partial_system_impl,
)
from grace_control.api.routers.admin_control_center_project import (
    project_api_impl as _project_api_impl,
)
from grace_control.api.routers.admin_control_center_project import (
    project_events_impl as _project_events_impl,
)
from grace_control.api.routers.admin_control_center_project import (
    project_files_impl as _project_files_impl,
)
from grace_control.api.routers.admin_control_center_project import (
    project_git_impl as _project_git_impl,
)
from grace_control.api.routers.admin_control_center_project import (
    project_logs_impl as _project_logs_impl,
)
from grace_control.api.routers.admin_control_center_project import (
    project_maintenance_impl as _project_maintenance_impl,
)
from grace_control.api.routers.admin_control_center_project import (
    project_packet_impl as _project_packet_impl,
)
from grace_control.api.routers.admin_control_center_project import (
    project_system_impl as _project_system_impl,
)
from grace_control.api.routers.admin_control_center_rendering import (
    cc_query_url as _cc_query_url_impl,
)
from grace_control.api.routers.admin_control_center_rendering import (
    cc_url as _cc_url_impl,
)
from grace_control.api.routers.admin_control_center_rendering import (
    partial_url as _partial_url_impl,
)
from grace_control.api.routers.admin_control_center_rendering import (
    render as _render_impl,
)
from grace_control.api.routers.admin_control_center_rendering import (
    render_fragment as _render_fragment_impl,
)
from grace_control.api.routers.admin_control_center_rendering import (
    render_project_partial as _render_project_partial_impl,
)
from grace_control.api.routers.admin_control_center_rendering import (
    status_icon as _status_icon_impl,
)
from grace_control.api.routers.admin_ui import admin_console
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center import AdminControlCenterService
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.ui.admin_template_filters import register as _register_filters

router = APIRouter()
_log = GraceLogger("admin_control_center_router")
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "ui" / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR / "admin"))
_register_filters(_templates.env)


# Historical private seams retained by facade wrappers.
# START_BLOCK_HELPERS
def _service(request: Request) -> AdminControlCenterService:
    state = request.app.state
    hub = getattr(state, "admin_cross_project_service", None)
    if not isinstance(hub, AdminCrossProjectService):
        raise HTTPException(status_code=503, detail="Admin Hub service is unavailable")
    return AdminControlCenterService(hub)


def _render(request: Request, page: str, model: dict[str, Any]) -> HTMLResponse:
    return _render_impl(request, page, model, templates=_templates, cc_url=_cc_url, status_icon=_status_icon)


def _render_fragment(request: Request, template_name: str, model: dict[str, Any]) -> HTMLResponse:
    return _render_fragment_impl(
        request,
        template_name,
        model,
        templates=_templates,
        cc_url=_cc_url,
        cc_query_url=_cc_query_url,
        status_icon=_status_icon,
    )


def _render_project_partial(request: Request, model: dict[str, Any]) -> HTMLResponse:
    return _render_project_partial_impl(
        request,
        model,
        templates=_templates,
        cc_url=_cc_url,
        status_icon=_status_icon,
    )


def _cc_url(project_key: str | None = None, kind: str = "", entity_id: str = "", **params: Any) -> str:
    return _cc_url_impl(project_key, kind, entity_id, **params)


def _cc_query_url(path: str, **params: Any) -> str:
    return _cc_query_url_impl(path, **params)


def _partial_url(
    project_key: str,
    entity_type: str | None = None, entity_id: str | None = None, tab: str | None = None,
    run_id: str | None = None, stage_id: str | None = None, event: str | None = None,
    component: str | None = None, run_stage: str | None = None, trace_id: str | None = None,
    text: str | None = None, source: str | None = None, tail: int | None = None,
    artifact_path: str | None = None, root: str | None = None, file_path: str | None = None,
    ref: str | None = None, file: str | None = None, git_path: str | None = None,
) -> str:
    return _partial_url_impl(
        project_key, entity_type, entity_id, tab, run_id, stage_id, event, component,
        run_stage, trace_id, text, source, tail, artifact_path, root, file_path, ref, file, git_path,
    )


def _status_icon(status: Any) -> str:
    return _status_icon_impl(status)


def _raise_project_not_found(exc: KeyError) -> None:
    raise HTTPException(status_code=404, detail="project not found") from exc


_templates.env.globals["cc_url"] = lambda project_key, kind="", entity_id="", **params: _cc_url(
    project_key, kind, entity_id, **params
)
_templates.env.globals["cc_query_url"] = _cc_query_url
_templates.env.globals["cc_partial_url"] = _partial_url
_templates.env.globals["cc_status_icon"] = _status_icon


# Explicit callback bridges keep owner modules independent of this facade.
async def _project_route(owner: Callable[..., Any], request: Request, *args: Any, **kwargs: Any) -> HTMLResponse:
    return await owner(
        request, *args, service_fn=_service, render=_render,
        project_not_found=_raise_project_not_found, **kwargs,
    )


async def _project_logs_route(request: Request, *args: Any) -> HTMLResponse:
    return await _project_route(_project_logs_impl, request, *args, render_fragment=_render_fragment)


async def _global_route(owner: Callable[..., Any], request: Request, *args: Any, **kwargs: Any) -> HTMLResponse:
    return await owner(
        request, *args, service_fn=_service, render=_render,
        project_not_found=_raise_project_not_found, **kwargs,
    )


async def _global_logs_route(request: Request, *args: Any) -> HTMLResponse:
    return await _global_route(_admin_logs_impl, request, *args, render_fragment=_render_fragment)


async def _partial_content_route(request: Request, *args: Any) -> HTMLResponse:
    return await _partial_project_impl(
        request, *args, service_fn=_service, render_project_partial=_render_project_partial,
        project_not_found=_raise_project_not_found,
    )


# END_BLOCK_HELPERS


# START_BLOCK_DASHBOARD
# START_FUNCTION_CONTRACT
# name: admin_landing
# purpose: Delegate dashboard rendering with empty-registry fallback.
# inputs: request and dashboard filter.
# returns: HTMLResponse.
# side_effects: Bounded dashboard reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Empty registry uses legacy console.
# END_FUNCTION_CONTRACT
@router.get("/admin", response_class=HTMLResponse)
async def admin_landing(request: Request, filter: str = Query("all")) -> HTMLResponse:
    return await _admin_landing_impl(
        request, filter, service_fn=_service, legacy_console=admin_console, render=_render,
    )


# START_FUNCTION_CONTRACT
# name: admin_projects
# purpose: Delegate the project dashboard alias.
# inputs: request and dashboard filter.
# returns: HTMLResponse.
# side_effects: Bounded dashboard reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Preserves landing fallback.
# END_FUNCTION_CONTRACT
@router.get("/admin/projects", response_class=HTMLResponse)
async def admin_projects(request: Request, filter: str = Query("all")) -> HTMLResponse:
    return await _admin_projects_impl(request, filter, landing=admin_landing)


# START_FUNCTION_CONTRACT
# name: partial_projects
# purpose: Delegate the HTMX project-card grid.
# inputs: request and dashboard filter.
# returns: HTMLResponse.
# side_effects: Bounded dashboard reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Preserves template context.
# END_FUNCTION_CONTRACT
@router.get("/admin/_partial/projects", response_class=HTMLResponse)
async def partial_projects(request: Request, filter: str = Query("all")) -> HTMLResponse:
    return await _partial_projects_impl(
        request, filter, service_fn=_service, templates=_templates,
        cc_url=_cc_url, status_icon=_status_icon,
    )


# START_FUNCTION_CONTRACT
# name: project_overview
# purpose: Delegate the selected project shell.
# inputs: request and project_key.
# returns: HTMLResponse.
# side_effects: Selected-project reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}", response_class=HTMLResponse)
async def project_overview(request: Request, project_key: str) -> HTMLResponse:
    return await _project_route(_project_entity_impl, request, project_key)


# START_FUNCTION_CONTRACT
# name: project_feature
# purpose: Delegate a Feature deep link.
# inputs: request, project_key and feature_id.
# returns: HTMLResponse.
# side_effects: Selected-project reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/feature/{feature_id}", response_class=HTMLResponse)
async def project_feature(request: Request, project_key: str, feature_id: str) -> HTMLResponse:
    return await _project_route(
        _project_entity_impl, request, project_key, entity_type="feature", entity_id=feature_id,
    )


# START_FUNCTION_CONTRACT
# name: project_wave
# purpose: Delegate a Wave deep link.
# inputs: request, project_key and wave_id.
# returns: HTMLResponse.
# side_effects: Selected-project reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/wave/{wave_id}", response_class=HTMLResponse)
async def project_wave(request: Request, project_key: str, wave_id: str) -> HTMLResponse:
    return await _project_route(
        _project_entity_impl, request, project_key, entity_type="wave", entity_id=wave_id,
    )


# END_BLOCK_DASHBOARD


# START_BLOCK_PROJECT_EXPLORER
# START_FUNCTION_CONTRACT
# name: project_packet
# purpose: Delegate packet debugging with all historical selectors.
# inputs: request, project/packet keys and bounded tab/explorer selectors.
# returns: HTMLResponse.
# side_effects: Selected-project detail reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/packet/{packet_id}", response_class=HTMLResponse)
async def project_packet(
    request: Request, project_key: str, packet_id: str,
    tab: str = Query("overview"), run_id: str | None = Query(None), stage_id: str | None = Query(None),
    event: str | None = Query(None), component: str | None = Query(None), run_stage: str | None = Query(None),
    trace_id: str | None = Query(None), text: str | None = Query(None), source: str | None = Query(None),
    tail: int = Query(500, ge=100, le=2000), artifact_path: str | None = Query(None), root: str | None = Query(None),
    path: str = Query(""), ref: str | None = Query(None), file: str | None = Query(None), git_path: str | None = Query(None),
) -> HTMLResponse:
    return await _project_route(
        _project_packet_impl, request, project_key, packet_id, tab, run_id, stage_id, event, component,
        run_stage, trace_id, text, source, tail, artifact_path, root, path, ref, file, git_path,
    )


# START_FUNCTION_CONTRACT
# name: project_system
# purpose: Delegate selected-project System rendering.
# inputs: request and project_key.
# returns: HTMLResponse.
# side_effects: Selected-project reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/system", response_class=HTMLResponse)
async def project_system(request: Request, project_key: str) -> HTMLResponse:
    return await _project_route(_project_system_impl, request, project_key)


# START_FUNCTION_CONTRACT
# name: project_maintenance
# purpose: Delegate selected-project maintenance rendering.
# inputs: request and project_key.
# returns: HTMLResponse.
# side_effects: Maintenance snapshot read.
# emitted_logs: Service-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/maintenance", response_class=HTMLResponse)
async def project_maintenance(request: Request, project_key: str) -> HTMLResponse:
    return await _project_route(_project_maintenance_impl, request, project_key)


# START_FUNCTION_CONTRACT
# name: project_git
# purpose: Delegate selected-project Git explorer rendering.
# inputs: request, project_key, ref and path.
# returns: HTMLResponse.
# side_effects: Selected-project Git reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/git", response_class=HTMLResponse)
async def project_git(
    request: Request, project_key: str, ref: str | None = Query(None), path: str | None = Query(None),
) -> HTMLResponse:
    return await _project_route(_project_git_impl, request, project_key, ref, path)


# START_FUNCTION_CONTRACT
# name: project_files
# purpose: Delegate selected-project Files explorer rendering.
# inputs: request, project_key and root/path/preview/tail selectors.
# returns: HTMLResponse.
# side_effects: Selected-project Files reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/files", response_class=HTMLResponse)
async def project_files(
    request: Request, project_key: str, root: str | None = Query(None), path: str = Query(""),
    preview: str | None = Query(None), tail: int = Query(0, ge=0, le=1000),
) -> HTMLResponse:
    return await _project_route(_project_files_impl, request, project_key, root, path, preview, tail)


# START_FUNCTION_CONTRACT
# name: project_api
# purpose: Delegate selected-project OpenAPI explorer rendering.
# inputs: request, project_key and API path/method/control selectors.
# returns: HTMLResponse.
# side_effects: Service-approved selected-project reads/execution.
# emitted_logs: Service-owned read logs.
# error_behavior: Service gates mutation/arbitrary paths.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/api", response_class=HTMLResponse)
async def project_api(
    request: Request, project_key: str, path: str | None = Query(None), execute: bool = Query(False),
    params: str | None = Query(None), method: str = Query("GET"), control_mode: bool = Query(False),
    body: str | None = Query(None), confirmation: str | None = Query(None),
) -> HTMLResponse:
    return await _project_route(
        _project_api_impl, request, project_key, path, execute, params, method, control_mode, body, confirmation,
    )


# START_FUNCTION_CONTRACT
# name: project_events
# purpose: Delegate selected-project Events rendering.
# inputs: request, project_key, event filters and pagination.
# returns: HTMLResponse.
# side_effects: Selected-project event reads.
# emitted_logs: Hub-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/events", response_class=HTMLResponse)
async def project_events(
    request: Request, project_key: str, entity_id: str | None = Query(None), entity_type: str | None = Query(None),
    event_type: str | None = Query(None), trace_id: str | None = Query(None), since: str | None = Query(None),
    until: str | None = Query(None), text: str | None = Query(None), limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0), cursor: str | None = Query(None),
) -> HTMLResponse:
    return await _project_route(
        _project_events_impl, request, project_key, entity_id, entity_type, event_type, trace_id, since, until,
        text, limit, offset, cursor,
    )


# START_FUNCTION_CONTRACT
# name: project_logs
# purpose: Delegate selected-project Logs rendering and HTMX behavior.
# inputs: request, project_key and bounded log filters.
# returns: HTMLResponse.
# side_effects: Selected-project log reads.
# emitted_logs: Hub-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/logs", response_class=HTMLResponse)
async def project_logs(
    request: Request, project_key: str, contains: str | None = Query(None), level: str | None = Query(None),
    source: str | None = Query(None), worker: str | None = Query(None), packet: str | None = Query(None),
    run: str | None = Query(None), stage: str | None = Query(None), trace_id: str | None = Query(None),
    regex: str | None = Query(None), since: str | None = Query(None), until: str | None = Query(None),
    tail: int = Query(500, ge=100, le=2000), cursor: str | None = Query(None), follow: bool = Query(False),
    wrap: bool = Query(False),
) -> HTMLResponse:
    return await _project_logs_route(
        request, project_key, contains, level, source, worker, packet, run, stage, trace_id, regex, since,
        until, tail, cursor, follow, wrap,
    )


# END_BLOCK_PROJECT_EXPLORER


# START_BLOCK_GLOBAL_EXPLORERS
# START_FUNCTION_CONTRACT
# name: admin_events
# purpose: Delegate cross-project Events rendering.
# inputs: request, project/entity filters and pagination.
# returns: HTMLResponse.
# side_effects: Bounded Hub event reads.
# emitted_logs: Hub-owned read logs.
# error_behavior: Unknown project filters return 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/events", response_class=HTMLResponse)
async def admin_events(
    request: Request, project: list[str] | None = Query(None), entity_id: str | None = Query(None),
    entity_type: str | None = Query(None), event_type: str | None = Query(None), trace_id: str | None = Query(None),
    since: str | None = Query(None), until: str | None = Query(None), text: str | None = Query(None),
    limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0), cursor: str | None = Query(None),
) -> HTMLResponse:
    return await _global_route(
        _admin_events_impl, request, project, entity_id, entity_type, event_type, trace_id, since, until,
        text, limit, offset, cursor,
    )


# START_FUNCTION_CONTRACT
# name: admin_logs
# purpose: Delegate cross-project Logs rendering and HTMX behavior.
# inputs: request, project filters and bounded log filters.
# returns: HTMLResponse.
# side_effects: Bounded Hub log reads.
# emitted_logs: Hub-owned read logs.
# error_behavior: Unknown project filters return 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs(
    request: Request, project: list[str] | None = Query(None), contains: str | None = Query(None),
    level: str | None = Query(None), source: str | None = Query(None), worker: str | None = Query(None),
    packet: str | None = Query(None), run: str | None = Query(None), stage: str | None = Query(None),
    trace_id: str | None = Query(None), regex: str | None = Query(None), since: str | None = Query(None),
    until: str | None = Query(None), tail: int = Query(500, ge=100, le=2000), cursor: str | None = Query(None),
    follow: bool = Query(False), wrap: bool = Query(False),
) -> HTMLResponse:
    return await _global_logs_route(
        request, project, contains, level, source, worker, packet, run, stage, trace_id, regex, since, until,
        tail, cursor, follow, wrap,
    )


# START_FUNCTION_CONTRACT
# name: admin_search
# purpose: Delegate cross-project Search rendering.
# inputs: request, q search text and optional project.
# returns: HTMLResponse.
# side_effects: Bounded Hub search reads.
# emitted_logs: Hub-owned read logs.
# error_behavior: Unknown project filters return 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/search", response_class=HTMLResponse)
async def admin_search(
    request: Request, q: str = Query(""), project: str | None = Query(None),
) -> HTMLResponse:
    return await _global_route(_admin_search_impl, request, q, project)


# END_BLOCK_GLOBAL_EXPLORERS


# START_BLOCK_PARTIALS
# START_FUNCTION_CONTRACT
# name: partial_project
# purpose: Delegate selected project content HTMX polling.
# inputs: request, project key and entity/tab/explorer selectors.
# returns: HTMLResponse.
# side_effects: Selected-project reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/_partial/content", response_class=HTMLResponse)
async def partial_project(
    request: Request, project_key: str, entity_type: str | None = Query(None), entity_id: str | None = Query(None),
    tab: str = Query("overview"), run_id: str | None = Query(None), stage_id: str | None = Query(None),
    event: str | None = Query(None), component: str | None = Query(None), run_stage: str | None = Query(None),
    trace_id: str | None = Query(None), text: str | None = Query(None), source: str | None = Query(None),
    tail: int = Query(500, ge=100, le=2000), artifact_path: str | None = Query(None), root: str | None = Query(None),
    path: str = Query(""), ref: str | None = Query(None), file: str | None = Query(None), git_path: str | None = Query(None),
) -> HTMLResponse:
    return await _partial_content_route(
        request, project_key, entity_type, entity_id, tab, run_id, stage_id, event, component, run_stage,
        trace_id, text, source, tail, artifact_path, root, path, ref, file, git_path,
    )


# START_FUNCTION_CONTRACT
# name: partial_project_query
# purpose: Delegate the legacy query-form project partial.
# inputs: request, required query project_key and selectors.
# returns: HTMLResponse.
# side_effects: Selected-project reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Missing project_key remains 422; unknown key returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/_partial/project", response_class=HTMLResponse)
async def partial_project_query(
    request: Request, project_key: str = Query(...), entity_type: str | None = Query(None), entity_id: str | None = Query(None),
    tab: str = Query("overview"), run_id: str | None = Query(None), stage_id: str | None = Query(None),
    event: str | None = Query(None), component: str | None = Query(None), run_stage: str | None = Query(None),
    trace_id: str | None = Query(None), text: str | None = Query(None), source: str | None = Query(None),
    tail: int = Query(500, ge=100, le=2000), artifact_path: str | None = Query(None), root: str | None = Query(None),
    path: str = Query(""), ref: str | None = Query(None), file: str | None = Query(None), git_path: str | None = Query(None),
) -> HTMLResponse:
    return await _partial_project_query_impl(
        request, project_key, entity_type, entity_id, tab, run_id, stage_id, event, component, run_stage,
        trace_id, text, source, tail, artifact_path, root, path, ref, file, git_path,
        partial_project=partial_project,
    )


# START_FUNCTION_CONTRACT
# name: partial_system
# purpose: Delegate selected-project System HTMX polling.
# inputs: request and project_key.
# returns: HTMLResponse.
# side_effects: Selected-project reads.
# emitted_logs: Service-owned read logs.
# error_behavior: Unknown project returns 404.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/_partial/system", response_class=HTMLResponse)
async def partial_system(request: Request, project_key: str) -> HTMLResponse:
    return await _partial_system_impl(
        request, project_key, service_fn=_service, templates=_templates,
        cc_url=_cc_url, status_icon=_status_icon, project_not_found=_raise_project_not_found,
    )


# END_BLOCK_PARTIALS
