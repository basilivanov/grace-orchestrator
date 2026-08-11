# ############################################################################
# AI_HEADER: admin_mutation_openapi — discovered OpenAPI mutation guard
# ROLE: Owns safe-path, discovery, parameter and confirmation gates for one
#       selected project's local OpenAPI control endpoint.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute exactly one discovered selected-project OpenAPI mutation.
# inputs: Project key, discovered path/method, bounded parameters/body,
#          confirmation and request identity.
# returns: Stable normalized mutation DTO.
# side_effects: At most one local OpenAPI control mutation after read discovery.
# emitted_logs: Mutation completion/failure logs through the facade.
# error_behavior: Unsafe, undiscovered or unconfirmed operations fail before
#                 mutation transport.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminMutationOpenApiMixin
#     methods:
#       - execute_openapi
#   - function: _safe_openapi_path
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_explorer_helpers import (
    _openapi_operations,
    _openapi_request,
)
from grace_control.services.admin_control_security import mask_operator_data
from grace_control.services.admin_mutation_catalog import _payload_mapping
from grace_control.services.admin_mutation_result import (
    _unknown_result,
    normalize_mutation_result,
)
from grace_control.services.admin_mutation_validation import (
    _base_result,
    _bounded_mapping,
    _request_id,
    _validate_confirmation,
    _validate_project_key,
)

_log = GraceLogger("admin_mutation_openapi")

_LOCAL_OPENAPI_PATH = "/api/admin/control/openapi"
_DANGEROUS_OPENAPI_PREFIXES = (
    "/api/admin/control",
    "/api/admin/lifecycle",
    "/api/packets/claim",
    "/api/admin/shutdown",
)


# START_BLOCK_OPENAPI
class AdminMutationOpenApiMixin:
    """Guarded discovered OpenAPI mutation composition."""

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
        bounded_parameters = _bounded_mapping(parameters)
        _request_path, _query_parameters, parameter_error = _openapi_request(
            path,
            discovered,
            bounded_parameters,
        )
        if parameter_error:
            return {**base, "ok": False, "result": "failed", "status": 400,
                    "error_code": parameter_error, "retry_allowed": False}
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
            "parameters": bounded_parameters,
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


# END_BLOCK_OPENAPI


# START_BLOCK_HELPERS
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


# END_BLOCK_HELPERS
