# ############################################################################
# AI_HEADER: admin_mutation_validation — guarded mutation input helpers
# ROLE: Owns pure validation, confirmation, bounding and identity DTO helpers
#       used by AdminMutationService and its focused mutation owners.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate one-project mutation selectors and bound operator inputs.
# inputs: Action/entity/confirmation values, request IDs and JSON-like mappings.
# returns: Canonical validated values or stable ValueError codes.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Invalid selectors, entities, confirmations or oversized
#                 mappings raise stable ValueError messages.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _validate_project_key
#   - function: _normalize_action
#   - function: _validate_action_entity
#   - function: _validate_confirmation
#   - function: _confirmation_values
#   - function: _bounded_mapping
#   - function: _request_id
#   - function: _base_result
#   - function: _safe_segment
#   - function: _int_or_none
# END_MODULE_MAP

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_security import mask_operator_data

_log = GraceLogger("admin_mutation_validation")

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


# START_BLOCK_VALIDATION
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


# END_BLOCK_VALIDATION
