# ############################################################################
# AI_HEADER: admin_project_access — explicit project context and read boundary
# ROLE: Owns project context lookup, selected-project reads and the OpenAPI
#       cache for Admin Control Center collaborators.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide the narrow project access boundary used by Control Center
#          focused services.
# inputs: CrossProjectTransport, project keys, API paths and bounded params.
# returns: ProjectContext values and normalized project-read dictionaries.
# side_effects: Performs selected-project API requests through the transport;
#               owns an in-memory OpenAPI result cache.
# emitted_logs: Transport-owned project read logs.
# error_behavior: Unknown project keys raise KeyError; transport failures are
#                 returned in the normalized read dictionary.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminProjectAccess
#     methods:
#       - contexts
#       - context
#       - read
#       - openapi_cache
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from grace_control.config.project_registry import ProjectContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_cross_project_transport import CrossProjectTransport

_log = GraceLogger("admin_project_access")


# START_BLOCK_ACCESS
class AdminProjectAccess:
    """Own explicit project context, read and OpenAPI-cache access."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the access boundary to the shared cross-project transport.
    # inputs: transport — configured CrossProjectTransport; openapi_cache —
    #         optional mutable project-keyed successful-read cache.
    # returns: None.
    # side_effects: Initializes an in-memory cache when one is not supplied.
    # emitted_logs: None.
    # error_behavior: None beyond normal mapping/type errors.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        transport: CrossProjectTransport,
        *,
        openapi_cache: MutableMapping[str, tuple[float, dict[str, Any]]] | None = None,
    ) -> None:
        self._transport = transport
        self._openapi_cache = openapi_cache if openapi_cache is not None else {}

    # START_FUNCTION_CONTRACT
    # name: contexts
    # purpose: Return immutable configured project contexts in registry order.
    # inputs: None.
    # returns: Ordered tuple of ProjectContext values.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def contexts(self) -> tuple[ProjectContext, ...]:
        return self._transport.list_contexts()

    # START_FUNCTION_CONTRACT
    # name: context
    # purpose: Resolve one explicit project context by its registry key.
    # inputs: project_key — configured project key.
    # returns: Matching immutable ProjectContext.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises KeyError for an unknown project key.
    # END_FUNCTION_CONTRACT
    def context(self, project_key: str) -> ProjectContext:
        return self._transport.registry.get(project_key)

    # START_FUNCTION_CONTRACT
    # name: read
    # purpose: Perform one selected-project read and preserve the Control Center
    #          normalized result shape.
    # inputs: project_key, API path, optional params and required operation.
    # returns: Dictionary with ok, payload, error, error_class, http_status and
    #          headers keys.
    # side_effects: One bounded CrossProjectTransport request.
    # emitted_logs: Transport-owned project read logs.
    # error_behavior: Transport failures are normalized and returned.
    # END_FUNCTION_CONTRACT
    async def read(
        self,
        project_key: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        operation: str,
    ) -> dict[str, Any]:
        result = await self._transport.request(
            self.context(project_key),
            path,
            params=params,
            operation=operation,
        )
        return {
            "ok": bool(result.ok),
            "payload": result.payload or {},
            "error": result.error or result.error_class,
            "error_class": result.error_class,
            "http_status": result.http_status,
            "headers": result.headers or {},
        }

    # START_FUNCTION_CONTRACT
    # name: openapi_cache
    # purpose: Expose the project-keyed OpenAPI result cache to the explorer.
    # inputs: None.
    # returns: Mutable cache mapping with existing TTL/value semantics.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    @property
    def openapi_cache(self) -> MutableMapping[str, tuple[float, dict[str, Any]]]:
        return self._openapi_cache


# END_BLOCK_ACCESS
