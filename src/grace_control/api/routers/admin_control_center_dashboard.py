# ############################################################################
# AI_HEADER: admin_control_center_dashboard — dashboard and project shell owner
# ROLE: Owns dashboard/project-shell read orchestration while the facade keeps
#       historical route decorators, names, signatures and rendering seams.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Compose dashboard, project-card and project deep-link pages through
#          the accepted AdminControlCenterService.
# inputs: FastAPI requests, explicit project/entity selectors and facade callbacks.
# returns: HTMLResponse page models.
# side_effects: Bounded read-only Hub/project service calls.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Unknown project errors use the supplied canonical 404 callback;
#                 empty registries retain the legacy-console fallback.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: admin_landing_impl
#   - function: admin_projects_impl
#   - function: partial_projects_impl
#   - function: project_entity_impl
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center import AdminControlCenterService

_log = GraceLogger("admin_control_center_dashboard")


# START_BLOCK_DASHBOARD
# START_FUNCTION_CONTRACT
# name: admin_landing_impl
# purpose: Render the multi-project dashboard with the historical empty-registry
#          fallback to the legacy console.
# inputs: request, dashboard filter and service/render/legacy callbacks.
# returns: HTMLResponse.
# side_effects: Bounded dashboard reads when projects are configured.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Empty registry invokes the supplied legacy console callback.
# END_FUNCTION_CONTRACT
async def admin_landing_impl(
    request: Request,
    filter: str,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    legacy_console: Callable[..., HTMLResponse],
    render: Callable[..., HTMLResponse],
) -> HTMLResponse:
    service = service_fn(request)
    if not service.contexts():
        return legacy_console(request=request, filter=filter)
    model = await service.dashboard(filter)
    return render(request, "dashboard", model)


# START_FUNCTION_CONTRACT
# name: admin_projects_impl
# purpose: Render the explicit project dashboard alias through the canonical
#          landing route callback.
# inputs: request, dashboard filter and current landing callback.
# returns: HTMLResponse.
# side_effects: Same bounded reads/fallback as the landing route.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Preserves landing callback behavior.
# END_FUNCTION_CONTRACT
async def admin_projects_impl(
    request: Request,
    filter: str,
    *,
    landing: Callable[..., Any],
) -> HTMLResponse:
    return await landing(request=request, filter=filter)


# START_FUNCTION_CONTRACT
# name: partial_projects_impl
# purpose: Render only the project-card grid for HTMX polling.
# inputs: request, dashboard filter, service resolver, templates and URL helpers.
# returns: HTMLResponse project-card partial.
# side_effects: Bounded dashboard reads for configured projects.
# emitted_logs: Service-owned structured read logs.
# error_behavior: Template context remains compatible in empty-registry mode.
# END_FUNCTION_CONTRACT
async def partial_projects_impl(
    request: Request,
    filter: str,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    templates: Jinja2Templates,
    cc_url: Callable[..., str],
    status_icon: Callable[[Any], str],
) -> HTMLResponse:
    service = service_fn(request)
    model = await service.dashboard(filter)
    return templates.TemplateResponse(request, "control/_projects.html", {
        "request": request,
        **model,
        "cc_url": cc_url,
        "cc_status_icon": status_icon,
    })


# START_FUNCTION_CONTRACT
# name: project_entity_impl
# purpose: Render a selected project shell or Feature/Wave deep link using one
#          explicit project key and the accepted page service.
# inputs: request, project key, optional entity type/id and facade callbacks.
# returns: HTMLResponse.
# side_effects: Reads only the selected project through the accepted service.
# emitted_logs: Service-owned structured read logs.
# error_behavior: KeyError is translated by the supplied canonical 404 callback.
# END_FUNCTION_CONTRACT
async def project_entity_impl(
    request: Request,
    project_key: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        service = service_fn(request)
        model = await service.project_page(
            project_key,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    except KeyError as exc:
        project_not_found(exc)
    return render(request, "project", model)


# END_BLOCK_DASHBOARD
