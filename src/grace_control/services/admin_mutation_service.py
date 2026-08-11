# ############################################################################
# AI_HEADER: admin_mutation_service — single-project Admin Hub mutation proxy
# ROLE: Authorizes and transports one operator action to one immutable project
#       through its local API; it never opens project state or runs privileged
#       filesystem/Git/process operations from the Hub.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate confirmation, select one project-local control endpoint,
#          propagate an admin request ID and normalize success/failure/unknown
#          mutation outcomes for API and UI consumers.
# inputs: AdminCrossProjectService, one project key, action/entity selectors and
#          bounded JSON parameters.
# returns: JSON-safe mutation result or capability catalog.
# side_effects: Performs at most one project-local mutation request; no retry.
# emitted_logs: admin_mutation_requested, admin_mutation_completed,
#                admin_mutation_failed.
# error_behavior: Invalid confirmation is rejected before transport; timeout or
#                 ambiguous disconnect is UNKNOWN OUTCOME with an exact message.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminMutationService
#     methods:
#       - available_controls
#       - execute
#       - execute_openapi
#   - function: normalize_mutation_result
# END_MODULE_MAP

from __future__ import annotations

import inspect
import re
import uuid
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_explorer_helpers import _openapi_operations
from grace_control.services.admin_control_security import mask_operator_data
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.services.project_client import ProjectApiResult

_log = GraceLogger("admin_mutation_service")

UNKNOWN_OUTCOME_MESSAGE = "UNKNOWN OUTCOME — verify project state before retrying"
_LOCAL_CONTROL_PATH = "/api/admin/control/action"
_LOCAL_OPENAPI_PATH = "/api/admin/control/openapi"
_NORMAL_ACTIONS = frozenset({"retry", "resume", "archive", "unarchive"})
_STRONG_ACTIONS = frozenset({
    "cancel", "cleanup", "cleanup_execute", "stop", "restart_all", "merge",
    "manual_merge", "recovery", "restart_api", "restart_workers", "reload",
})
_READ_ACTIONS = frozenset({"maintenance_snapshot", "controls"})
_ACTION_ALIASES = {
    "resume": "retry",
    "stop": "cancel",
    "restart": "restart_api",
    "restart_api": "restart_api",
    "restart_workers": "restart_workers",
    "restart_all": "restart_all",
    "stop_cancel": "cancel",
    "stop/cancel": "cancel",
    "manual_merge": "merge",
    "cleanup_execute": "cleanup",
}
_TERMINAL_PACKET_STATES = frozenset({
    "accepted", "merged", "failed", "cancelled", "blocked_final",
})
_DANGEROUS_OPENAPI_PREFIXES = (
    "/api/admin/control",
    "/api/admin/lifecycle",
    "/api/packets/claim",
    "/api/admin/shutdown",
)


# START_BLOCK_SERVICE
class AdminMutationService:
    """Hub-side boundary for one project-local operator mutation."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the mutation proxy to the existing registry/client factory.
    # inputs: hub — app-scoped AdminCrossProjectService.
    # returns: None.
    # side_effects: None; no project request occurs during construction.
    # emitted_logs: None.
    # error_behavior: Raises TypeError when hub is not the accepted service.
    # END_FUNCTION_CONTRACT
    def __init__(self, hub: AdminCrossProjectService) -> None:
        if not isinstance(hub, AdminCrossProjectService):
            raise TypeError("AdminMutationService requires AdminCrossProjectService")
        self._hub = hub

    # START_FUNCTION_CONTRACT
    # name: available_controls
    # purpose: Return capability/state-aware controls for one selected project
    #          and optional entity without offering unsupported actions.
    # inputs: project_key — one immutable registry key; entity_type/id optional;
    #         state_hint — trusted read-model state when already available.
    # returns: JSON catalog with available/unavailable action rows.
    # side_effects: Reads selected project's capabilities and optional entity
    #               detail.
    # emitted_logs: Hub read logs through the existing cross-project service.
    # error_behavior: Unknown project raises KeyError; read gaps become explicit
    #                 unavailable reasons instead of optimistic success.
    # END_FUNCTION_CONTRACT
    async def available_controls(
        self,
        project_key: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        state_hint: str | None = None,
    ) -> dict[str, Any]:
        key = _validate_project_key(project_key)
        context = self._hub._registry.get(key)
        if not context.enabled:
            return {
                "project_key": key,
                "controls": [],
                "unavailable": [{"action": "all", "reason": "project is disabled"}],
            }
        capability = await self._hub._request(
            context,
            "/api/admin/capabilities",
            operation="capabilities",
        )
        capability_data = _payload_mapping(capability.payload)
        capability_map = capability_data.get("capabilities")
        advertised = capability_map.get("controls") if isinstance(capability_map, Mapping) else None
        advertised_set = {str(item).casefold() for item in advertised} if isinstance(advertised, list) else set()
        state = (
            str(state_hint or "unknown").casefold()
            if state_hint is not None
            else await self._read_entity_state(key, entity_type, entity_id)
        )
        rows: list[dict[str, Any]] = []
        for action in _catalog_actions(entity_type):
            available, reason = _control_availability(
                action,
                entity_type,
                state,
                advertised_set,
                capability.ok,
            )
            rows.append({
                "action": action,
                "available": available,
                "confirmation": "strong" if action in _STRONG_ACTIONS else "normal",
                "reason": reason,
                "current_state": state,
            })
        return {
            "project_key": key,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "controls": rows,
            "control_actions": {
                str(row["action"]): bool(row["available"])
                for row in rows
            },
            "capabilities": mask_operator_data(capability_data),
        }

    # START_FUNCTION_CONTRACT
    # name: execute
    # purpose: Execute exactly one supported project-local action after
    #          server-side confirmation and return a normalized audit-safe DTO.
    # inputs: project_key, action, entity_type/id, confirmation, parameters and
    #          display-safe actor/request_id.
    # returns: Mutation DTO with success, failed or unknown_after_timeout result.
    # side_effects: At most one POST to the selected project; never retries.
    # emitted_logs: admin_mutation_requested, admin_mutation_completed or failed.
    # error_behavior: Rejects invalid project/action/confirmation before remote
    #                 transport; network ambiguity is never reported success.
    # END_FUNCTION_CONTRACT
    async def execute(
        self,
        project_key: str,
        *,
        action: str,
        entity_type: str = "project",
        entity_id: str | None = None,
        confirmation: Mapping[str, Any] | bool | str | None = None,
        parameters: Mapping[str, Any] | None = None,
        actor: str = "operator",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        key = _validate_project_key(project_key)
        normalized_action = _normalize_action(action)
        params = _bounded_mapping(parameters)
        request_token = _request_id(request_id)
        base = _base_result(
            key,
            normalized_action,
            entity_type,
            entity_id,
            request_token,
            actor,
        )
        if normalized_action in _READ_ACTIONS:
            return {**base, "ok": False, "result": "failed", "status": 400,
                    "error_code": "READ_ACTION_NOT_MUTATION"}
        try:
            _validate_action_entity(normalized_action, entity_type, entity_id)
            _validate_confirmation(
                normalized_action,
                key,
                entity_type,
                entity_id,
                confirmation,
            )
        except ValueError as exc:
            _log.warn("admin_mutation_failed", project_key=key, action=normalized_action,
                      request_id=request_token, reason="validation")
            return {
                **base,
                "ok": False,
                "result": "failed",
                "status": 400,
                "error_code": str(exc).split(":", 1)[0],
                "error": str(exc),
                "retry_allowed": False,
            }

        payload = {
            "project_key": key,
            "action": normalized_action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "parameters": params,
            "confirmation": confirmation,
            "request_id": request_token,
            "actor": mask_operator_data(str(actor)[:120]),
        }
        _log.info("admin_mutation_requested", project_key=key, action=normalized_action,
                  request_id=request_token, entity_id=entity_id or "")
        try:
            raw = await self._call_project(
                key,
                _LOCAL_CONTROL_PATH,
                payload,
                request_token,
                actor,
            )
        except Exception as exc:
            return _unknown_result(base, exc)
        result = normalize_mutation_result(raw, base)
        if result["result"] == "unknown_after_timeout":
            _log.warn("admin_mutation_failed", project_key=key, action=normalized_action,
                      request_id=request_token, reason="unknown_after_timeout")
        elif result["ok"]:
            _log.info("admin_mutation_completed", project_key=key, action=normalized_action,
                      request_id=request_token)
        else:
            _log.warn("admin_mutation_failed", project_key=key, action=normalized_action,
                      request_id=request_token, reason="remote_failure")
        return result

    # START_FUNCTION_CONTRACT
    # name: execute_openapi
    # purpose: Execute one explicitly discovered selected-project mutation only
    #          when control mode and confirmation are both enabled.
    # inputs: project_key, exact discovered path/method, bounded params/body,
    #          confirmation and request identity.
    # returns: Normalized mutation DTO.
    # side_effects: At most one project-local OpenAPI mutation through the
    #                narrow local control endpoint; never arbitrary URL access.
    # emitted_logs: admin_mutation_requested, admin_mutation_completed or failed.
    # error_behavior: Rejects unsafe/undiscovered paths before remote transport.
    # END_FUNCTION_CONTRACT
    async def execute_openapi(
        self,
        project_key: str,
        *,
        path: str,
        method: str,
        confirmation: Mapping[str, Any] | bool | str | None,
        parameters: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        actor: str = "operator",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        key = _validate_project_key(project_key)
        token = _request_id(request_id)
        base = _base_result(key, "openapi", "api_operation", path, token, actor)
        normalized_method = str(method or "").upper()
        if (
            normalized_method in {"GET", "HEAD", "OPTIONS"}
            or not _safe_openapi_path(path)
            or any(path.startswith(prefix) for prefix in _DANGEROUS_OPENAPI_PREFIXES)
        ):
            return {**base, "ok": False, "result": "failed", "status": 400,
                    "error_code": "API_PATH_OR_METHOD_REJECTED", "retry_allowed": False}
        try:
            document_result = await self._hub._request(
                self._hub._registry.get(key),
                "/openapi.json",
                operation="openapi_control_discovery",
            )
            document = _payload_mapping(document_result.payload)
            operations, _get_paths = _openapi_operations(document)
            discovered = next(
                (
                    row for row in operations
                    if row.get("path") == path and row.get("method") == normalized_method
                    and row.get("mutation")
                ),
                None,
            )
        except (KeyError, ValueError):
            discovered = None
        if discovered is None:
            return {**base, "ok": False, "result": "failed", "status": 400,
                    "error_code": "API_PATH_OR_METHOD_REJECTED", "retry_allowed": False}
        try:
            _validate_confirmation("openapi", key, "api_operation", path, confirmation)
        except ValueError as exc:
            return {**base, "ok": False, "result": "failed", "status": 400,
                    "error_code": str(exc).split(":", 1)[0], "error": str(exc),
                    "retry_allowed": False}
        payload = {
            "project_key": key,
            "action": "openapi",
            "entity_type": "api_operation",
            "entity_id": path,
            "parameters": _bounded_mapping(parameters),
            "body": _bounded_mapping(body),
            "confirmation": confirmation,
            "method": normalized_method,
            "path": path,
            "request_id": token,
            "actor": mask_operator_data(str(actor)[:120]),
        }
        try:
            raw = await self._call_project(key, _LOCAL_OPENAPI_PATH, payload, token, actor)
        except Exception as exc:
            return _unknown_result(base, exc)
        return normalize_mutation_result(raw, base)

    # START_FUNCTION_CONTRACT
    # name: _read_entity_state
    # purpose: Read current selected-entity state for capability-aware controls.
    # inputs: project key and optional entity type/id.
    # returns: Lowercase state or unknown.
    # side_effects: One bounded project-local GET when an entity is selected.
    # emitted_logs: Hub read logs.
    # error_behavior: Missing/unavailable data becomes unknown.
    # END_FUNCTION_CONTRACT
    async def _read_entity_state(
        self,
        project_key: str,
        entity_type: str | None,
        entity_id: str | None,
    ) -> str:
        if not entity_type or not entity_id:
            return "unknown"
        path = ""
        if entity_type.casefold() == "packet":
            path = f"/api/admin/packet/{_safe_segment(entity_id)}/detail"
        elif entity_type.casefold() == "feature":
            path = "/api/admin/features"
        if not path:
            return "unknown"
        result = await self._hub._request(
            self._hub._registry.get(project_key), path, operation="control_state",
        )
        payload = _payload_mapping(result.payload)
        if entity_type.casefold() == "packet":
            packet = payload.get("packet") if isinstance(payload.get("packet"), Mapping) else payload
            return str(packet.get("state") or "unknown").casefold()
        features = payload.get("features")
        if isinstance(features, list):
            row = next((item for item in features if isinstance(item, Mapping) and str(item.get("id")) == str(entity_id)), None)
            return str(row.get("status") or "unknown").casefold() if row else "unknown"
        return "unknown"

    # START_FUNCTION_CONTRACT
    # name: _call_project
    # purpose: Call one selected project's mutation-capable client exactly once.
    # inputs: project key, local path, payload, request ID and actor.
    # returns: Raw compatible ProjectApiResult or fake-client response.
    # side_effects: One bounded project-local request.
    # emitted_logs: Project transport logs.
    # error_behavior: Missing mutation support raises a typed runtime error.
    # END_FUNCTION_CONTRACT
    async def _call_project(
        self,
        project_key: str,
        path: str,
        payload: Mapping[str, Any],
        request_id: str,
        actor: str,
    ) -> Any:
        context = self._hub._registry.get(project_key)
        if not context.enabled:
            raise RuntimeError("project is disabled")
        client = self._hub._client_factory(context)
        mutate = getattr(client, "mutate_json", None)
        if callable(mutate):
            kwargs: dict[str, Any] = {"method": "POST", "payload": payload}
            try:
                signature = inspect.signature(mutate)
                if "request_id" in signature.parameters:
                    kwargs["request_id"] = request_id
                if "actor" in signature.parameters:
                    kwargs["actor"] = str(actor)[:120]
            except (TypeError, ValueError):
                pass
            return await mutate(path, **kwargs)
        request_json = getattr(client, "request_json", None)
        if not callable(request_json):
            raise RuntimeError("project runtime does not advertise mutation transport")
        kwargs = {"method": "POST", "payload": payload}
        try:
            signature = inspect.signature(request_json)
            if "request_id" in signature.parameters:
                kwargs["request_id"] = request_id
            if "extra_headers" in signature.parameters:
                kwargs["extra_headers"] = {
                    "x-grace-admin-request-id": request_id,
                    "x-grace-admin-actor": str(actor)[:120],
                }
        except (TypeError, ValueError):
            pass
        return await request_json(path, **kwargs)


# END_BLOCK_SERVICE


# START_BLOCK_NORMALIZATION
# START_FUNCTION_CONTRACT
# name: normalize_mutation_result
# purpose: Convert ProjectApiResult or compatible test/fake responses to the
#          canonical success/failure/unknown outcome DTO.
# inputs: raw — remote result; base — request identity DTO.
# returns: Masked mutation result with status, response and retry safety.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Timeout/connection/no-response errors become unknown outcome.
# END_FUNCTION_CONTRACT
def normalize_mutation_result(raw: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw, ProjectApiResult):
        ok = bool(raw.ok)
        status = raw.http_status
        payload = raw.payload or {}
        error = raw.error or raw.error_class
        error_class = raw.error_class or ""
    elif isinstance(raw, Mapping):
        ok = bool(raw.get("ok", True))
        status = _int_or_none(raw.get("http_status", raw.get("status_code", raw.get("status"))))
        payload = raw.get("payload", raw.get("response", raw))
        error = raw.get("error") or raw.get("message")
        error_class = str(raw.get("error_class") or raw.get("code") or "")
    else:
        ok = False
        status = None
        payload = {}
        error = "project mutation returned an unsupported response"
        error_class = "malformed_response"
    if not isinstance(payload, Mapping):
        payload = {"value": payload}
    payload = dict(payload)
    if isinstance(error, Mapping):
        error = error.get("message") or error.get("detail") or str(error)
    ambiguous = not ok and status is None and _is_ambiguous(error_class, error)
    if ambiguous:
        return {
            **dict(base),
            "ok": False,
            "result": "unknown_after_timeout",
            "unknown_outcome": True,
            "status": 504,
            "display_message": UNKNOWN_OUTCOME_MESSAGE,
            "error": UNKNOWN_OUTCOME_MESSAGE,
            "error_class": error_class or "ambiguous_disconnect",
            "response": mask_operator_data(payload),
            "retry_allowed": False,
            "attention": True,
        }
    planned_text = f"{error_class} {error or ''} {payload.get('detail', '')}".casefold()
    if status == 501 or "not implemented" in planned_text or "planned" in planned_text:
        return {
            **dict(base),
            "ok": False,
            "result": "failed",
            "unknown_outcome": False,
            "status": 501,
            "available": False,
            "error_code": "CONTROL_UNAVAILABLE",
            "error": "Not implemented / unavailable for this runtime",
            "reason": "Not implemented / unavailable for this runtime",
            "response": mask_operator_data(payload),
            "retry_allowed": False,
            "attention": True,
        }
    remote_ok = ok and not ("ok" in payload and payload.get("ok") is False)
    wait_state = bool(payload.get("wait")) or str(
        payload.get("state") or payload.get("status") or payload.get("result") or ""
    ).casefold() in {"waiting", "wait"}
    wait_reason = str(payload.get("wait_reason") or payload.get("reason") or "").strip()
    if wait_state:
        remote_ok = False
    result_name = "success" if remote_ok else "failed"
    return {
        **dict(base),
        "ok": remote_ok,
        "result": result_name,
        "unknown_outcome": False,
        "status": status or (200 if remote_ok else 502),
        "response": mask_operator_data(payload),
        "display_message": f"WAIT — {wait_reason}" if wait_state and wait_reason else None,
        "error": None if remote_ok else mask_operator_data(
            wait_reason or error or "project mutation failed"
        ),
        "error_class": error_class or ("merge_slot_wait" if wait_state else None),
        "retry_allowed": False if wait_state else remote_ok,
        "attention": bool(wait_state or not remote_ok),
        "wait": wait_state,
    }


# END_BLOCK_NORMALIZATION


# START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: _validate_project_key
# purpose: Reject empty/list/path-like project selectors at the mutation
#          boundary so one request cannot broadcast or escape the registry.
# inputs: project_key — explicit scalar registry key.
# returns: Validated string key.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError for invalid selectors.
# END_FUNCTION_CONTRACT
def _validate_project_key(project_key: str) -> str:
    if not isinstance(project_key, str) or not project_key or "/" in project_key or "\\" in project_key:
        raise ValueError("PROJECT_KEY_INVALID: one immutable project_key is required")
    return project_key


# START_FUNCTION_CONTRACT
# name: _normalize_action
# purpose: Canonicalize supported operator action aliases.
# inputs: action — requested action name.
# returns: Lowercase canonical action.
# side_effects: None.
# error_behavior: Raises ValueError for empty/unsupported actions.
# END_FUNCTION_CONTRACT
def _normalize_action(action: str) -> str:
    value = str(action or "").strip().casefold()
    value = _ACTION_ALIASES.get(value, value)
    if value not in _NORMAL_ACTIONS | _STRONG_ACTIONS | {"openapi"}:
        raise ValueError(f"ACTION_UNAVAILABLE: unsupported control action {value or 'empty'}")
    return value


# START_FUNCTION_CONTRACT
# name: _validate_action_entity
# purpose: Require entity IDs for entity-scoped actions and reject ambiguous
#          project-wide operations from a packet/feature route.
# inputs: action, entity_type, entity_id.
# returns: None.
# side_effects: None.
# error_behavior: Raises ValueError for malformed action/entity combinations.
# END_FUNCTION_CONTRACT
def _validate_action_entity(action: str, entity_type: str, entity_id: str | None) -> None:
    if not isinstance(entity_type, str) or not entity_type or len(entity_type) > 80:
        raise ValueError("ENTITY_INVALID: entity_type is required")
    if action in {"retry", "resume", "cancel", "stop", "merge"} and not entity_id:
        raise ValueError("ENTITY_REQUIRED: packet id is required")
    if action in {"archive", "unarchive"} and not entity_id:
        raise ValueError("ENTITY_REQUIRED: feature id is required")
    if entity_id is not None and (len(str(entity_id)) > 240 or "\x00" in str(entity_id)):
        raise ValueError("ENTITY_INVALID: entity id is not safe")


# START_FUNCTION_CONTRACT
# name: _validate_confirmation
# purpose: Enforce intent for every mutation and typed identity for strong
#          destructive actions.
# inputs: action, project/entity identity and confirmation value.
# returns: None.
# side_effects: None.
# error_behavior: Raises ValueError with stable error code on missing/invalid.
# END_FUNCTION_CONTRACT
def _validate_confirmation(
    action: str,
    project_key: str,
    entity_type: str,
    entity_id: str | None,
    confirmation: Mapping[str, Any] | bool | str | None,
) -> None:
    intent, value = _confirmation_values(confirmation)
    if intent not in {"confirm", "confirmed", "yes", "true", "1"}:
        raise ValueError("CONFIRMATION_REQUIRED: explicit confirmation intent is required")
    if action in _STRONG_ACTIONS or action == "openapi":
        expected = str(entity_id or project_key)
        if value not in {expected, project_key}:
            raise ValueError(
                f"CONFIRMATION_INVALID: type project key or entity id {expected}"
            )


# START_FUNCTION_CONTRACT
# name: _confirmation_values
# purpose: Normalize supported JSON/form confirmation representations.
# inputs: confirmation — bool, string or mapping.
# returns: intent/value pair.
# side_effects: None.
# error_behavior: Malformed values become empty strings.
# END_FUNCTION_CONTRACT
def _confirmation_values(confirmation: Mapping[str, Any] | bool | str | None) -> tuple[str, str]:
    if isinstance(confirmation, Mapping):
        intent = str(confirmation.get("intent") or confirmation.get("token") or confirmation.get("confirm") or "")
        value = str(confirmation.get("value") or confirmation.get("typed") or confirmation.get("project_key") or "")
        return intent.casefold(), value
    if isinstance(confirmation, bool):
        return ("true" if confirmation else ""), ""
    return str(confirmation or "").casefold(), str(confirmation or "")


# START_FUNCTION_CONTRACT
# name: _catalog_actions
# purpose: Return deterministic UI/catalog actions for a selected entity.
# inputs: entity_type — optional selected entity kind.
# returns: Ordered action names.
# side_effects: None.
# error_behavior: Unknown entity receives project-safe actions only.
# END_FUNCTION_CONTRACT
def _catalog_actions(entity_type: str | None) -> tuple[str, ...]:
    kind = str(entity_type or "project").casefold()
    if kind == "packet":
        return ("retry", "cancel", "merge")
    if kind == "feature":
        return ("archive", "unarchive")
    return ("maintenance_snapshot", "cleanup", "restart_api", "restart_workers", "restart_all", "reload")


# START_FUNCTION_CONTRACT
# name: _control_availability
# purpose: Combine advertised capability and current state into one safe row.
# inputs: action, entity kind/state, advertised names and capability result.
# returns: available flag and explicit reason.
# side_effects: None.
# error_behavior: Unknown capability/state fails closed.
# END_FUNCTION_CONTRACT
def _control_availability(
    action: str,
    entity_type: str | None,
    current_state: str,
    advertised: set[str],
    capabilities_ok: bool,
) -> tuple[bool, str | None]:
    if not capabilities_ok or not advertised:
        return False, "Not implemented / unavailable for this runtime"
    aliases = {action, _ACTION_ALIASES.get(action, action)}
    if advertised and not aliases.intersection(advertised) and action not in {"maintenance_snapshot"}:
        return False, "Not implemented / unavailable for this runtime"
    normalized_state = current_state.casefold()
    kind = str(entity_type or "project").casefold()
    if kind == "packet":
        if normalized_state == "unknown":
            return False, "current packet state is unavailable"
        if action in {"retry"} and normalized_state not in {"rejected", "blocked_recoverable"}:
            return False, f"invalid packet state: {normalized_state}"
        if action == "cancel" and normalized_state in _TERMINAL_PACKET_STATES | {"accepted", "blocked"}:
            return False, f"invalid packet state: {normalized_state}"
        if action == "merge" and normalized_state != "accepted":
            return False, f"merge requires ACCEPTED; current state: {normalized_state}"
    if kind == "feature" and normalized_state == "unknown":
        return False, "current feature state is unavailable"
    if kind == "feature" and action == "archive" and normalized_state == "archived":
        return False, "feature is already archived"
    if kind == "feature" and action == "unarchive" and normalized_state != "archived":
        return False, f"feature is not archived; current state: {normalized_state}"
    return True, None


# START_FUNCTION_CONTRACT
# name: _payload_mapping
# purpose: Unwrap common project API data envelopes without trusting arbitrary
#          values as a mutation instruction.
# inputs: payload — optional JSON mapping.
# returns: Mapping or empty mapping.
# side_effects: None.
# error_behavior: Non-mappings return empty mapping.
# END_FUNCTION_CONTRACT
def _payload_mapping(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    data = payload.get("data")
    return data if isinstance(data, Mapping) else payload


# START_FUNCTION_CONTRACT
# name: _bounded_mapping
# purpose: Bound mutation parameter shape and size before transport.
# inputs: optional mapping.
# returns: Shallow bounded mapping with JSON-like values.
# side_effects: None.
# error_behavior: Non-mappings become empty; oversized values are rejected.
# END_FUNCTION_CONTRACT
def _bounded_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > 32:
        raise ValueError("PARAMETERS_INVALID: bounded mapping required")
    result = {str(key)[:120]: item for key, item in value.items()}
    if len(repr(result)) > 64 * 1024:
        raise ValueError("PARAMETERS_INVALID: request is too large")
    return result


# START_FUNCTION_CONTRACT
# name: _request_id
# purpose: Preserve a valid caller ID or generate a unique UUID request ID.
# inputs: optional requested ID.
# returns: bounded unique request string.
# side_effects: None.
# error_behavior: Invalid caller IDs are replaced with a generated UUID.
# END_FUNCTION_CONTRACT
def _request_id(request_id: str | None) -> str:
    value = str(request_id or "")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,120}", value):
        return f"admin-{uuid.uuid4().hex}"
    return value


# START_FUNCTION_CONTRACT
# name: _base_result
# purpose: Build immutable identity fields shared by every mutation result.
# inputs: project/action/entity/request identity.
# returns: Safe base mapping.
# side_effects: None.
# error_behavior: Actor is bounded and masked.
# END_FUNCTION_CONTRACT
def _base_result(
    project_key: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
    request_id: str,
    actor: str,
) -> dict[str, Any]:
    return {
        "project_key": project_key,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "request_id": request_id,
        "actor": mask_operator_data(str(actor or "operator")[:120]),
    }


# START_FUNCTION_CONTRACT
# name: _unknown_result
# purpose: Convert timeout/connection ambiguity into the exact operator state.
# inputs: base result and exception.
# returns: Unknown-outcome mutation DTO with blind retry disabled.
# side_effects: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _unknown_result(base: Mapping[str, Any], error: Exception) -> dict[str, Any]:
    _log.warn("admin_mutation_failed", project_key=str(base.get("project_key")),
              action=str(base.get("action")), reason="unknown_after_timeout")
    return {
        **dict(base),
        "ok": False,
        "result": "unknown_after_timeout",
        "unknown_outcome": True,
        "status": 504,
        "display_message": UNKNOWN_OUTCOME_MESSAGE,
        "error": UNKNOWN_OUTCOME_MESSAGE,
        "error_class": error.__class__.__name__,
        "error_detail": mask_operator_data(str(error)[:240]),
        "retry_allowed": False,
        "attention": True,
    }


# START_FUNCTION_CONTRACT
# name: _is_ambiguous
# purpose: Classify no-response timeout/disconnect errors.
# inputs: error class and message.
# returns: True for transport ambiguity.
# side_effects: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _is_ambiguous(error_class: str, error: Any) -> bool:
    text = f"{error_class} {error or ''}".casefold()
    return any(marker in text for marker in ("timeout", "disconnect", "offline", "network", "connect"))


# START_FUNCTION_CONTRACT
# name: _safe_openapi_path
# purpose: Keep OpenAPI control requests same-origin and path-only before the
#          selected project receives them.
# inputs: path — discovered OpenAPI path candidate.
# returns: True for safe absolute path components.
# side_effects: None.
# error_behavior: Unsafe paths return False.
# END_FUNCTION_CONTRACT
def _safe_openapi_path(path: str) -> bool:
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        return False
    if "\\" in path or "#" in path or ".." in path.split("?")[0].split("/"):
        return False
    try:
        parsed = urlsplit(path)
    except ValueError:
        return False
    return not parsed.scheme and not parsed.netloc and not parsed.fragment


# START_FUNCTION_CONTRACT
# name: _safe_segment
# purpose: Encode an entity ID into a path segment without permitting route
#          traversal or query injection.
# inputs: entity identifier.
# returns: bounded safe segment.
# side_effects: None.
# error_behavior: Invalid values become empty segment.
# END_FUNCTION_CONTRACT
def _safe_segment(value: str) -> str:
    text = str(value or "")
    return re.sub(r"[^A-Za-z0-9_.:-]", "", text)[:240]


# START_FUNCTION_CONTRACT
# name: _int_or_none
# purpose: Convert a status-like value to an integer safely.
# inputs: arbitrary value.
# returns: integer or None.
# side_effects: None.
# error_behavior: Invalid values return None.
# END_FUNCTION_CONTRACT
def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# END_BLOCK_HELPERS
