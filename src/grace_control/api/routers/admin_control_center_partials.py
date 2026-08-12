# ############################################################################
# AI_HEADER: admin_control_center_partials — Control Center HTMX owner
# ROLE: Owns project-content, query-compatibility and system partial bodies
#       while the facade preserves route registration and rendering callbacks.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Compose explicit project partial requests and render bounded HTMX
#          fragments without replacing the persistent Control Center shell.
# inputs: Explicit project/entity/tab/run/stage/explorer selectors and callbacks.
# returns: HTMLResponse partials.
# side_effects: Selected-project read calls only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Missing query project_key remains FastAPI 422; unknown project
#                 keys use the supplied canonical UI 404 callback.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: partial_project_impl
#   - function: partial_project_query_impl
#   - function: partial_system_impl
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center import AdminControlCenterService

_log = GraceLogger("admin_control_center_partials")


# START_BLOCK_PARTIALS
# START_FUNCTION_CONTRACT
# name: partial_project_impl
# purpose: Poll and replace only selected project content while preserving all
#          explicit project/entity/tab/run/stage/timeline values.
# inputs: request, project key, partial selectors and facade callbacks.
# returns: HTMLResponse project content partial.
# side_effects: Selected-project API reads only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Unknown project uses the canonical 404 callback.
# END_FUNCTION_CONTRACT
async def partial_project_impl(
    request: Request,
    project_key: str,
    entity_type: str | None,
    entity_id: str | None,
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
    render_project_partial: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).project_page(
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
        project_not_found(exc)
    return render_project_partial(request, model)


# START_FUNCTION_CONTRACT
# name: partial_project_query_impl
# purpose: Preserve the legacy query-form HTMX compatibility endpoint.
# inputs: request, explicit query project key, partial selectors and current
#         facade partial-route callback.
# returns: HTMLResponse project content partial.
# side_effects: Same selected-project reads as the path partial.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Delegates validation/404 behavior to the current partial route.
# END_FUNCTION_CONTRACT
async def partial_project_query_impl(
    request: Request,
    project_key: str,
    entity_type: str | None,
    entity_id: str | None,
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
    partial_project: Callable[..., Any],
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
# name: partial_system_impl
# purpose: Poll selected-project System data without replacing the full shell.
# inputs: request, project key, service/templates and URL/status callbacks.
# returns: HTMLResponse system partial.
# side_effects: Selected-project health/worker/diagnostic reads only.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Unknown project uses the canonical 404 callback.
# END_FUNCTION_CONTRACT
async def partial_system_impl(
    request: Request,
    project_key: str,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    templates: Jinja2Templates,
    cc_url: Callable[..., str],
    status_icon: Callable[[Any], str],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).system_page(project_key)
    except KeyError as exc:
        project_not_found(exc)
    return templates.TemplateResponse(request, "control/_system.html", {
        "request": request,
        **model,
        "cc_url": cc_url,
        "cc_status_icon": status_icon,
    })


# END_BLOCK_PARTIALS
