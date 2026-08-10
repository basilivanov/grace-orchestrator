# ############################################################################
# AI_HEADER: admin_control_center_router — Jinja2/HTMX multi-project UI
# ROLE: Binds the Stage 04 project-aware Control Center routes to the Hub read
#       service. It owns no project selection state; every entity URL carries
#       its project key explicitly.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve the project dashboard, project/entity deep links, system view,
#          cross-project Events/Logs/Search pages and HTMX polling fragments.
# inputs: FastAPI requests with explicit project/entity/query selectors.
# returns: Server-rendered HTML and HTMX partial HTML.
# side_effects: Delegates bounded read-only API calls to Admin Hub services.
# emitted_logs: None; service and transport own structured read logs.
# error_behavior: 404 for unknown project keys; partial data stays visible.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /admin
#       - GET /admin/projects
#       - GET /admin/p/{project_key}
#       - GET /admin/p/{project_key}/feature/{feature_id}
#       - GET /admin/p/{project_key}/wave/{wave_id}
#       - GET /admin/p/{project_key}/packet/{packet_id}
#       - GET /admin/p/{project_key}/system
#       - GET /admin/p/{project_key}/git
#       - GET /admin/p/{project_key}/files
#       - GET /admin/p/{project_key}/api
#       - GET /admin/events
#       - GET /admin/logs
#       - GET /admin/search
#       - GET /admin/_partial/projects
#       - GET /admin/_partial/project
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center import AdminControlCenterService
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.ui.admin_template_filters import register as _register_filters

router = APIRouter()
_log = GraceLogger("admin_control_center_router")
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "ui" / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR / "admin"))
_register_filters(_templates.env)


# START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: _service
# purpose: Resolve the immutable app-scoped Hub service for one request.
# inputs: request — current FastAPI request.
# returns: AdminControlCenterService bound to the app's Hub service.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises HTTPException 503 when Hub wiring is unavailable.
# END_FUNCTION_CONTRACT
def _service(request: Request) -> AdminControlCenterService:
    state = request.app.__dict__["state"]
    hub = getattr(state, "admin_cross_project_service", None)
    if not isinstance(hub, AdminCrossProjectService):
        raise HTTPException(status_code=503, detail="Admin Hub service is unavailable")
    return AdminControlCenterService(hub)


# START_FUNCTION_CONTRACT
# name: _render
# purpose: Render the common persistent Control Center shell around one page.
# inputs: request, page name and page-specific view model.
# returns: HTMLResponse.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for valid template models.
# END_FUNCTION_CONTRACT
def _render(request: Request, page: str, model: dict[str, Any]) -> HTMLResponse:
    context = {
        "request": request,
        "page": page,
        "current_project": model.get("current_project") or model.get("project"),
        "projects": model.get("projects", []),
        "cc_url": _cc_url,
        "cc_status_icon": _status_icon,
    }
    context.update(model)
    return _templates.TemplateResponse(request, "control_center.html", context)


# START_FUNCTION_CONTRACT
# name: _render_fragment
# purpose: Render one explorer fragment for bounded HTMX polling without
#          returning the persistent Control Center shell a second time.
# inputs: request — current request; template_name — control partial name;
#         model — page-specific view model.
# returns: HTMLResponse containing the requested explorer fragment.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for valid template models.
# END_FUNCTION_CONTRACT
def _render_fragment(request: Request, template_name: str, model: dict[str, Any]) -> HTMLResponse:
    context = {
        "request": request,
        "cc_url": _cc_url,
        "cc_query_url": _cc_query_url,
        "cc_status_icon": _status_icon,
    }
    context.update(model)
    return _templates.TemplateResponse(request, f"control/_{template_name}.html", context)


# START_FUNCTION_CONTRACT
# name: _render_project_partial
# purpose: Render only the selected project content for HTMX polling while
#          preserving explicit project/entity/tab query state.
# inputs: request and project view model.
# returns: HTMLResponse containing one replaceable project-content section.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for valid template models.
# END_FUNCTION_CONTRACT
def _render_project_partial(request: Request, model: dict[str, Any]) -> HTMLResponse:
    context = {
        "request": request,
        "cc_url": _cc_url,
        "cc_status_icon": _status_icon,
    }
    context.update(model)
    return _templates.TemplateResponse(request, "control/_project_content.html", context)


# START_FUNCTION_CONTRACT
# name: _cc_url
# purpose: Build canonical project-aware URLs with safely quoted entity IDs and
#          explicit query context for tabs, runs and polling.
# inputs: project_key, optional entity kind/id and query parameters.
# returns: URL string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for ordinary string values.
# END_FUNCTION_CONTRACT
def _cc_url(
    project_key: str | None = None,
    kind: str = "",
    entity_id: str = "",
    **params: Any,
) -> str:
    if project_key:
        path = f"/admin/p/{quote(str(project_key), safe='-_.~')}"
        if kind:
            path += f"/{quote(str(kind), safe='-_.~')}"
            if entity_id:
                path += f"/{quote(str(entity_id), safe='-_.~')}"
    else:
        path = "/admin"
    query = [(key, str(value)) for key, value in params.items() if value not in (None, "", False)]
    return f"{path}?{urlencode(query)}" if query else path


# START_FUNCTION_CONTRACT
# name: _cc_query_url
# purpose: Build a bounded continuation or polling URL from an internal
#          explorer path and active query state.
# inputs: path — router-owned relative path; params — scalar query values.
# returns: URL with encoded non-empty query parameters.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for ordinary string/scalar values.
# END_FUNCTION_CONTRACT
def _cc_query_url(path: str, **params: Any) -> str:
    query = [(key, str(value)) for key, value in params.items() if value not in (None, "", False)]
    return f"{path}?{urlencode(query)}" if query else path


# START_FUNCTION_CONTRACT
# name: _partial_url
# purpose: Build an explicit project/entity/tab URL for HTMX polling.
# inputs: project_key, entity type/id and optional tab/run/stage/timeline
#         selectors.
# returns: Absolute project partial URL.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for ordinary string values.
# END_FUNCTION_CONTRACT
def _partial_url(
    project_key: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    tab: str | None = None,
    run_id: str | None = None,
    stage_id: str | None = None,
    event: str | None = None,
    component: str | None = None,
    run_stage: str | None = None,
    trace_id: str | None = None,
    text: str | None = None,
    source: str | None = None,
    tail: int | None = None,
    artifact_path: str | None = None,
    root: str | None = None,
    file_path: str | None = None,
    ref: str | None = None,
    file: str | None = None,
    git_path: str | None = None,
) -> str:
    path = f"/admin/p/{quote(str(project_key), safe='-_.~')}/_partial/content"
    params = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "tab": tab or "overview",
        "run_id": run_id,
        "stage_id": stage_id,
        "event": event,
        "component": component,
        "run_stage": run_stage,
        "trace_id": trace_id,
        "text": text,
        "source": source,
        "tail": tail,
        "artifact_path": artifact_path,
        "root": root,
        "path": file_path,
        "ref": ref,
        "file": file,
        "git_path": git_path,
    }
    return f"{path}?{urlencode([(key, str(value)) for key, value in params.items() if value not in (None, '')])}"


# START_FUNCTION_CONTRACT
# name: _status_icon
# purpose: Return a textual/icon status semantic that is not dependent on color.
# inputs: status string.
# returns: Human-readable status marker.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _status_icon(status: Any) -> str:
    value = str(status or "unknown").casefold()
    return {
        "online": "● ONLINE",
        "running": "▶ RUNNING",
        "degraded": "▲ DEGRADED",
        "offline": "■ OFFLINE",
        "disabled": "○ DISABLED",
        "idle": "○ IDLE",
    }.get(value, f"? {value.upper()}")


_templates.env.globals["cc_url"] = lambda project_key, kind="", entity_id="", **params: _cc_url(
    project_key, kind, entity_id, **params
)
_templates.env.globals["cc_query_url"] = _cc_query_url
_templates.env.globals["cc_partial_url"] = _partial_url
_templates.env.globals["cc_status_icon"] = _status_icon


# START_FUNCTION_CONTRACT
# name: _raise_project_not_found
# purpose: Convert an unknown registry key into the canonical UI 404.
# inputs: KeyError.
# returns: Never; raises HTTPException.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Always raises HTTP 404.
# END_FUNCTION_CONTRACT
def _raise_project_not_found(exc: KeyError) -> None:
    raise HTTPException(status_code=404, detail="project not found") from exc


# END_BLOCK_HELPERS


# START_BLOCK_DASHBOARD
# START_FUNCTION_CONTRACT
# name: admin_landing
# purpose: Render the multi-project dashboard at the canonical Admin landing
#          URL, retaining legacy single-project behavior when no registry is
#          configured.
# inputs: request and deterministic dashboard filter.
# returns: HTMLResponse.
# side_effects: Hub overview reads when projects are configured.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Falls back to the accepted legacy console for an empty registry.
# END_FUNCTION_CONTRACT
@router.get("/admin", response_class=HTMLResponse)
async def admin_landing(
    request: Request,
    filter: str = Query("all"),
) -> HTMLResponse:
    service = _service(request)
    if not service.contexts():
        from grace_control.api.routers.admin_ui import admin_console

        return admin_console(request=request, filter=filter)
    model = await service.dashboard(filter)
    return _render(request, "dashboard", model)


# START_FUNCTION_CONTRACT
# name: admin_projects
# purpose: Render the explicit project dashboard alias.
# inputs: request and deterministic dashboard filter.
# returns: HTMLResponse.
# side_effects: Hub overview reads for configured projects.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Same fallback and isolation semantics as admin_landing.
# END_FUNCTION_CONTRACT
@router.get("/admin/projects", response_class=HTMLResponse)
async def admin_projects(
    request: Request,
    filter: str = Query("all"),
) -> HTMLResponse:
    return await admin_landing(request=request, filter=filter)


# START_FUNCTION_CONTRACT
# name: partial_projects
# purpose: Poll only the project-card grid through HTMX while retaining the
#          current dashboard filter in the request URL.
# inputs: request and dashboard filter.
# returns: HTMLResponse project-card partial.
# side_effects: Hub overview reads for configured projects.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Returns an explicit empty partial for empty registry mode.
# END_FUNCTION_CONTRACT
@router.get("/admin/_partial/projects", response_class=HTMLResponse)
async def partial_projects(
    request: Request,
    filter: str = Query("all"),
) -> HTMLResponse:
    service = _service(request)
    model = await service.dashboard(filter)
    return _templates.TemplateResponse(request, "control/_projects.html", {
        "request": request,
        **model,
        "cc_url": _cc_url,
        "cc_status_icon": _status_icon,
    })


# END_BLOCK_DASHBOARD


# START_BLOCK_PROJECT
# START_FUNCTION_CONTRACT
# name: project_overview
# purpose: Render a selected project's Feature/Wave/Packet tree and current
#          entity summary from that project's API only.
# inputs: request and project_key path key.
# returns: HTMLResponse.
# side_effects: Selected-project API reads only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: 404 for unknown project keys.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}", response_class=HTMLResponse)
async def project_overview(request: Request, project_key: str) -> HTMLResponse:
    try:
        model = await _service(request).project_page(project_key)
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render(request, "project", model)


# START_FUNCTION_CONTRACT
# name: project_feature
# purpose: Render a project-scoped Feature deep link.
# inputs: request and explicit project_key/feature_id path keys.
# returns: HTMLResponse.
# side_effects: Reads selected project API only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: 404 for unknown project; missing feature is rendered in-page.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/feature/{feature_id}", response_class=HTMLResponse)
async def project_feature(request: Request, project_key: str, feature_id: str) -> HTMLResponse:
    try:
        model = await _service(request).project_page(
            project_key,
            entity_type="feature",
            entity_id=feature_id,
        )
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render(request, "project", model)


# START_FUNCTION_CONTRACT
# name: project_wave
# purpose: Render a project-scoped Wave deep link without requiring a hidden
#          feature selection or global browser state.
# inputs: request and explicit project_key/wave_id path keys.
# returns: HTMLResponse.
# side_effects: Reads selected project API only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: 404 for unknown project; missing wave is rendered in-page.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/wave/{wave_id}", response_class=HTMLResponse)
async def project_wave(request: Request, project_key: str, wave_id: str) -> HTMLResponse:
    try:
        model = await _service(request).project_page(
            project_key,
            entity_type="wave",
            entity_id=wave_id,
        )
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render(request, "project", model)


# START_FUNCTION_CONTRACT
# name: project_packet
# purpose: Render the primary project-scoped Packet debugging page and retain
#          tab/run/stage selections in canonical query parameters.
# inputs: request, project_key/packet_id and tab/run/stage/timeline selectors.
# returns: HTMLResponse.
# side_effects: Reads selected project Admin detail APIs only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: 404 for unknown project; unavailable packet data is explicit.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/packet/{packet_id}", response_class=HTMLResponse)
async def project_packet(
    request: Request,
    project_key: str,
    packet_id: str,
    tab: str = Query("overview"),
    run_id: str | None = Query(None),
    stage_id: str | None = Query(None),
    event: str | None = Query(None),
    component: str | None = Query(None),
    run_stage: str | None = Query(None),
    trace_id: str | None = Query(None),
    text: str | None = Query(None),
    source: str | None = Query(None),
    tail: int = Query(500, ge=100, le=2000),
    artifact_path: str | None = Query(None),
    root: str | None = Query(None),
    path: str = Query(""),
    ref: str | None = Query(None),
    file: str | None = Query(None),
    git_path: str | None = Query(None),
) -> HTMLResponse:
    try:
        model = await _service(request).project_page(
            project_key,
            entity_type="packet",
            entity_id=packet_id,
            tab=tab,
            run_id=run_id,
            stage_id=stage_id,
            event=event,
            component=component,
            run_stage=run_stage,
            trace_id=trace_id,
            text=text,
            source=source,
            log_tail=tail,
            artifact_path=artifact_path or file,
            file_root=root,
            file_path=path,
            git_ref=ref,
            git_path=git_path or file,
        )
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render(request, "project", model)


# START_FUNCTION_CONTRACT
# name: project_system
# purpose: Render a selected project's health, runtime, worker, lease, wait
#          and masked configuration view.
# inputs: request and explicit project_key.
# returns: HTMLResponse.
# side_effects: Selected-project API reads only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: 404 for unknown project keys.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/system", response_class=HTMLResponse)
async def project_system(request: Request, project_key: str) -> HTMLResponse:
    try:
        model = await _service(request).system_page(project_key)
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render(request, "system", model)


# START_FUNCTION_CONTRACT
# name: project_git
# purpose: Render the selected project's bounded repository, worktree and diff
#          explorer using only Stage 02 read APIs.
# inputs: request, project_key and optional validated ref/path selectors.
# returns: HTMLResponse project Git explorer.
# side_effects: Selected-project Git read API calls only; no commands from the
#                browser are accepted.
# emitted_logs: Service-owned project read logs.
# error_behavior: Unknown projects return 404; typed Git errors remain visible.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/git", response_class=HTMLResponse)
async def project_git(
    request: Request,
    project_key: str,
    ref: str | None = Query(None),
    path: str | None = Query(None),
) -> HTMLResponse:
    try:
        model = await _service(request).git_page(project_key, ref=ref, path=path)
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render(request, "git", model)


# START_FUNCTION_CONTRACT
# name: project_files
# purpose: Render the selected project's advertised named-root Files explorer.
# inputs: request, project_key and relative root/path/preview selectors.
# returns: HTMLResponse bounded Files explorer.
# side_effects: Selected-project Stage 02 filesystem reads only.
# emitted_logs: Service-owned project read logs.
# error_behavior: Unknown projects return 404; typed filesystem errors remain
#                 in the page model without server-side path disclosure.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/files", response_class=HTMLResponse)
async def project_files(
    request: Request,
    project_key: str,
    root: str | None = Query(None),
    path: str = Query(""),
    preview: str | None = Query(None),
    tail: int = Query(0, ge=0, le=1000),
) -> HTMLResponse:
    try:
        model = await _service(request).files_page(
            project_key,
            root=root,
            path=path,
            preview_path=preview,
            tail=tail,
        )
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render(request, "files", model)


# START_FUNCTION_CONTRACT
# name: project_api
# purpose: Render dynamic OpenAPI documentation and optional exact discovered
#          GET execution for one selected project.
# inputs: request, project_key, exact OpenAPI path, execute flag and bounded
#          JSON query parameters.
# returns: HTMLResponse API explorer.
# side_effects: Reads selected project /openapi.json and, only for discovered
#               GETs, one selected project API endpoint.
# emitted_logs: Service-owned project read logs.
# error_behavior: Mutation/arbitrary path execution is disabled in the model.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/api", response_class=HTMLResponse)
async def project_api(
    request: Request,
    project_key: str,
    path: str | None = Query(None),
    execute: bool = Query(False),
    params: str | None = Query(None),
) -> HTMLResponse:
    try:
        model = await _service(request).api_page(
            project_key,
            path=path,
            execute=execute,
            params_json=params,
        )
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render(request, "api", model)


# START_FUNCTION_CONTRACT
# name: project_events
# purpose: Render selected-project Events using the canonical Hub event query.
# inputs: request and project_key; optional entity/event filters.
# returns: HTMLResponse.
# side_effects: Selected-project event API read through Hub service.
# emitted_logs: Hub-owned event read logs.
# error_behavior: 404 for unknown project; partial event data remains visible.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/events", response_class=HTMLResponse)
async def project_events(
    request: Request,
    project_key: str,
    entity_id: str | None = Query(None),
    entity_type: str | None = Query(None),
    event_type: str | None = Query(None),
    trace_id: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    text: str | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(None),
) -> HTMLResponse:
    try:
        model = await _service(request).events_page(
            project_key,
            entity_id=entity_id,
            entity_type=entity_type,
            event_type=event_type,
            trace_id=trace_id,
            since=since,
            until=until,
            text=text,
            limit=limit,
            offset=offset,
            cursor=cursor,
        )
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render(request, "events", model)


# START_FUNCTION_CONTRACT
# name: project_logs
# purpose: Render selected-project bounded Logs data.
# inputs: request and project_key; optional contains/level filters.
# returns: HTMLResponse.
# side_effects: Selected-project log API read through Hub service.
# emitted_logs: Hub-owned log read logs.
# error_behavior: 404 for unknown project; partial data remains visible.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/logs", response_class=HTMLResponse)
async def project_logs(
    request: Request,
    project_key: str,
    contains: str | None = Query(None),
    level: str | None = Query(None),
    source: str | None = Query(None),
    worker: str | None = Query(None),
    packet: str | None = Query(None),
    run: str | None = Query(None),
    stage: str | None = Query(None),
    trace_id: str | None = Query(None),
    regex: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    tail: int = Query(500, ge=100, le=2000),
    cursor: str | None = Query(None),
    follow: bool = Query(False),
    wrap: bool = Query(False),
) -> HTMLResponse:
    try:
        model = await _service(request).logs_page(
            project_key,
            source=source,
            worker=worker,
            packet=packet,
            run=run,
            stage=stage,
            contains=contains,
            level=level,
            trace_id=trace_id,
            regex=regex,
            since=since,
            until=until,
            tail=tail,
            cursor=cursor,
            follow=follow,
            wrap=wrap,
        )
    except KeyError as exc:
        _raise_project_not_found(exc)
    if request.headers.get("HX-Request", "").casefold() == "true":
        return _render_fragment(request, "logs", model)
    return _render(request, "logs", model)


# END_BLOCK_PROJECT


# START_BLOCK_GLOBAL_EXPLORERS
# START_FUNCTION_CONTRACT
# name: admin_events
# purpose: Render the cross-project Events page with optional one-project
#          selector and canonical full-payload event rows.
# inputs: request and optional project/entity/event filters.
# returns: HTMLResponse.
# side_effects: Bounded Hub event reads.
# emitted_logs: Hub-owned event read logs.
# error_behavior: 404 for unknown project; partial results remain visible.
# END_FUNCTION_CONTRACT
@router.get("/admin/events", response_class=HTMLResponse)
async def admin_events(
    request: Request,
    project: list[str] | None = Query(None),
    entity_id: str | None = Query(None),
    entity_type: str | None = Query(None),
    event_type: str | None = Query(None),
    trace_id: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    text: str | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(None),
) -> HTMLResponse:
    try:
        model = await _service(request).events_page(
            project,
            entity_id=entity_id,
            entity_type=entity_type,
            event_type=event_type,
            trace_id=trace_id,
            since=since,
            until=until,
            text=text,
            limit=limit,
            offset=offset,
            cursor=cursor,
        )
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render(request, "events", model)


# START_FUNCTION_CONTRACT
# name: admin_logs
# purpose: Render the cross-project Logs page with explicit project filters.
# inputs: request and optional project/contains/level filters.
# returns: HTMLResponse.
# side_effects: Bounded Hub log reads.
# emitted_logs: Hub-owned log read logs.
# error_behavior: 404 for unknown project; partial results remain visible.
# END_FUNCTION_CONTRACT
@router.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs(
    request: Request,
    project: list[str] | None = Query(None),
    contains: str | None = Query(None),
    level: str | None = Query(None),
    source: str | None = Query(None),
    worker: str | None = Query(None),
    packet: str | None = Query(None),
    run: str | None = Query(None),
    stage: str | None = Query(None),
    trace_id: str | None = Query(None),
    regex: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    tail: int = Query(500, ge=100, le=2000),
    cursor: str | None = Query(None),
    follow: bool = Query(False),
    wrap: bool = Query(False),
) -> HTMLResponse:
    try:
        model = await _service(request).logs_page(
            project,
            source=source,
            worker=worker,
            packet=packet,
            run=run,
            stage=stage,
            contains=contains,
            level=level,
            trace_id=trace_id,
            regex=regex,
            since=since,
            until=until,
            tail=tail,
            cursor=cursor,
            follow=follow,
            wrap=wrap,
        )
    except KeyError as exc:
        _raise_project_not_found(exc)
    if request.headers.get("HX-Request", "").casefold() == "true":
        return _render_fragment(request, "logs", model)
    return _render(request, "logs", model)


# START_FUNCTION_CONTRACT
# name: admin_search
# purpose: Render cross-project canonical search results and project-aware
#          entity links.
# inputs: request, q search text and optional project selector.
# returns: HTMLResponse.
# side_effects: Bounded Hub search reads.
# emitted_logs: Hub-owned search read logs.
# error_behavior: 404 for unknown project; isolated errors remain visible.
# END_FUNCTION_CONTRACT
@router.get("/admin/search", response_class=HTMLResponse)
async def admin_search(
    request: Request,
    q: str = Query(""),
    project: str | None = Query(None),
) -> HTMLResponse:
    try:
        model = await _service(request).search_page(q, project)
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render(request, "search", model)


# END_BLOCK_GLOBAL_EXPLORERS


# START_BLOCK_PARTIALS
# START_FUNCTION_CONTRACT
# name: partial_project
# purpose: Poll and replace only selected project content while preserving
#          project/entity/tab values supplied in the request.
# inputs: request, explicit project_key and optional entity/tab/run/stage/timeline.
# returns: HTMLResponse project content partial.
# side_effects: Selected-project API reads only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: 404 for unknown project.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/_partial/content", response_class=HTMLResponse)
async def partial_project(
    request: Request,
    project_key: str,
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
    tab: str = Query("overview"),
    run_id: str | None = Query(None),
    stage_id: str | None = Query(None),
    event: str | None = Query(None),
    component: str | None = Query(None),
    run_stage: str | None = Query(None),
    trace_id: str | None = Query(None),
    text: str | None = Query(None),
    source: str | None = Query(None),
    tail: int = Query(500, ge=100, le=2000),
    artifact_path: str | None = Query(None),
    root: str | None = Query(None),
    path: str = Query(""),
    ref: str | None = Query(None),
    file: str | None = Query(None),
    git_path: str | None = Query(None),
) -> HTMLResponse:
    try:
        model = await _service(request).project_page(
            project_key,
            entity_type=entity_type,
            entity_id=entity_id,
            tab=tab,
            run_id=run_id,
            stage_id=stage_id,
            event=event,
            component=component,
            run_stage=run_stage,
            trace_id=trace_id,
            text=text,
            source=source,
            log_tail=tail,
            artifact_path=artifact_path or file,
            file_root=root,
            file_path=path,
            git_ref=ref,
            git_path=git_path or file,
        )
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _render_project_partial(request, model)


# START_FUNCTION_CONTRACT
# name: partial_project_query
# purpose: Backward-compatible HTMX partial accepting project_key as an
#          explicit query parameter for shell integrations.
# inputs: request, project_key query and entity/tab context.
# returns: HTMLResponse project content partial.
# side_effects: Selected-project API reads only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: 422 when project_key is omitted; 404 for unknown project.
# END_FUNCTION_CONTRACT
@router.get("/admin/_partial/project", response_class=HTMLResponse)
async def partial_project_query(
    request: Request,
    project_key: str = Query(...),
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
    tab: str = Query("overview"),
    run_id: str | None = Query(None),
    stage_id: str | None = Query(None),
    event: str | None = Query(None),
    component: str | None = Query(None),
    run_stage: str | None = Query(None),
    trace_id: str | None = Query(None),
    text: str | None = Query(None),
    source: str | None = Query(None),
    tail: int = Query(500, ge=100, le=2000),
    artifact_path: str | None = Query(None),
    root: str | None = Query(None),
    path: str = Query(""),
    ref: str | None = Query(None),
    file: str | None = Query(None),
    git_path: str | None = Query(None),
) -> HTMLResponse:
    return await partial_project(
        request=request,
        project_key=project_key,
        entity_type=entity_type,
        entity_id=entity_id,
        tab=tab,
        run_id=run_id,
        stage_id=stage_id,
        event=event,
        component=component,
        run_stage=run_stage,
        trace_id=trace_id,
        text=text,
        source=source,
        tail=tail,
        artifact_path=artifact_path,
        root=root,
        path=path,
        ref=ref,
        file=file,
        git_path=git_path,
    )


# START_FUNCTION_CONTRACT
# name: partial_system
# purpose: Poll selected-project System data without replacing the full shell.
# inputs: request and explicit project_key.
# returns: HTMLResponse system partial.
# side_effects: Selected-project health/worker/diagnostics reads only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: 404 for unknown project.
# END_FUNCTION_CONTRACT
@router.get("/admin/p/{project_key}/_partial/system", response_class=HTMLResponse)
async def partial_system(request: Request, project_key: str) -> HTMLResponse:
    try:
        model = await _service(request).system_page(project_key)
    except KeyError as exc:
        _raise_project_not_found(exc)
    return _templates.TemplateResponse(request, "control/_system.html", {
        "request": request,
        **model,
        "cc_url": _cc_url,
        "cc_status_icon": _status_icon,
    })


# END_BLOCK_PARTIALS
