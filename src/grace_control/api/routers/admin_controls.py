# ############################################################################
# AI_HEADER: admin_controls_router — authorized Hub and project-local controls
# ROLE: Registers the stable Stage 06 route surface and keeps historical
#       helper/import seams while coherent owner modules execute route bodies.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose project-scoped controls, authorization, confirmation, audit,
#          bounded maintenance and safe discovered OpenAPI mutations.
# inputs: HTTP requests with one scalar project key and bounded JSON bodies.
# returns: JSON control/catalog/snapshot/result DTOs.
# side_effects: Delegates mutations to project-local domain services, writes
#               project-local Event rows and may perform approved maintenance.
# emitted_logs: admin_control_request, admin_action_requested,
#               admin_action_completed, admin_action_failed.
# error_behavior: Unauthorized/cross-origin/invalid confirmation requests are
#                 rejected; unavailable runtime controls return explicit failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /api/admin-hub/projects/{project_key}/controls
#       - POST /api/admin-hub/projects/{project_key}/controls
#       - POST /api/admin-hub/projects/{project_key}/control
#       - POST /api/admin-hub/projects/{project_key}/openapi-control
#       - POST /api/admin-hub/projects/{project_key}/api-control
#       - GET /api/admin-hub/projects/{project_key}/maintenance
#       - GET /api/admin/maintenance/snapshot
#       - POST /api/admin/control/action
#       - POST /api/admin/control/openapi
#       - POST /api/admin/maintenance/cleanup
#   - function: legacy_admin_action
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from grace_control.api.routers.admin_controls_hub import (
    project_control_impl as _project_control_impl,
)
from grace_control.api.routers.admin_controls_hub import (
    project_controls_impl as _project_controls_impl,
)
from grace_control.api.routers.admin_controls_hub import (
    project_maintenance_impl as _project_maintenance_impl,
)
from grace_control.api.routers.admin_controls_hub import (
    project_openapi_control_impl as _project_openapi_control_impl,
)
from grace_control.api.routers.admin_controls_local import (
    _LOCAL_ACTIONS,
)
from grace_control.api.routers.admin_controls_local import (
    _unavailable_result as _local_unavailable_result,
)
from grace_control.api.routers.admin_controls_local import (
    dispatch_local_action_impl as _dispatch_local_action_impl,
)
from grace_control.api.routers.admin_controls_local import (
    legacy_admin_action_impl as _legacy_admin_action_impl,
)
from grace_control.api.routers.admin_controls_local import (
    local_control_action_impl as _local_control_action_impl,
)
from grace_control.api.routers.admin_controls_maintenance import (
    local_maintenance_cleanup_impl as _local_maintenance_cleanup_impl,
)
from grace_control.api.routers.admin_controls_maintenance import (
    local_maintenance_snapshot_impl as _local_maintenance_snapshot_impl,
)
from grace_control.api.routers.admin_controls_openapi import (
    _DANGEROUS_OPENAPI_PREFIXES,
)
from grace_control.api.routers.admin_controls_openapi import (
    decode_response as _decode_response_impl,
)
from grace_control.api.routers.admin_controls_openapi import (
    local_openapi_control_impl as _local_openapi_control_impl,
)
from grace_control.api.routers.admin_controls_openapi import (
    openapi_operation_allowed as _openapi_operation_allowed_impl,
)
from grace_control.core.event_recorder import record_event
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_local_helpers import (
    _audit_failure_response as _build_audit_failure_response,
)
from grace_control.services.admin_control_local_helpers import (
    _audit_identity,
    _materialize_openapi_request,
    _optional_text,
)
from grace_control.services.admin_control_local_helpers import (
    _record_admin_event as _persist_admin_event,
)
from grace_control.services.admin_control_security import mask_operator_data, require_control_request
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.services.admin_maintenance_control_service import AdminMaintenanceControlService
from grace_control.services.admin_mutation_service import (
    UNKNOWN_OUTCOME_MESSAGE,
    AdminMutationService,
)
from grace_control.services.maintenance_service import MaintenanceService

router = APIRouter()
_log = GraceLogger("admin_controls_router")
_maintenance_control_service = AdminMaintenanceControlService()


# START_BLOCK_HUB
# START_FUNCTION_CONTRACT
# name: project_controls
# purpose: Return capability/state-aware controls for one selected project.
# inputs: request and one scalar project_key/entity selectors in query/body.
# returns: JSON control catalog.
# side_effects: Reads only the selected project's capability/entity API.
# emitted_logs: Hub read logs.
# error_behavior: 404 for unknown project; unavailable controls remain explicit.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/projects/{project_key}/controls")
async def project_controls(
    request: Request,
    project_key: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    return await _project_controls_impl(
        request,
        project_key,
        entity_type,
        entity_id,
        mutation_service=_mutation_service,
    )


# START_FUNCTION_CONTRACT
# name: project_control
# purpose: Execute one authorized, confirmed mutation against exactly one
#          immutable selected project.
# inputs: request, scalar project_key and bounded JSON control body.
# returns: Normalized mutation result with request ID and outcome state.
# side_effects: One selected project-local POST at most; local domain service
#               owns packet/lease/fencing behavior.
# emitted_logs: admin_control_request plus mutation service outcome logs.
# error_behavior: 401/403 auth-origin failures; 400 validation; 504 unknown.
# END_FUNCTION_CONTRACT
@router.post("/api/admin-hub/projects/{project_key}/controls")
@router.post("/api/admin-hub/projects/{project_key}/control")
async def project_control(
    request: Request,
    project_key: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await _project_control_impl(
        request,
        project_key,
        body,
        require_control_request=require_control_request,
        mutation_service=_mutation_service,
        control_body=_control_body,
        optional_text=_optional_text,
        actor=_actor,
        mutation_response=_mutation_response,
        log_info=_log.info,
    )


# START_FUNCTION_CONTRACT
# name: project_openapi_control
# purpose: Execute only a selected project's exact discovered non-GET OpenAPI
#          operation when explicit control mode and confirmation are supplied.
# inputs: request, project_key and bounded body with path/method/params/body.
# returns: Normalized mutation result.
# side_effects: At most one selected project-local discovered mutation.
# emitted_logs: Mutation service logs and project-local audit logs.
# error_behavior: Control mode off, unsafe paths and missing confirmation reject.
# END_FUNCTION_CONTRACT
@router.post("/api/admin-hub/projects/{project_key}/openapi-control")
@router.post("/api/admin-hub/projects/{project_key}/api-control")
async def project_openapi_control(
    request: Request,
    project_key: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await _project_openapi_control_impl(
        request,
        project_key,
        body,
        require_control_request=require_control_request,
        mutation_service=_mutation_service,
        optional_text=_optional_text,
        actor=_actor,
        mutation_response=_mutation_response,
    )


# START_FUNCTION_CONTRACT
# name: project_maintenance
# purpose: Return a selected project's safe maintenance snapshot through its
#          local API without exposing a generic delete path.
# inputs: request and scalar project_key.
# returns: JSON maintenance snapshot.
# side_effects: One selected project-local GET.
# emitted_logs: Project read logs.
# error_behavior: 404 unknown project; remote errors are returned safely.
# END_FUNCTION_CONTRACT
@router.get("/api/admin-hub/projects/{project_key}/maintenance")
async def project_maintenance(request: Request, project_key: str) -> JSONResponse:
    return await _project_maintenance_impl(
        request,
        project_key,
        mutation_service=_mutation_service,
        mask_data=mask_operator_data,
    )


# END_BLOCK_HUB


# START_BLOCK_LOCAL_CONTROL
# START_FUNCTION_CONTRACT
# name: local_control_action
# purpose: Receive Hub-proxied actions inside the project runtime and delegate
#          them to existing PacketService, lifecycle or maintenance services.
# inputs: authenticated request and bounded action body.
# returns: JSON result from the local domain/API service.
# side_effects: Project-local state transitions, supervisor calls or approved
#               maintenance; writes canonical admin audit events.
# emitted_logs: admin_action_requested/completed/failed.
# error_behavior: Unsupported/planned actions return 501 unavailable; domain
#                 errors remain failures and never become fake success.
# END_FUNCTION_CONTRACT
@router.post("/api/admin/control/action")
async def local_control_action(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await _local_control_action_impl(
        request,
        body,
        require_control_request=require_control_request,
        audit_identity=_audit_identity,
        optional_text=_optional_text,
        audit_or_failure=_audit_or_failure,
        confirmation_allowed=_confirmation_allowed,
        unavailable_result=_unavailable_result,
        dispatch_local_action=_dispatch_local_action,
        local_actions=_LOCAL_ACTIONS,
        mask_data=mask_operator_data,
        log_warn=_log.warn,
    )


# START_FUNCTION_CONTRACT
# name: legacy_admin_action
# purpose: Adapt a legacy project-local Admin POST to the canonical dispatcher.
# inputs: Authenticated request, action/entity identity, legacy body aliases and parameters.
# returns: Canonical local-control JSONResponse, including audited failures.
# side_effects: Delegates at most one local action and writes canonical audit events.
# emitted_logs: admin_action_requested, admin_action_completed/failed.
# error_behavior: Shared control/confirmation gate rejects unsafe requests;
#                 unsupported actions return explicit 501.
# END_FUNCTION_CONTRACT
async def legacy_admin_action(
    request: Request, *, action: str, entity_type: str, entity_id: str | None,
    body: Mapping[str, Any] | None = None, parameters: Mapping[str, Any] | None = None,
) -> JSONResponse:
    return await _legacy_admin_action_impl(
        request,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        body=body,
        parameters=parameters,
        local_control_action=local_control_action,
    )


# START_FUNCTION_CONTRACT
# name: local_maintenance_snapshot
# purpose: Build a project-local dry-run/snapshot model including protected
#          worktrees and lease/reservation state without mutating anything.
# inputs: None.
# returns: Safe maintenance snapshot DTO.
# side_effects: Reads local filesystem/Git/DB through MaintenanceService.
# emitted_logs: Maintenance service read logs.
# error_behavior: Missing DB/filesystem data is represented as unavailable.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/maintenance/snapshot")
def local_maintenance_snapshot() -> dict[str, Any]:
    return _local_maintenance_snapshot_impl(
        maintenance_service_fn=_maintenance_service,
        maintenance_state_fn=_maintenance_state,
        maintenance_control_service=_maintenance_control_service,
        state_directory_summary_fn=_state_directory_summary,
    )


# START_FUNCTION_CONTRACT
# name: local_maintenance_cleanup
# purpose: Execute or dry-run only the bounded stale-worktree cleanup backed by
#          MaintenanceService; live/unknown packet ownership remains kept.
# inputs: authenticated request and dry_run boolean body.
# returns: Safe deleted/kept/errors/bytes result.
# side_effects: On confirmed non-dry-run, removes only terminal-like stale
#               worktrees selected by the local service.
# emitted_logs: admin audit plus maintenance cleanup logs.
# error_behavior: Invalid body fails closed; dry_run never mutates.
# END_FUNCTION_CONTRACT
@router.post("/api/admin/maintenance/cleanup")
async def local_maintenance_cleanup(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await _local_maintenance_cleanup_impl(
        request,
        body,
        require_control_request=require_control_request,
        audit_identity=_audit_identity,
        audit_or_failure=_audit_or_failure,
        confirmation_allowed=_confirmation_allowed,
        maintenance_service_fn=_maintenance_service,
        maintenance_state_fn=_maintenance_state,
        maintenance_control_service=_maintenance_control_service,
        mask_data=mask_operator_data,
    )


# END_BLOCK_LOCAL_CONTROL


# START_BLOCK_LOCAL_OPENAPI
# START_FUNCTION_CONTRACT
# name: local_openapi_control
# purpose: Validate an exact local OpenAPI operation and invoke it through the
#          current ASGI app, never an arbitrary URL or shell command.
# inputs: authenticated request with exact path/method/body/params.
# returns: masked downstream status/body plus canonical audit identity.
# side_effects: One bounded request to this same project ASGI app.
# emitted_logs: admin audit events.
# error_behavior: Missing/disallowed operation returns 400/403/501; downstream
#                 failure remains failure.
# END_FUNCTION_CONTRACT
@router.post("/api/admin/control/openapi")
async def local_openapi_control(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await _local_openapi_control_impl(
        request,
        body,
        require_control_request=require_control_request,
        audit_identity=_audit_identity,
        audit_or_failure=_audit_or_failure,
        confirmation_allowed=_confirmation_allowed,
        openapi_operation_allowed=_openapi_operation_allowed,
        materialize_openapi_request=_materialize_openapi_request,
        decode_response=_decode_response,
        mask_data=mask_operator_data,
        unknown_outcome_message=UNKNOWN_OUTCOME_MESSAGE,
    )


# END_BLOCK_LOCAL_OPENAPI


# START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: _mutation_service
# purpose: Resolve the app-scoped Hub service and build its mutation boundary.
# inputs: request — current app request.
# returns: AdminMutationService.
# side_effects: None.
# error_behavior: Raises HTTP 503 when Hub wiring is missing.
# END_FUNCTION_CONTRACT
def _mutation_service(request: Request) -> AdminMutationService:
    state = request.app.state
    hub = getattr(state, "admin_cross_project_service", None)
    if not isinstance(hub, AdminCrossProjectService):
        raise HTTPException(status_code=503, detail="Admin Hub mutation service is unavailable")
    return AdminMutationService(hub)


# START_FUNCTION_CONTRACT
# name: _control_body
# purpose: Normalize JSON confirmation aliases and reject body project-key
#          switching before the service sees the request.
# inputs: body and request headers.
# returns: bounded control body.
# side_effects: None.
# error_behavior: Raises HTTPException for a mismatched embedded project key.
# END_FUNCTION_CONTRACT
def _control_body(body: Mapping[str, Any], request: Request) -> dict[str, Any]:
    result = dict(body)
    embedded_key = result.get("project_key")
    path_key = request.path_params.get("project_key")
    if embedded_key not in (None, path_key):
        raise HTTPException(status_code=400, detail="project_key cannot switch the selected project")
    if "confirmation" not in result:
        result["confirmation"] = {
            "intent": result.get("confirmation_intent") or result.get("confirm") or "",
            "value": result.get("confirmation_value") or result.get("typed_value") or "",
        }
    return result


# START_FUNCTION_CONTRACT
# name: _mutation_response
# purpose: Map normalized result state to an HTTP status without converting
#          unknown or failed outcomes into success.
# inputs: result — mutation DTO.
# returns: JSONResponse.
# side_effects: None.
# error_behavior: 504 for unknown, 202 for explicit wait, 400/502 for failures.
# END_FUNCTION_CONTRACT
def _mutation_response(result: Mapping[str, Any]) -> JSONResponse:
    if result.get("result") == "unknown_after_timeout":
        status = 504
    elif result.get("wait"):
        status = 202
    elif result.get("ok"):
        status = 200
    else:
        status = int(result.get("status") or 400)
        if status < 400:
            status = 502
    return JSONResponse(status_code=status, content=mask_operator_data(dict(result)))


# START_FUNCTION_CONTRACT
# name: _actor
# purpose: Derive a bounded display-safe actor identity from authenticated
#          request metadata without persisting credentials.
# inputs: request.
# returns: Actor string.
# side_effects: None.
# error_behavior: Falls back to operator.
# END_FUNCTION_CONTRACT
def _actor(request: Request) -> str:
    return str(request.headers.get("x-grace-actor") or request.headers.get("x-admin-actor") or "operator")[:120]


# START_FUNCTION_CONTRACT
# name: _record_admin_event
# purpose: Keep the router's recorder seam while delegating strict canonical
#          audit persistence to the local helper service.
# inputs: Event type, audit identity, reason and result.
# returns: True when persisted; False on persistence failure.
# side_effects: Inserts one local Event row.
# emitted_logs: admin_audit_persist_failed on failure.
# error_behavior: Never raises persistence errors.
# END_FUNCTION_CONTRACT
def _record_admin_event(
    event_type: str,
    audit: Mapping[str, Any],
    *,
    reason: str,
    result: str = "success",
) -> bool:
    return _persist_admin_event(
        event_type,
        audit,
        reason=reason,
        result=result,
        recorder=record_event,
    )


# START_FUNCTION_CONTRACT
# name: _audit_or_failure
# purpose: Gate action progress on requested/completed/failed audit persistence.
# inputs: Event/audit fields, failure phase and optional mutation outcome.
# returns: None when persisted, otherwise an audit-integrity JSONResponse.
# side_effects: Writes one canonical local Event row.
# emitted_logs: admin_audit_persist_failed on failure.
# error_behavior: Never permits an unaudited ordinary action response.
# END_FUNCTION_CONTRACT
def _audit_or_failure(
    event_type: str,
    audit: Mapping[str, Any],
    *,
    reason: str,
    phase: str,
    result: str = "success",
    outcome: Mapping[str, Any] | None = None,
) -> JSONResponse | None:
    if _record_admin_event(
        event_type,
        audit,
        reason=reason,
        result=result,
    ):
        return None
    return _build_audit_failure_response(audit, phase=phase, outcome=outcome)


# START_FUNCTION_CONTRACT
# name: _confirmation_allowed
# purpose: Recheck Hub confirmation at the project-local endpoint so a direct
#          local API caller cannot bypass the server-side control policy.
# inputs: action, project/entity identity and confirmation representation.
# returns: True when intent and strong typed identity are valid.
# side_effects: None.
# error_behavior: Malformed values return False.
# END_FUNCTION_CONTRACT
def _confirmation_allowed(
    action: str,
    project_key: str,
    entity_type: str,
    entity_id: str | None,
    confirmation: Any,
) -> bool:
    if isinstance(confirmation, Mapping):
        intent = str(
            confirmation.get("intent")
            or confirmation.get("token")
            or confirmation.get("confirm")
            or ""
        ).casefold()
        value = str(
            confirmation.get("value")
            or confirmation.get("typed")
            or confirmation.get("project_key")
            or ""
        )
    elif isinstance(confirmation, bool):
        intent, value = ("true" if confirmation else ""), ""
    else:
        intent, value = str(confirmation or "").casefold(), str(confirmation or "")
    if intent not in {"confirm", "confirmed", "yes", "true", "1"}:
        return False
    strong = {
        "cancel", "cleanup", "delete", "lifecycle_cleanup", "shutdown", "stop", "restart_all", "restart_api",
        "restart_workers", "reload", "merge", "openapi", "recovery",
    }
    if action.casefold() not in strong:
        return True
    expected = str(entity_id or project_key)
    return value in {expected, project_key}


# START_FUNCTION_CONTRACT
# name: _unavailable_result
# purpose: Build the explicit planned/501 unavailable response required by the
#          control contract.
# inputs: audit identity and action.
# returns: failure DTO.
# side_effects: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _unavailable_result(audit: Mapping[str, Any], action: str) -> dict[str, Any]:
    return _local_unavailable_result(audit, action)


# START_FUNCTION_CONTRACT
# name: _dispatch_local_action
# purpose: Route a narrow action to existing local domain/API functions without
#          duplicating packet transition or fencing logic.
# inputs: action/entity/params/request and immutable local identity.
# returns: JSON-like domain response.
# side_effects: Local state transition, supervisor control or safe maintenance.
# emitted_logs: Existing domain/service logs.
# error_behavior: Propagates HTTPException so caller records a failed audit.
# END_FUNCTION_CONTRACT
async def _dispatch_local_action(
    action: str,
    entity_type: str,
    entity_id: str | None,
    params: dict[str, Any],
    request: Request,
    project_key: str,
) -> Any:
    return await _dispatch_local_action_impl(
        action,
        entity_type,
        entity_id,
        params,
        request,
        project_key,
        maintenance_control_service=_maintenance_control_service,
        maintenance_service_fn=_maintenance_service,
        maintenance_state_fn=_maintenance_state,
        mask_data=mask_operator_data,
    )


# START_FUNCTION_CONTRACT
# name: _maintenance_service
# purpose: Build local maintenance service from fixed runtime roots, never from
#          browser-provided deletion paths.
# inputs: None.
# returns: MaintenanceService.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Uses safe project-relative defaults when settings are empty.
# END_FUNCTION_CONTRACT
def _maintenance_service() -> MaintenanceService:
    return _maintenance_control_service.maintenance_service()


# START_FUNCTION_CONTRACT
# name: _maintenance_state
# purpose: Read packet ownership and lease/reservation summaries for safe
#          maintenance planning without exposing full fencing tokens.
# inputs: None.
# returns: packet state mapping and safe lease groups.
# side_effects: Reads local DB only.
# emitted_logs: None.
# error_behavior: Uninitialized/partial DB returns empty groups.
# END_FUNCTION_CONTRACT
def _maintenance_state() -> tuple[dict[str, str], dict[str, list[dict[str, Any]]]]:
    return _maintenance_control_service.state()


# START_FUNCTION_CONTRACT
# name: _state_directory_summary
# purpose: Describe fixed runtime state-directory entries without exposing
#          arbitrary paths or deleting anything.
# inputs: state_root — fixed local runtime root or None.
# returns: Bounded name/kind/size rows.
# side_effects: Reads directory metadata only.
# error_behavior: Missing/unreadable roots return an empty list.
# END_FUNCTION_CONTRACT
def _state_directory_summary(state_root: Any) -> list[dict[str, Any]]:
    return _maintenance_control_service.state_directory_summary(state_root)


# START_FUNCTION_CONTRACT
# name: _openapi_operation_allowed
# purpose: Validate the exact same-project OpenAPI route/method and reject
#          dangerous generic control paths.
# inputs: request, path and HTTP method.
# returns: True when operation is discovered and safe for local dispatch.
# side_effects: Reads the current app OpenAPI document.
# error_behavior: Missing/malformed docs return False.
# END_FUNCTION_CONTRACT
def _openapi_operation_allowed(request: Request, path: str, method: str) -> bool:
    return _openapi_operation_allowed_impl(
        request,
        path,
        method,
        dangerous_prefixes=_DANGEROUS_OPENAPI_PREFIXES,
    )


# START_FUNCTION_CONTRACT
# name: _decode_response
# purpose: Decode and recursively mask same-app OpenAPI response body/headers.
# inputs: HTTPX response.
# returns: safe status/body/headers mapping.
# side_effects: None.
# error_behavior: Non-JSON response becomes bounded masked text.
# END_FUNCTION_CONTRACT
def _decode_response(response: httpx.Response) -> dict[str, Any]:
    return _decode_response_impl(response)


# END_BLOCK_HELPERS

__all__ = [
    "router",
    "legacy_admin_action",
    "_LOCAL_ACTIONS",
    "_DANGEROUS_OPENAPI_PREFIXES",
]
