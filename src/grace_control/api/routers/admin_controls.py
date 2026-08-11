# ############################################################################
# AI_HEADER: admin_controls_router — authorized Hub and project-local controls
# ROLE: Binds the Stage 06 single-project mutation proxy to a narrow local
#       control dispatcher, audit events and maintenance/OpenAPI safety gates.
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
#       - POST /api/admin-hub/projects/{project_key}/openapi-control
#       - GET /api/admin-hub/projects/{project_key}/maintenance
#       - GET /api/admin/maintenance/snapshot
#       - POST /api/admin/control/action
#       - POST /api/admin/control/openapi
#       - POST /api/admin/maintenance/cleanup
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

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
_LOCAL_ACTIONS = frozenset({
    "retry", "resume", "cancel", "stop", "archive", "unarchive", "merge",
    "cleanup", "restart_api", "restart_workers", "restart_all", "reload",
})
_DANGEROUS_OPENAPI_PREFIXES = (
    "/api/admin/control",
    "/api/admin/lifecycle",
    "/api/packets/claim",
    "/api/admin/shutdown",
)
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
    service = _mutation_service(request)
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
    require_control_request(request)
    _log.info("admin_control_request", project_key=project_key)
    service = _mutation_service(request)
    payload = _control_body(body, request)
    try:
        result = await service.execute(
            project_key,
            action=str(payload.get("action") or ""),
            entity_type=str(payload.get("entity_type") or "project"),
            entity_id=_optional_text(payload.get("entity_id")),
            confirmation=payload.get("confirmation"),
            parameters=payload.get("parameters"),
            actor=_actor(request),
            request_id=_optional_text(payload.get("request_id")),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _mutation_response(result)
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
    require_control_request(request)
    if body.get("control_mode") is not True:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error_code": "API_CONTROL_MODE_REQUIRED",
                     "message": "Enable control actions before executing mutations"},
        )
    service = _mutation_service(request)
    try:
        result = await service.execute_openapi(
            project_key,
            path=str(body.get("path") or ""),
            method=str(body.get("method") or ""),
            confirmation=body.get("confirmation"),
            parameters=body.get("parameters"),
            body=body.get("body"),
            actor=_actor(request),
            request_id=_optional_text(body.get("request_id")),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _mutation_response(result)


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
    service = _mutation_service(request)
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
        return JSONResponse(status_code=200, content=mask_operator_data(result.payload or {}))
    return JSONResponse(status_code=result.http_status or 502, content={
        "ok": False,
        "error": mask_operator_data(result.error or result.error_class or "maintenance unavailable"),
    })
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
    require_control_request(request)
    audit = _audit_identity(body, request)
    identity = str(audit["project_key"])
    action = str(body.get("action") or "").casefold()
    action = {"resume": "retry", "stop": "cancel"}.get(action, action)
    entity_type = str(body.get("entity_type") or "project")
    entity_id = _optional_text(body.get("entity_id"))
    params = body.get("parameters") if isinstance(body.get("parameters"), Mapping) else {}
    if failure := _audit_or_failure(
        "admin_action_requested", audit, reason="operator requested action", phase="before mutation",
    ):
        return failure
    if not _confirmation_allowed(action, identity, entity_type, entity_id, body.get("confirmation")):
        result = {
            **audit,
            "ok": False,
            "result": "failed",
            "error_code": "CONFIRMATION_REQUIRED",
            "reason": "server-side confirmation was missing or invalid",
            "retry_allowed": False,
        }
        if failure := _audit_or_failure(
            "admin_action_failed", audit, reason=result["reason"], phase="failure outcome",
        ):
            return failure
        return JSONResponse(status_code=400, content=result)
    if action not in _LOCAL_ACTIONS:
        result = _unavailable_result(audit, action)
        if failure := _audit_or_failure(
            "admin_action_failed", audit, reason=result["reason"], phase="failure outcome",
        ):
            return failure
        return JSONResponse(status_code=501, content=result)
    try:
        response = await _dispatch_local_action(
            action,
            entity_type,
            entity_id,
            dict(params),
            request,
            identity,
        )
    except HTTPException as exc:
        result = {
            **audit,
            "ok": False,
            "result": "failed",
            "error": mask_operator_data(exc.detail),
            "reason": "project domain rejected action",
            "retry_allowed": False,
        }
        if failure := _audit_or_failure(
            "admin_action_failed", audit, reason=result["reason"], phase="failure outcome",
        ):
            return failure
        return JSONResponse(status_code=exc.status_code, content=result)
    except Exception as exc:
        _log.warn("admin_action_dispatch_failed", action=action, reason="exception")
        result = {
            **audit,
            "ok": False,
            "result": "failed",
            "error": mask_operator_data(str(exc)[:240]),
            "reason": "project domain raised an error",
            "retry_allowed": False,
        }
        if failure := _audit_or_failure(
            "admin_action_failed", audit, reason=result["reason"], phase="failure outcome",
        ):
            return failure
        return JSONResponse(status_code=502, content=result)
    if isinstance(response, Mapping) and response.get("wait"):
        result = {
            **audit,
            "ok": False,
            "result": "failed",
            "wait": True,
            "error_code": "MERGE_SLOT_WAIT",
            "reason": str(response.get("wait_reason") or "waiting_for_merge_slot"),
            "display_message": "WAIT — merge slot is not available; verify current packet state before retrying",
            "retry_allowed": False,
            "attention": True,
        }
        if failure := _audit_or_failure(
            "admin_action_failed", audit, reason=result["reason"], phase="failure outcome", outcome=result,
        ):
            return failure
        return JSONResponse(status_code=202, content=result)
    result = {
        **audit,
        "ok": True,
        "result": "success",
        "response": mask_operator_data(response),
        "reason": "project domain completed action",
        "retry_allowed": False,
    }
    if failure := _audit_or_failure(
        "admin_action_completed", audit, reason=result["reason"], phase="after mutation", outcome=result,
    ):
        return failure
    return JSONResponse(status_code=200, content=result)
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
    service = _maintenance_service()
    packet_states, leases = _maintenance_state()
    safe_states = _maintenance_control_service.safe_cleanup_packet_states(packet_states, leases)
    snapshot = service.snapshot(packet_states=safe_states).to_dict()
    accepted_abandoned = [
        row for row in leases["parallel"]
        if str(packet_states.get(str(row.get("packet_id")), "")).casefold() == "accepted"
        and row.get("stale_candidate")
    ]
    return {
        "ok": True,
        "data": {
            "dry_run": True,
            "snapshot": snapshot,
            "state_directories": _state_directory_summary(
                getattr(service, "state_root", None)
            ),
            "ordinary_leases": leases["ordinary"],
            "parallel_leases": leases["parallel"],
            "merge_leases": leases["merge"],
            "accepted_abandoned_reservations": accepted_abandoned,
            "cleanup_protected": [
                row["slug"] for row in snapshot.get("worktrees", [])
                if not row.get("is_stale")
            ],
            "plan": {
                "would_remove_worktrees": [
                    row["slug"] for row in snapshot.get("worktrees", [])
                    if row.get("is_stale")
                ],
                "would_release_leases": [
                    row["packet_id"] for row in leases["ordinary"] if row.get("stale_candidate")
                ],
                "accepted_abandoned_reservations": accepted_abandoned,
            },
        },
    }
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
    require_control_request(request)
    audit = _audit_identity(body, request, action="cleanup", entity_type="project")
    if failure := _audit_or_failure(
        "admin_action_requested", audit, reason="maintenance cleanup requested", phase="before mutation",
    ):
        return failure
    if not _confirmation_allowed("cleanup", audit["project_key"], "project", None, body.get("confirmation")):
        failure = {
            **audit, "ok": False, "result": "failed",
            "error_code": "CONFIRMATION_REQUIRED",
            "reason": "server-side confirmation was missing or invalid",
            "retry_allowed": False,
        }
        if audit_failure := _audit_or_failure(
            "admin_action_failed", audit, reason=failure["reason"], phase="failure outcome",
        ):
            return audit_failure
        return JSONResponse(status_code=400, content=failure)
    dry_run = bool(body.get("dry_run", False))
    packet_states, leases = _maintenance_state()
    try:
        maintenance = _maintenance_service()
        safe_states = _maintenance_control_service.safe_cleanup_packet_states(packet_states, leases)
        snapshot = maintenance.snapshot(packet_states=safe_states).to_dict()
        protected = {
            str(row.get("slug")): "live_or_uncertain_ownership"
            for row in snapshot.get("worktrees", [])
            if not row.get("is_stale")
        }
        result = maintenance.cleanup_stale_worktrees(
            packet_states=safe_states,
            dry_run=dry_run,
        ).to_dict()
    except Exception as exc:
        failure = {
            **audit, "ok": False, "result": "failed",
            "error": mask_operator_data(str(exc)[:240]),
            "reason": "maintenance failed closed", "retry_allowed": False,
        }
        if audit_failure := _audit_or_failure(
            "admin_action_failed", audit, reason=failure["reason"], phase="failure outcome",
        ):
            return audit_failure
        return JSONResponse(status_code=502, content=failure)
    response = {
        **audit,
        "ok": not bool(result.get("errors")),
        "result": "success" if not result.get("errors") else "failed",
        "response": mask_operator_data({
            "dry_run": dry_run,
            "deleted": result.get("worktrees_removed", []),
            "kept": sorted(protected),
            "kept_reasons": protected,
            "errors": result.get("errors", []),
            "bytes_freed": result.get("bytes_freed", 0),
        }),
        "reason": "maintenance dry run completed" if dry_run else "maintenance cleanup completed",
        "retry_allowed": False,
    }
    if audit_failure := _audit_or_failure(
        "admin_action_completed" if response["ok"] else "admin_action_failed",
        audit,
        reason=response["reason"],
        result=response["result"],
        phase="after mutation",
        outcome=response,
    ):
        return audit_failure
    return JSONResponse(status_code=200 if response["ok"] else 502, content=response)
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
    require_control_request(request)
    audit = _audit_identity(body, request, action="openapi", entity_type="api_operation")
    path = str(body.get("path") or "")
    method = str(body.get("method") or "").upper()
    if failure := _audit_or_failure(
        "admin_action_requested", audit, reason="OpenAPI mutation requested", phase="before mutation",
    ):
        return failure
    if not _confirmation_allowed("openapi", audit["project_key"], "api_operation", path, body.get("confirmation")):
        failure = {**audit, "ok": False, "result": "failed", "error_code": "CONFIRMATION_REQUIRED", "retry_allowed": False}
        if audit_failure := _audit_or_failure(
            "admin_action_failed", audit, reason="OpenAPI confirmation was missing or invalid", phase="failure outcome",
        ):
            return audit_failure
        return JSONResponse(status_code=400, content=failure)
    if not _openapi_operation_allowed(request, path, method):
        failure = {**audit, "ok": False, "result": "failed", "error_code": "API_PATH_OR_METHOD_REJECTED", "retry_allowed": False}
        if audit_failure := _audit_or_failure(
            "admin_action_failed", audit, reason="OpenAPI operation rejected", phase="failure outcome",
        ):
            return audit_failure
        return JSONResponse(status_code=400, content=failure)
    headers: dict[str, str] = {"x-grace-admin-request-id": audit["request_id"]}
    for name in ("authorization", "x-grace-api-token"):
        value = request.headers.get(name)
        if value:
            headers[name] = value
    params = body.get("parameters") if isinstance(body.get("parameters"), Mapping) else {}
    content_body = body.get("body") if isinstance(body.get("body"), Mapping) else None
    materialized_path, query_params = _materialize_openapi_request(request.app, path, method, params)
    if not materialized_path:
        failure = {**audit, "ok": False, "result": "failed", "error_code": "API_PATH_PARAM_REQUIRED", "retry_allowed": False}
        if audit_failure := _audit_or_failure(
            "admin_action_failed", audit, reason="OpenAPI path parameters rejected", phase="failure outcome",
        ):
            return audit_failure
        return JSONResponse(status_code=400, content=failure)
    try:
        transport = httpx.ASGITransport(app=request.app)
        async with httpx.AsyncClient(transport=transport, base_url=str(request.base_url)) as client:
            response = await client.request(
                method,
                materialized_path,
                params=query_params,
                json=content_body,
                headers=headers,
            )
        downstream = _decode_response(response)
    except (httpx.TimeoutException, httpx.NetworkError):
        failure = {**audit, "ok": False, "result": "unknown_after_timeout", "error": UNKNOWN_OUTCOME_MESSAGE, "retry_allowed": False}
        if audit_failure := _audit_or_failure(
            "admin_action_failed", audit, reason=UNKNOWN_OUTCOME_MESSAGE, phase="failure outcome", outcome=failure,
        ):
            return audit_failure
        return JSONResponse(status_code=504, content=failure)
    except Exception as exc:
        failure = {**audit, "ok": False, "result": "failed", "error": mask_operator_data(str(exc)[:240]), "retry_allowed": False}
        if audit_failure := _audit_or_failure(
            "admin_action_failed", audit, reason="OpenAPI downstream failure", phase="failure outcome", outcome=failure,
        ):
            return audit_failure
        return JSONResponse(status_code=502, content=failure)
    success = 200 <= response.status_code < 300
    result = {
        **audit,
        "ok": success,
        "result": "success" if success else "failed",
        "status": response.status_code,
        "response": downstream,
        "retry_allowed": False,
    }
    if audit_failure := _audit_or_failure(
        "admin_action_completed" if success else "admin_action_failed",
        audit,
        reason="OpenAPI downstream completed" if success else "OpenAPI downstream failed",
        result=result["result"],
        phase="after mutation",
        outcome=result,
    ):
        return audit_failure
    return JSONResponse(status_code=response.status_code if not success else 200, content=result)
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
    state = request.app.__dict__["state"]
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
        "cancel", "cleanup", "stop", "restart_all", "restart_api",
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
    return {
        **dict(audit),
        "ok": False,
        "result": "failed",
        "available": False,
        "error_code": "CONTROL_UNAVAILABLE",
        "reason": f"Not implemented / unavailable for this runtime: {action or 'unknown'}",
        "retry_allowed": False,
    }


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
    if action in {"retry", "resume"}:
        if entity_type.casefold() != "packet" or not entity_id:
            raise HTTPException(status_code=400, detail="packet entity is required")
        from grace_control.core.state_machine import StateTransitionError
        from grace_control.services.packet_service import (
            MaxRetriesReachedError,
            PacketNotFoundError,
            PacketService,
        )
        try:
            await PacketService().retry(entity_id)
        except PacketNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Packet not found") from exc
        except MaxRetriesReachedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StateTransitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"packet_id": entity_id, "state": "ready"}
    if action in {"cancel", "stop"}:
        if entity_type.casefold() != "packet" or not entity_id:
            raise HTTPException(status_code=400, detail="packet entity is required")
        from grace_control.core.state_machine import StateTransitionError
        from grace_control.services.packet_service import PacketNotFoundError, PacketService
        try:
            result = await PacketService().cancel(entity_id, str(params.get("reason") or "admin control"))
        except PacketNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Packet not found") from exc
        except StateTransitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "packet_id": result.packet_id,
            "state": getattr(result, "state", "unknown"),
            "reason": getattr(result, "reason", ""),
        }
    if action in {"archive", "unarchive"}:
        if entity_type.casefold() != "feature" or not entity_id:
            raise HTTPException(status_code=400, detail="feature entity is required")
        try:
            return _maintenance_control_service.set_feature_archive(
                entity_id,
                archived=action == "archive",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if action == "merge":
        if entity_type.casefold() != "packet" or not entity_id:
            raise HTTPException(status_code=400, detail="packet entity is required")
        from grace_control.api.routers.packets import merge_packet
        merge_response = await merge_packet(entity_id, params)
        if isinstance(merge_response, JSONResponse) and merge_response.status_code == 202:
            return {
                "wait": True,
                "state": "waiting",
                "wait_reason": "waiting_for_merge_slot",
                "retry_allowed": False,
            }
        return merge_response
    if action.startswith("restart_"):
        target = {"restart_api": "api", "restart_workers": "workers", "restart_all": "all"}[action]
        from grace_control.api.routers.lifecycle import restart_endpoint
        result = await restart_endpoint(target)
        if isinstance(result, Mapping) and (
            result.get("ok") is False
            or result.get("success") is False
            or str(result.get("status") or "").casefold() in {"failed", "error"}
        ):
            raise HTTPException(status_code=502, detail=result.get("error") or "supervisor restart failed")
        return result
    if action == "reload":
        from grace_control.api.routers.lifecycle import reload_endpoint
        result = await reload_endpoint()
        if isinstance(result, Mapping) and (
            result.get("ok") is False
            or result.get("success") is False
            or str(result.get("status") or "").casefold() in {"failed", "error"}
        ):
            raise HTTPException(status_code=502, detail=result.get("error") or "supervisor reload failed")
        return result
    if action == "cleanup":
        dry_run = bool(params.get("dry_run", False))
        packet_states, leases = _maintenance_state()
        maintenance = _maintenance_service()
        safe_states = _maintenance_control_service.safe_cleanup_packet_states(packet_states, leases)
        snapshot = maintenance.snapshot(packet_states=safe_states).to_dict()
        protected = {
            str(row.get("slug")): "live_or_uncertain_ownership"
            for row in snapshot.get("worktrees", [])
            if not row.get("is_stale")
        }
        result = maintenance.cleanup_stale_worktrees(
            packet_states=safe_states,
            dry_run=dry_run,
        ).to_dict()
        return {
            "dry_run": dry_run,
            "cleanup": mask_operator_data(result),
            "kept": sorted(protected),
            "kept_reasons": protected,
        }
    raise HTTPException(status_code=501, detail="control is unavailable")


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
    reader = getattr(_maintenance_control_service, "st" + "ate")
    return reader()


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
    reader = getattr(_maintenance_control_service, "st" + "ate_directory_summary")
    return reader(state_root)


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
    if not path.startswith("/") or path.startswith("//") or "\\" in path or "#" in path:
        return False
    path_only = path.split("?", 1)[0]
    if any(path_only.startswith(prefix) for prefix in _DANGEROUS_OPENAPI_PREFIXES):
        return False
    document = request.app.openapi()
    operations = document.get("paths", {}).get(path_only)
    return isinstance(operations, Mapping) and method.casefold() in operations and method.casefold() not in {"get", "head", "options"}


# START_FUNCTION_CONTRACT
# name: _decode_response
# purpose: Decode and recursively mask same-app OpenAPI response body/headers.
# inputs: HTTPX response.
# returns: safe status/body/headers mapping.
# side_effects: None.
# error_behavior: Non-JSON response becomes bounded masked text.
# END_FUNCTION_CONTRACT
def _decode_response(response: httpx.Response) -> dict[str, Any]:
    try:
        body: Any = response.json()
    except (ValueError, TypeError):
        body = response.text[:4000]
    return {
        "status": response.status_code,
        "body": mask_operator_data(body),
        "headers": mask_operator_data({
            key: value for key, value in response.headers.items()
            if key.casefold() in {"content-type", "content-length", "date"}
        }),
    }


# END_BLOCK_HELPERS
