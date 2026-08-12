# ############################################################################
# AI_HEADER: admin_controls_local — local action and legacy route owners
# ROLE: Owns the project-local action dispatcher, canonical audit sequencing
#       and legacy adapter bodies while the facade preserves route/seam names.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Dispatch narrow local actions through existing domain services and
#          preserve audit-before/after and legacy compatibility semantics.
# inputs: Authenticated request, bounded action body and explicit facade seams.
# returns: JSONResponse mutation outcomes or legacy-adapted local responses.
# side_effects: Local state transitions, supervisor calls, maintenance and
#                canonical Event audit writes through supplied callbacks.
# emitted_logs: admin_action_dispatch_failed and existing domain/audit logs.
# error_behavior: Confirmation/audit/domain failures remain explicit failures;
#                 unsupported actions return 501.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: local_control_action_impl
#   - function: legacy_admin_action_impl
#   - function: dispatch_local_action_impl
#   - function: _unavailable_result
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_security import mask_operator_data
from grace_control.services.supervisor_control_service import (
    SupervisorNotRunningError,
    SupervisorRemoteError,
    SupervisorUnavailableError,
)

_log = GraceLogger("admin_controls_local")

_LOCAL_ACTIONS = frozenset({
    "retry", "resume", "cancel", "stop", "archive", "unarchive", "merge",
    "cleanup", "restart_api", "restart_workers", "restart_all", "reload",
})


# START_BLOCK_LOCAL_CONTROL
# START_FUNCTION_CONTRACT
# name: local_control_action_impl
# purpose: Receive Hub-proxied actions inside the project runtime and delegate
#          them to existing PacketService, lifecycle or maintenance services.
# inputs: authenticated request, bounded action body, action allowlist and
#         facade callbacks.
# returns: JSON result from the local domain/API service.
# side_effects: Project-local state transitions, supervisor calls or approved
#               maintenance; writes canonical admin audit events.
# emitted_logs: admin_action_requested/completed/failed.
# error_behavior: Unsupported/planned actions return 501; domain errors remain
#                 failures and never become fake success.
# END_FUNCTION_CONTRACT
async def local_control_action_impl(
    request: Request,
    body: dict[str, Any],
    *,
    require_control_request: Callable[[Request], Any],
    audit_identity: Callable[..., dict[str, Any]],
    optional_text: Callable[[Any], str | None],
    audit_or_failure: Callable[..., JSONResponse | None],
    confirmation_allowed: Callable[..., bool],
    unavailable_result: Callable[[Mapping[str, Any], str], dict[str, Any]],
    dispatch_local_action: Callable[..., Any],
    local_actions: Collection[str] = _LOCAL_ACTIONS,
    mask_data: Callable[[Any], Any] = mask_operator_data,
    log_warn: Callable[..., Any] = _log.warn,
) -> JSONResponse:
    require_control_request(request)
    audit = audit_identity(body, request)
    identity = str(audit["project_key"])
    action = str(body.get("action") or "").casefold()
    action = {"resume": "retry", "stop": "cancel"}.get(action, action)
    entity_type = str(body.get("entity_type") or "project")
    entity_id = optional_text(body.get("entity_id"))
    params = body.get("parameters") if isinstance(body.get("parameters"), Mapping) else {}
    if failure := audit_or_failure(
        "admin_action_requested", audit, reason="operator requested action", phase="before mutation",
    ):
        return failure
    if not confirmation_allowed(action, identity, entity_type, entity_id, body.get("confirmation")):
        result = {
            **audit,
            "ok": False,
            "result": "failed",
            "error_code": "CONFIRMATION_REQUIRED",
            "reason": "server-side confirmation was missing or invalid",
            "retry_allowed": False,
        }
        if failure := audit_or_failure(
            "admin_action_failed", audit, reason=result["reason"], phase="failure outcome",
        ):
            return failure
        return JSONResponse(status_code=400, content=result)
    if action not in local_actions:
        result = unavailable_result(audit, action)
        if failure := audit_or_failure(
            "admin_action_failed", audit, reason=result["reason"], phase="failure outcome",
        ):
            return failure
        return JSONResponse(status_code=501, content=result)
    try:
        response = await dispatch_local_action(
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
            "error": mask_data(exc.detail),
            "reason": "project domain rejected action",
            "retry_allowed": False,
        }
        if failure := audit_or_failure(
            "admin_action_failed", audit, reason=result["reason"], phase="failure outcome",
        ):
            return failure
        return JSONResponse(status_code=exc.status_code, content=result)
    except Exception as exc:
        log_warn("admin_action_dispatch_failed", action=action, reason="exception")
        result = {
            **audit,
            "ok": False,
            "result": "failed",
            "error": mask_data(str(exc)[:240]),
            "reason": "project domain raised an error",
            "retry_allowed": False,
        }
        if failure := audit_or_failure(
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
        if failure := audit_or_failure(
            "admin_action_failed", audit, reason=result["reason"], phase="failure outcome", outcome=result,
        ):
            return failure
        return JSONResponse(status_code=202, content=result)
    result = {
        **audit,
        "ok": True,
        "result": "success",
        "response": mask_data(response),
        "reason": "project domain completed action",
        "retry_allowed": False,
    }
    if failure := audit_or_failure(
        "admin_action_completed", audit, reason=result["reason"], phase="after mutation", outcome=result,
    ):
        return failure
    return JSONResponse(status_code=200, content=result)


# START_FUNCTION_CONTRACT
# name: legacy_admin_action_impl
# purpose: Adapt a legacy project-local Admin POST to the canonical dispatcher.
# inputs: Authenticated request, action/entity identity, legacy body aliases and
#          explicit facade seams.
# returns: Canonical local-control JSONResponse, including audited failures.
# side_effects: Delegates at most one local action and writes canonical events.
# emitted_logs: admin_action_requested, admin_action_completed/failed.
# error_behavior: Shared control/confirmation gate rejects unsafe requests;
#                 unsupported actions return explicit 501.
# END_FUNCTION_CONTRACT
async def legacy_admin_action_impl(
    request: Request,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None,
    body: Mapping[str, Any] | None = None,
    parameters: Mapping[str, Any] | None = None,
    local_control_action: Callable[..., Any],
) -> JSONResponse:
    source = dict(body or {})
    supplied_parameters = source.get("parameters")
    merged_parameters = dict(supplied_parameters) if isinstance(supplied_parameters, Mapping) else {}
    if isinstance(parameters, Mapping):
        merged_parameters.update(parameters)
    legacy_value = source.get("confirm", source.get("confirmation_value", source.get("typed_value", "")))
    confirmation = source.get("confirmation", {
        "intent": "confirm" if "confirm" in source else source.get("confirmation_intent") or "",
        "value": legacy_value,
    })
    payload: dict[str, Any] = {"action": action, "entity_type": entity_type, "entity_id": entity_id,
                               "parameters": merged_parameters, "confirmation": confirmation}
    payload.update({key: source[key] for key in ("project_key", "request_id") if key in source})
    return await local_control_action(request, payload)


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


# END_BLOCK_LOCAL_CONTROL


# START_BLOCK_DISPATCH
# START_FUNCTION_CONTRACT
# name: dispatch_local_action_impl
# purpose: Route a narrow action to existing local domain/API functions without
#          duplicating packet transition or fencing logic.
# inputs: action/entity/params/request, immutable identity and maintenance
#         callbacks, including the explicit lifecycle service factory.
# returns: JSON-like domain response.
# side_effects: Local state transition, supervisor control or safe maintenance.
# emitted_logs: Existing domain/service logs.
# error_behavior: Propagates HTTPException so caller records a failed audit.
# END_FUNCTION_CONTRACT
async def dispatch_local_action_impl(
    action: str,
    entity_type: str,
    entity_id: str | None,
    params: dict[str, Any],
    request: Request,
    project_key: str,
    *,
    maintenance_control_service: Any,
    maintenance_service_fn: Callable[[], Any],
    maintenance_state_fn: Callable[[], tuple[dict[str, str], dict[str, list[dict[str, Any]]]]],
    lifecycle_service_fn: Callable[[], Any],
    mask_data: Callable[[Any], Any] = mask_operator_data,
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
            return maintenance_control_service.set_feature_archive(
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
        try:
            result = await lifecycle_service_fn().restart(target)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SupervisorNotRunningError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except SupervisorRemoteError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except SupervisorUnavailableError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if isinstance(result, Mapping) and (
            result.get("ok") is False
            or result.get("success") is False
            or str(result.get("status") or "").casefold() in {"failed", "error"}
        ):
            raise HTTPException(status_code=502, detail=result.get("error") or "supervisor restart failed")
        return result
    if action == "reload":
        try:
            result = await lifecycle_service_fn().reload()
        except SupervisorNotRunningError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except SupervisorRemoteError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except SupervisorUnavailableError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if isinstance(result, Mapping) and (
            result.get("ok") is False
            or result.get("success") is False
            or str(result.get("status") or "").casefold() in {"failed", "error"}
        ):
            raise HTTPException(status_code=502, detail=result.get("error") or "supervisor reload failed")
        return result
    if action == "cleanup":
        dry_run = bool(params.get("dry_run", False))
        packet_states, leases = maintenance_state_fn()
        maintenance = maintenance_service_fn()
        safe_states = maintenance_control_service.safe_cleanup_packet_states(packet_states, leases)
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
            "cleanup": mask_data(result),
            "kept": sorted(protected),
            "kept_reasons": protected,
        }
    raise HTTPException(status_code=501, detail="control is unavailable")


# END_BLOCK_DISPATCH
