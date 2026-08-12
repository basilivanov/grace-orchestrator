# ############################################################################
# AI_HEADER: admin_controls_hub — project-selected Hub control route owners
# ROLE: Owns the Admin Hub proxy route behavior while the historical
#       `admin_controls` module retains decorators, names and compatibility
#       seams for route registration and tests.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute selected-project catalog, mutation, OpenAPI and maintenance
#          proxy route bodies without registering duplicate routes.
# inputs: FastAPI request/path/body values and explicit facade callbacks.
# returns: Existing Admin Hub JSON DTOs and HTTP responses.
# side_effects: Delegates bounded reads/mutations through accepted services.
# emitted_logs: admin_control_request and accepted service logs.
# error_behavior: Preserves current 400/404/502/503 mapping and response shape.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: project_controls_impl
#   - function: project_control_impl
#   - function: project_openapi_control_impl
#   - function: project_maintenance_impl
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_security import mask_operator_data

_log = GraceLogger("admin_controls_hub")


# START_BLOCK_HUB
# START_FUNCTION_CONTRACT
# name: project_controls_impl
# purpose: Return capability/state-aware controls for one selected project.
# inputs: request, scalar project key and optional entity selectors.
# returns: JSON control catalog.
# side_effects: Reads only the selected project's capability/entity API.
# emitted_logs: Hub read logs.
# error_behavior: 404 for unknown project; unavailable controls remain explicit.
# END_FUNCTION_CONTRACT
async def project_controls_impl(
    request: Request,
    project_key: str,
    entity_type: str | None,
    entity_id: str | None,
    *,
    mutation_service: Callable[[Request], Any],
) -> dict[str, Any]:
    service = mutation_service(request)
    try:
        return await service.available_controls(
            project_key,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# START_FUNCTION_CONTRACT
# name: project_control_impl
# purpose: Execute one authorized, confirmed mutation against exactly one
#          immutable selected project.
# inputs: request, scalar project key, bounded body and facade callbacks.
# returns: Normalized mutation result with request ID and outcome state.
# side_effects: One selected project-local POST at most.
# emitted_logs: admin_control_request plus mutation service outcome logs.
# error_behavior: 401/403 auth-origin failures; 400 validation; 504 unknown.
# END_FUNCTION_CONTRACT
async def project_control_impl(
    request: Request,
    project_key: str,
    body: dict[str, Any],
    *,
    require_control_request: Callable[[Request], Any],
    mutation_service: Callable[[Request], Any],
    control_body: Callable[[Mapping[str, Any], Request], dict[str, Any]],
    optional_text: Callable[[Any], str | None],
    actor: Callable[[Request], str],
    mutation_response: Callable[[Mapping[str, Any]], JSONResponse],
    log_info: Callable[..., Any],
) -> JSONResponse:
    require_control_request(request)
    log_info("admin_control_request", project_key=project_key)
    service = mutation_service(request)
    payload = control_body(body, request)
    try:
        result = await service.execute(
            project_key,
            action=str(payload.get("action") or ""),
            entity_type=str(payload.get("entity_type") or "project"),
            entity_id=optional_text(payload.get("entity_id")),
            confirmation=payload.get("confirmation"),
            parameters=payload.get("parameters"),
            actor=actor(request),
            request_id=optional_text(payload.get("request_id")),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return mutation_response(result)


# START_FUNCTION_CONTRACT
# name: project_openapi_control_impl
# purpose: Execute only a selected project's exact discovered non-GET OpenAPI
#          operation when explicit control mode and confirmation are supplied.
# inputs: request, project key, bounded body and facade callbacks.
# returns: Normalized mutation result.
# side_effects: At most one selected project-local discovered mutation.
# emitted_logs: Mutation service logs and project-local audit logs.
# error_behavior: Control mode off, unsafe paths and missing confirmation reject.
# END_FUNCTION_CONTRACT
async def project_openapi_control_impl(
    request: Request,
    project_key: str,
    body: dict[str, Any],
    *,
    require_control_request: Callable[[Request], Any],
    mutation_service: Callable[[Request], Any],
    optional_text: Callable[[Any], str | None],
    actor: Callable[[Request], str],
    mutation_response: Callable[[Mapping[str, Any]], JSONResponse],
) -> JSONResponse:
    require_control_request(request)
    if body.get("control_mode") is not True:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error_code": "API_CONTROL_MODE_REQUIRED",
                     "message": "Enable control actions before executing mutations"},
        )
    service = mutation_service(request)
    try:
        result = await service.execute_openapi(
            project_key,
            path=str(body.get("path") or ""),
            method=str(body.get("method") or ""),
            confirmation=body.get("confirmation"),
            parameters=body.get("parameters"),
            body=body.get("body"),
            actor=actor(request),
            request_id=optional_text(body.get("request_id")),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return mutation_response(result)


# START_FUNCTION_CONTRACT
# name: project_maintenance_impl
# purpose: Return a selected project's safe maintenance snapshot through its
#          local API without exposing a generic delete path.
# inputs: request, scalar project key and mutation-service resolver.
# returns: JSON maintenance snapshot.
# side_effects: One selected project-local GET.
# emitted_logs: Project read logs.
# error_behavior: 404 unknown project; remote errors are returned safely.
# END_FUNCTION_CONTRACT
async def project_maintenance_impl(
    request: Request,
    project_key: str,
    *,
    mutation_service: Callable[[Request], Any],
    mask_data: Callable[[Any], Any] = mask_operator_data,
) -> JSONResponse:
    service = mutation_service(request)
    try:
        context = service._hub._registry.get(project_key)
        result = await service._hub._request(
            context,
            "/api/admin/maintenance/snapshot",
            operation="maintenance_snapshot",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    if result.ok:
        return JSONResponse(status_code=200, content=mask_data(result.payload or {}))
    return JSONResponse(status_code=result.http_status or 502, content={
        "ok": False,
        "error": mask_data(result.error or result.error_class or "maintenance unavailable"),
    })


# END_BLOCK_HUB
