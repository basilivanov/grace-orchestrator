# ############################################################################
# AI_HEADER: admin_mutation_catalog — capability and state-aware controls
# ROLE: Owns the read-only mutation catalog for one selected project. It uses
#       the accepted Hub registry/request seams and never dispatches a write.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build fail-closed control catalogs and read selected entity state.
# inputs: AdminMutationService-compatible Hub facade, project and entity values.
# returns: JSON-safe capability/state-aware control rows or lowercase state.
# side_effects: Performs bounded project-local capability/entity reads only.
# emitted_logs: Hub read logs through the existing cross-project service.
# error_behavior: Unknown project raises KeyError; unavailable reads become
#                 explicit unavailable states.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminMutationCatalogMixin
#     methods:
#       - available_controls
#       - _read_entity_state
#   - function: _catalog_actions
#   - function: _control_availability
#   - function: _payload_mapping
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_security import mask_operator_data
from grace_control.services.admin_mutation_validation import (
    _ACTION_ALIASES,
    _STRONG_ACTIONS,
    _safe_segment,
    _validate_project_key,
)

_log = GraceLogger("admin_mutation_catalog")

_TERMINAL_PACKET_STATES = frozenset({
    "accepted", "merged", "failed", "cancelled", "blocked_final",
})


# START_BLOCK_CATALOG
class AdminMutationCatalogMixin:
    """Capability/state reads for the mutation facade."""

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


# END_BLOCK_CATALOG


# START_BLOCK_HELPERS
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


# END_BLOCK_HELPERS
