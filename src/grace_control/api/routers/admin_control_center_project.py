# ############################################################################
# AI_HEADER: admin_control_center_project — project explorer route owner
# ROLE: Maps packet, system, maintenance, Git, Files, API, Events and Logs
#       route inputs to the accepted selected-project Control Center service.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Compose project-scoped explorer pages without duplicating service
#          DTO assembly, filesystem/Git safety or project isolation policy.
# inputs: Explicit project/entity/query selectors and facade callbacks.
# returns: HTMLResponse explorer pages or HTMX log fragments.
# side_effects: Bounded selected-project read calls only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Unknown projects use the supplied canonical UI 404 callback;
#                 typed service errors remain represented by page models.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: project_packet_impl
#   - function: project_system_impl
#   - function: project_maintenance_impl
#   - function: project_git_impl
#   - function: project_files_impl
#   - function: project_api_impl
#   - function: project_events_impl
#   - function: project_logs_impl
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request
from fastapi.responses import HTMLResponse

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center import AdminControlCenterService

_log = GraceLogger("admin_control_center_project")


# START_BLOCK_PROJECT_EXPLORER
# START_FUNCTION_CONTRACT
# name: project_packet_impl
# purpose: Render the selected packet debugging page with all historical tab,
#          run, stage, timeline, log, artifact, Files and Git selectors.
# inputs: request, project/packet keys, bounded explorer selectors and callbacks.
# returns: HTMLResponse.
# side_effects: Selected-project Admin detail reads only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Unknown project uses the canonical 404 callback.
# END_FUNCTION_CONTRACT
async def project_packet_impl(
    request: Request,
    project_key: str,
    packet_id: str,
    tab: str,
    run_id: str | None,
    stage_id: str | None,
    event: str | None,
    component: str | None,
    run_stage: str | None,
    trace_id: str | None,
    text: str | None,
    source: str | None,
    tail: int,
    artifact_path: str | None,
    root: str | None,
    path: str,
    ref: str | None,
    file: str | None,
    git_path: str | None,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).project_page(
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
        project_not_found(exc)
    return render(request, "project", model)


# START_FUNCTION_CONTRACT
# name: project_system_impl
# purpose: Render selected-project health, runtime, worker, lease, wait and
#          masked configuration data.
# inputs: request, project key, service/render callbacks and 404 callback.
# returns: HTMLResponse.
# side_effects: Selected-project API reads only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Unknown project uses the canonical 404 callback.
# END_FUNCTION_CONTRACT
async def project_system_impl(
    request: Request,
    project_key: str,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).system_page(project_key)
    except KeyError as exc:
        project_not_found(exc)
    return render(request, "system", model)


# START_FUNCTION_CONTRACT
# name: project_maintenance_impl
# purpose: Render the selected project's bounded maintenance snapshot view.
# inputs: request, project key, service/render callbacks and 404 callback.
# returns: HTMLResponse.
# side_effects: Selected-project maintenance snapshot read only.
# emitted_logs: Service-owned project read logs.
# error_behavior: Unknown project uses the canonical 404 callback.
# END_FUNCTION_CONTRACT
async def project_maintenance_impl(
    request: Request,
    project_key: str,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).maintenance_page(project_key)
    except KeyError as exc:
        project_not_found(exc)
    return render(request, "maintenance", model)


# START_FUNCTION_CONTRACT
# name: project_git_impl
# purpose: Render the selected project's bounded repository/worktree/diff view.
# inputs: request, project key, optional ref/path and facade callbacks.
# returns: HTMLResponse.
# side_effects: Selected-project Git read API calls only.
# emitted_logs: Service-owned project read logs.
# error_behavior: Unknown projects use 404; typed Git errors remain visible.
# END_FUNCTION_CONTRACT
async def project_git_impl(
    request: Request,
    project_key: str,
    ref: str | None,
    path: str | None,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).git_page(project_key, ref=ref, path=path)
    except KeyError as exc:
        project_not_found(exc)
    return render(request, "git", model)


# START_FUNCTION_CONTRACT
# name: project_files_impl
# purpose: Render the selected project's named-root Files explorer.
# inputs: request, project key, root/path/preview/tail selectors and callbacks.
# returns: HTMLResponse.
# side_effects: Selected-project filesystem reads only.
# emitted_logs: Service-owned project read logs.
# error_behavior: Unknown projects use 404; typed filesystem errors stay in the model.
# END_FUNCTION_CONTRACT
async def project_files_impl(
    request: Request,
    project_key: str,
    root: str | None,
    path: str,
    preview: str | None,
    tail: int,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).files_page(
            project_key,
            root=root,
            path=path,
            preview_path=preview,
            tail=tail,
        )
    except KeyError as exc:
        project_not_found(exc)
    return render(request, "files", model)


# START_FUNCTION_CONTRACT
# name: project_api_impl
# purpose: Render dynamic OpenAPI documentation and optional exact discovered
#          GET execution for one selected project.
# inputs: request, project key, path/method/execute/control/query/body values.
# returns: HTMLResponse API explorer.
# side_effects: Selected project OpenAPI read and service-approved GET only.
# emitted_logs: Service-owned project read logs.
# error_behavior: Mutation/arbitrary path execution remains disabled by service.
# END_FUNCTION_CONTRACT
async def project_api_impl(
    request: Request,
    project_key: str,
    path: str | None,
    execute: bool,
    params: str | None,
    method: str,
    control_mode: bool,
    body: str | None,
    confirmation: str | None,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).api_page(
            project_key,
            path=path,
            execute=execute,
            params_json=params,
            method=method,
            control_mode=control_mode,
            body_json=body,
            confirmation_json=confirmation,
            actor=request.headers.get("x-grace-actor", "operator"),
        )
    except KeyError as exc:
        project_not_found(exc)
    return render(request, "api", model)


# START_FUNCTION_CONTRACT
# name: project_events_impl
# purpose: Render selected-project Events with the canonical Hub event query.
# inputs: request, project key, event filters and pagination selectors.
# returns: HTMLResponse.
# side_effects: Selected-project event API read through Hub service.
# emitted_logs: Hub-owned event read logs.
# error_behavior: Unknown projects use 404; partial event data remains visible.
# END_FUNCTION_CONTRACT
async def project_events_impl(
    request: Request,
    project_key: str,
    entity_id: str | None,
    entity_type: str | None,
    event_type: str | None,
    trace_id: str | None,
    since: str | None,
    until: str | None,
    text: str | None,
    limit: int,
    offset: int,
    cursor: str | None,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).events_page(
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
        project_not_found(exc)
    return render(request, "events", model)


# START_FUNCTION_CONTRACT
# name: project_logs_impl
# purpose: Render selected-project bounded Logs data or its HTMX fragment.
# inputs: request, project key, log filters/cursors and facade callbacks.
# returns: Full-shell or fragment HTMLResponse.
# side_effects: Selected-project log API read through Hub service.
# emitted_logs: Hub-owned log read logs.
# error_behavior: Unknown projects use 404; partial data remains visible.
# END_FUNCTION_CONTRACT
async def project_logs_impl(
    request: Request,
    project_key: str,
    contains: str | None,
    level: str | None,
    source: str | None,
    worker: str | None,
    packet: str | None,
    run: str | None,
    stage: str | None,
    trace_id: str | None,
    regex: str | None,
    since: str | None,
    until: str | None,
    tail: int,
    cursor: str | None,
    follow: bool,
    wrap: bool,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    render_fragment: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).logs_page(
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
        project_not_found(exc)
    if request.headers.get("HX-Request", "").casefold() == "true":
        return render_fragment(request, "logs", model)
    return render(request, "logs", model)


# END_BLOCK_PROJECT_EXPLORER
