# ############################################################################
# AI_HEADER: admin_mutation_service — guarded single-project mutation facade
# ROLE: Stable Admin Hub mutation facade. It owns public execution/audit flow
#       while focused owners provide catalog, validation, transport, OpenAPI
#       guards and result normalization without changing mutation policy.
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
#       - _read_entity_state
#       - _call_project
#   - function: normalize_mutation_result
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_security import mask_operator_data
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.services.admin_mutation_catalog import AdminMutationCatalogMixin
from grace_control.services.admin_mutation_openapi import AdminMutationOpenApiMixin
from grace_control.services.admin_mutation_result import (
    UNKNOWN_OUTCOME_MESSAGE,
    _unknown_result,
    normalize_mutation_result,
)
from grace_control.services.admin_mutation_transport import AdminMutationTransportMixin
from grace_control.services.admin_mutation_validation import (
    _READ_ACTIONS,
    _base_result,
    _bounded_mapping,
    _normalize_action,
    _request_id,
    _validate_action_entity,
    _validate_confirmation,
    _validate_project_key,
)

_log = GraceLogger("admin_mutation_service")

_LOCAL_CONTROL_PATH = "/api/admin/control/action"

__all__ = [
    "AdminMutationService",
    "UNKNOWN_OUTCOME_MESSAGE",
    "normalize_mutation_result",
]


# START_BLOCK_SERVICE
class AdminMutationService(
    AdminMutationCatalogMixin,
    AdminMutationOpenApiMixin,
    AdminMutationTransportMixin,
):
    """Stable facade for guarded one-project Admin Hub mutations."""

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


# END_BLOCK_SERVICE
