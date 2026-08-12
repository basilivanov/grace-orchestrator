# ############################################################################
# AI_HEADER: admin_cross_project_service — bounded cross-project observability
# ROLE: Stable thin facade for the Admin Hub cross-project services.
#       It composes one explicit transport with focused overview and query
#       projections while preserving the existing public read surface.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Preserve the Admin Hub cross-project service import, constructor,
#          transport seams and public read DTOs while delegating composition to
#          focused overview and query owners.
# inputs: ProjectRegistry, optional ProjectClient factory and bounded fan-out
#          settings; request filters remain explicit at every method boundary.
# returns: JSON-safe cross-project DTOs with project attribution, coverage and
#          isolated per-project errors.
# side_effects: Performs bounded project-local API requests only; never opens a
#                project database, filesystem, worktree or Git repository.
# emitted_logs: cross_project_fanout_start, cross_project_project_error,
#                cross_project_fanout_done.
# error_behavior: Isolates transport, HTTP, malformed-response and capability
#                 errors; unknown project keys raise KeyError and bad cursors
#                 or regular expressions raise ValueError.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminCrossProjectService
#     methods:
#       - get_projects_overview
#       - query_events
#       - query_logs
#       - search
#       - get_diagnostics
#       - get_attention
#       - transport
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from grace_control.config.project_registry import ProjectContext, ProjectRegistry
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_cross_project_helpers import _RemoteResult
from grace_control.services.admin_cross_project_overview_service import (
    AdminCrossProjectOverviewService,
)
from grace_control.services.admin_cross_project_query_service import AdminCrossProjectQueryService
from grace_control.services.admin_cross_project_transport import CrossProjectTransport

_log = GraceLogger("admin_cross_project_service")


# START_BLOCK_SERVICE
class AdminCrossProjectService:
    """Stable facade composed from explicit transport and read projections."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure the explicit transport and focused read projections
    #          for all cross-project read operations.
    # inputs: registry — immutable ProjectRegistry; client_factory — optional
    #          ProjectClient factory; max_concurrency and transport timeouts.
    # returns: None.
    # side_effects: None; no project request is made during construction.
    # emitted_logs: None.
    # error_behavior: Raises ValueError for non-positive limits.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        registry: ProjectRegistry,
        *,
        client_factory: Callable[[ProjectContext], Any] | None = None,
        max_concurrency: int = 8,
        connect_timeout: float = 1.0,
        read_timeout: float = 3.0,
    ) -> None:
        self._transport = CrossProjectTransport(
            registry,
            client_factory=client_factory,
            max_concurrency=max_concurrency,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )
        self._overview = AdminCrossProjectOverviewService(self._transport)
        self._query = AdminCrossProjectQueryService(self._transport)

    # START_FUNCTION_CONTRACT
    # name: transport
    # purpose: Expose the explicit read transport boundary for architecture
    #          composition and future focused service consumers.
    # inputs: None.
    # returns: Configured CrossProjectTransport.
    # side_effects: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    @property
    def transport(self) -> CrossProjectTransport:
        return self._transport

    # START_FUNCTION_CONTRACT
    # name: get_projects_overview
    # purpose: Delegate project overview projection to the explicit overview
    #          service without changing its public DTO.
    # inputs: project — optional one-or-many explicit project keys.
    # returns: Existing overview DTO.
    # side_effects: Bounded project-local read requests.
    # error_behavior: Preserves overview selection and isolation behavior.
    # END_FUNCTION_CONTRACT
    async def get_projects_overview(
        self,
        project: Sequence[str] | str | None = None,
    ) -> dict[str, Any]:
        return await self._overview.get_projects_overview(project)

    # START_FUNCTION_CONTRACT
    # name: get_diagnostics
    # purpose: Delegate diagnostics projection to the explicit overview
    #          service without changing its public DTO.
    # inputs: project — optional selected project key.
    # returns: Existing diagnostics DTO.
    # side_effects: Bounded project-local read requests.
    # error_behavior: Preserves diagnostics selection and isolation behavior.
    # END_FUNCTION_CONTRACT
    async def get_diagnostics(self, project: str | None = None) -> dict[str, Any]:
        return await self._overview.get_diagnostics(project)

    # START_FUNCTION_CONTRACT
    # name: get_attention
    # purpose: Delegate operator attention projection to the explicit overview
    #          service without changing its public DTO.
    # inputs: project — optional one-or-many explicit project keys.
    # returns: Existing attention DTO.
    # side_effects: Bounded project-local read requests.
    # error_behavior: Preserves attention selection and isolation behavior.
    # END_FUNCTION_CONTRACT
    async def get_attention(
        self,
        project: Sequence[str] | str | None = None,
    ) -> dict[str, Any]:
        return await self._overview.get_attention(project)

    # START_FUNCTION_CONTRACT
    # name: query_events
    # purpose: Delegate event projection to the explicit query service without
    #          changing public filters, cursors or DTOs.
    # inputs: Existing event filters and bounded page controls.
    # returns: Existing event page DTO.
    # side_effects: Bounded project-local event requests.
    # error_behavior: Preserves event validation and isolation behavior.
    # END_FUNCTION_CONTRACT
    async def query_events(
        self,
        *,
        project: Sequence[str] | str | None = None,
        entity_id: str | None = None,
        entity_type: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        text: str | None = None,
        limit: int = 100,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return await self._query.query_events(
            project=project,
            entity_id=entity_id,
            entity_type=entity_type,
            event_type=event_type,
            trace_id=trace_id,
            since=since,
            until=until,
            text=text,
            limit=limit,
            offset=offset,
            cursor=cursor,
        )

    # START_FUNCTION_CONTRACT
    # name: query_logs
    # purpose: Delegate log projection to the explicit query service without
    #          changing public filters, cursors or DTOs.
    # inputs: Existing log filters and bounded tail controls.
    # returns: Existing log page DTO.
    # side_effects: Bounded project-local log requests.
    # error_behavior: Preserves log validation and isolation behavior.
    # END_FUNCTION_CONTRACT
    async def query_logs(
        self,
        *,
        project: Sequence[str] | str | None = None,
        source: str | None = None,
        worker: str | None = None,
        packet: str | None = None,
        run: str | None = None,
        stage: str | None = None,
        level: str | None = None,
        trace_id: str | None = None,
        contains: str | None = None,
        regex: str | None = None,
        since: str | None = None,
        until: str | None = None,
        tail: int = 200,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return await self._query.query_logs(
            project=project,
            source=source,
            worker=worker,
            packet=packet,
            run=run,
            stage=stage,
            level=level,
            trace_id=trace_id,
            contains=contains,
            regex=regex,
            since=since,
            until=until,
            tail=tail,
            cursor=cursor,
        )

    # START_FUNCTION_CONTRACT
    # name: search
    # purpose: Delegate project search projection to the explicit query service
    #          without changing public filters or DTOs.
    # inputs: q — search text; existing project selector and result limit.
    # returns: Existing search DTO.
    # side_effects: Bounded project-local search requests.
    # error_behavior: Preserves search selection and isolation behavior.
    # END_FUNCTION_CONTRACT
    async def search(
        self,
        q: str = "",
        *,
        project: Sequence[str] | str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return await self._query.search(q, project=project, limit=limit)

    # START_FUNCTION_CONTRACT
    # name: _registry
    # purpose: Preserve the existing private registry seam for frozen Wave 2B
    #          compatibility consumers while transport remains the owner.
    # inputs: None.
    # returns: Immutable ProjectRegistry owned by transport.
    # side_effects: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    @property
    def _registry(self) -> ProjectRegistry:
        return self._transport.registry

    # START_FUNCTION_CONTRACT
    # name: _client_factory
    # purpose: Preserve the existing private client-factory seam for frozen
    #          mutation consumers without duplicating transport policy.
    # inputs: None.
    # returns: ProjectClient-compatible factory owned by transport.
    # side_effects: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    @property
    def _client_factory(self) -> Callable[[ProjectContext], Any]:
        return self._transport.client_factory

    # START_FUNCTION_CONTRACT
    # name: _request
    # purpose: Preserve the existing private single-request seam as a direct
    #          transport delegation for frozen compatibility consumers.
    # inputs: context, path, optional params and operation name.
    # returns: Internal isolated _RemoteResult.
    # side_effects: One bounded project-local API request.
    # error_behavior: Preserves transport normalization and isolation behavior.
    # END_FUNCTION_CONTRACT
    async def _request(
        self,
        context: ProjectContext,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        operation: str = "read",
    ) -> _RemoteResult:
        return await self._transport.request(context, path, params, operation=operation)

    # START_FUNCTION_CONTRACT
# END_BLOCK_SERVICE
