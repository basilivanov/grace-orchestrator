# ############################################################################
# AI_HEADER: admin_control_ui_controls_router — project-local Control Center forms
# ROLE: Binds server-rendered mutation forms to the same authenticated Hub
#       mutation service as the JSON routes. It keeps UI mutation transport
#       separate from the read-only Control Center explorer router.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve project-local Control Center mutation forms.
# inputs: FastAPI requests with one scalar project key and URL-encoded form data.
# returns: Refreshed project HTML with a normalized mutation result banner.
# side_effects: At most one selected-project mutation and bounded project reads.
# emitted_logs: Mutation service and project client structured logs.
# error_behavior: Authentication, origin, confirmation, and project errors stay
#                 visible or are returned by the shared policy helpers.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - POST /admin/p/{project_key}/control
#       - POST /admin/p/{project_key}/api/control
#       - POST /admin/p/{project_key}/maintenance/cleanup
# END_MODULE_MAP

from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from grace_control.api.routers.admin_control_center import (
    _raise_project_not_found,
    _render,
    _service,
)
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_security import require_control_request
from grace_control.services.admin_mutation_service import AdminMutationService

router = APIRouter()
_log = GraceLogger("admin_control_ui_controls_router")


# START_BLOCK_ROUTES
# START_FUNCTION_CONTRACT
# name: project_control_form
# purpose: Bind a server-rendered Control Center form to the selected project's
#          shared mutation service and confirmation policy.
# inputs: request — URL-encoded action/entity/confirmation fields; project_key —
#         immutable scalar registry key.
# returns: Refreshed project page with a normalized result banner.
# side_effects: One selected-project mutation at most, followed by bounded reads.
# emitted_logs: Mutation service and project client structured logs.
# error_behavior: Auth/origin/confirmation failures never become success states.
# END_FUNCTION_CONTRACT
@router.post("/admin/p/{project_key}/control", response_class=HTMLResponse)
async def project_control_form(request: Request, project_key: str) -> HTMLResponse:
    require_control_request(request)
    raw = (await request.body()).decode("utf-8", errors="replace")
    fields = {
        key: values[-1]
        for key, values in parse_qs(raw, keep_blank_values=True).items()
        if values
    }
    entity_type = fields.get("entity_type", "packet")
    entity_id = fields.get("entity_id") or None
    action = fields.get("action", "")
    parameters = {
        key: fields[key]
        for key in (
            "reason",
            "worktree_path",
            "branch_name",
            "commit_sha",
            "parallel_lease_id",
            "claimed_attempt",
        )
        if fields.get(key)
    }
    service = _service(request)
    result = await AdminMutationService(service._hub).execute(
        project_key,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        confirmation={
            "intent": fields.get("confirmation_intent", ""),
            "value": fields.get("confirmation_value", ""),
        },
        parameters=parameters,
        actor=request.headers.get("x-grace-actor", "operator"),
        request_id=fields.get("request_id"),
    )
    try:
        if action in {"restart_api", "restart_workers", "restart_all", "reload"}:
            model = await service.system_page(project_key)
            page = "system"
        else:
            model = await service.project_page(
                project_key,
                entity_type=entity_type,
                entity_id=entity_id,
            )
            page = "project"
    except KeyError as exc:
        _raise_project_not_found(exc)
    model["control_result"] = result
    _log.info("project_control_form_done", project_key=project_key, action=fields.get("action", ""))
    return _render(request, page, model)


# START_FUNCTION_CONTRACT
# name: project_api_control_form
# purpose: Execute one OpenAPI Explorer mutation from an authenticated POST
#          form after the read-only GET explorer has selected the operation.
# inputs: request — URL-encoded path/method/params/body/confirmation fields;
#         project_key — immutable scalar registry key.
# returns: Refreshed API explorer page with a masked result.
# side_effects: One selected-project OpenAPI mutation at most.
# emitted_logs: Mutation service and project client structured logs.
# error_behavior: Auth/origin/control-mode/confirmation failures stay visible.
# END_FUNCTION_CONTRACT
@router.post("/admin/p/{project_key}/api/control", response_class=HTMLResponse)
async def project_api_control_form(request: Request, project_key: str) -> HTMLResponse:
    require_control_request(request)
    raw = (await request.body()).decode("utf-8", errors="replace")
    fields = {
        key: values[-1]
        for key, values in parse_qs(raw, keep_blank_values=True).items()
        if values
    }
    service = _service(request)
    try:
        model = await service.api_page(
            project_key,
            path=fields.get("path"),
            execute=fields.get("execute") == "true",
            params_json=fields.get("params"),
            method=fields.get("method", "GET"),
            control_mode=fields.get("control_mode") == "true",
            body_json=fields.get("body"),
            confirmation_json=fields.get("confirmation"),
            actor=request.headers.get("x-grace-actor", "operator"),
            allow_mutation=True,
        )
    except KeyError as exc:
        _raise_project_not_found(exc)
    _log.info("project_api_control_form_done", project_key=project_key)
    return _render(request, "api", model)


# START_FUNCTION_CONTRACT
# name: project_maintenance_cleanup_form
# purpose: Execute the fixed project maintenance cleanup only after the
#          operator reviewed the selected project's dry-run snapshot.
# inputs: request — URL-encoded typed project confirmation; project_key —
#         immutable scalar registry key.
# returns: Refreshed maintenance page with cleanup result and audit identity.
# side_effects: One selected-project cleanup mutation at most.
# emitted_logs: Mutation service and project client structured logs.
# error_behavior: Auth/origin/confirmation/unknown-project failures stay visible.
# END_FUNCTION_CONTRACT
@router.post("/admin/p/{project_key}/maintenance/cleanup", response_class=HTMLResponse)
async def project_maintenance_cleanup_form(request: Request, project_key: str) -> HTMLResponse:
    require_control_request(request)
    raw = (await request.body()).decode("utf-8", errors="replace")
    fields = {
        key: values[-1]
        for key, values in parse_qs(raw, keep_blank_values=True).items()
        if values
    }
    service = _service(request)
    result = await AdminMutationService(service._hub).execute(
        project_key,
        action="cleanup",
        entity_type="project",
        confirmation={
            "intent": fields.get("confirmation_intent", ""),
            "value": fields.get("confirmation_value", ""),
        },
        actor=request.headers.get("x-grace-actor", "operator"),
        request_id=fields.get("request_id"),
    )
    try:
        model = await service.maintenance_page(project_key)
    except KeyError as exc:
        _raise_project_not_found(exc)
    model["control_result"] = result
    _log.info("project_maintenance_cleanup_form_done", project_key=project_key)
    return _render(request, "maintenance", model)
# END_BLOCK_ROUTES
