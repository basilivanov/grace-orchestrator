# ############################################################################
# AI_HEADER: admin_cross_project_service — bounded cross-project observability
# ROLE: Stable compatibility facade for the Admin Hub cross-project services.
#       It owns project selection, bounded fan-out and transport normalization;
#       focused mixins own overview, diagnostics, event, log and search reads.
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
#       - _select_contexts
#       - _fanout
#       - _request
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from grace_control.config.project_registry import ProjectContext, ProjectRegistry
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_cross_project_helpers import (
    _coerce_remote,
    _identity_mismatches,
    _invoke_client,
    _RemoteResult,
    _safe_error_text,
    _selector_values,
    _with_query,
)
from grace_control.services.admin_cross_project_overview_mixin import (
    AdminCrossProjectOverviewMixin,
)
from grace_control.services.admin_cross_project_query_mixin import (
    AdminCrossProjectQueryMixin,
)
from grace_control.services.project_client import ProjectClient

_log = GraceLogger("admin_cross_project_service")


# START_BLOCK_SERVICE
class AdminCrossProjectService(AdminCrossProjectOverviewMixin, AdminCrossProjectQueryMixin):
    """Stable facade for cross-project selection, transport and read models."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure immutable project selection, transport and fan-out
    #          limits for all cross-project read operations.
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
        if max_concurrency <= 0 or connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("cross-project limits must be positive")
        self._registry = registry
        self._max_concurrency = int(max_concurrency)
        self._connect_timeout = float(connect_timeout)
        self._read_timeout = float(read_timeout)
        self._client_factory = client_factory or (
            lambda context: ProjectClient(
                context,
                connect_timeout=self._connect_timeout,
                read_timeout=self._read_timeout,
            )
        )

    # START_FUNCTION_CONTRACT
    # name: get_attention
    # purpose: Return the normalized read-only operator attention model for the
    #          selected projects without changing project/business state.
    # inputs: project — optional one-or-many explicit project keys.
    # returns: Attention items with severity, entity identity, reason, source
    #          timestamp and canonical Hub detail URL.
    # side_effects: Reads overview/diagnostic project APIs.
    # emitted_logs: Same bounded fan-out events as get_projects_overview.
    # error_behavior: Offline and malformed projects become attention/error rows.
    # END_FUNCTION_CONTRACT
    async def get_attention(
        self,
        project: Sequence[str] | str | None = None,
    ) -> dict[str, Any]:
        overview = await self.get_projects_overview(project)
        return {
            "attention": overview["attention"],
            "coverage": overview["coverage"],
            "errors": overview["errors"],
            "fetched_at": overview["fetched_at"],
        }

    # START_FUNCTION_CONTRACT
    # name: _select_contexts
    # purpose: Resolve explicit project selectors while preserving registry
    #          order and excluding disabled projects from default fan-out.
    # inputs: project — None, one key, comma-separated keys or a sequence.
    # returns: Ordered immutable ProjectContext tuple.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises KeyError for an unknown explicit key.
    # END_FUNCTION_CONTRACT
    def _select_contexts(self, project: Sequence[str] | str | None) -> tuple[ProjectContext, ...]:
        if project is None:
            return self._registry.enabled_projects()
        requested = _selector_values(project)
        if not requested or "all" in requested:
            return self._registry.enabled_projects()
        selected = set(requested)
        contexts = tuple(context for context in self._registry.list_projects() if context.key in selected)
        found = {context.key for context in contexts}
        missing = selected - found
        if missing:
            raise KeyError(sorted(missing)[0])
        return contexts

    # START_FUNCTION_CONTRACT
    # name: _fanout
    # purpose: Run one operation for selected contexts with a shared bounded
    #          semaphore and deterministic registry-order results.
    # inputs: contexts, operation and operation label.
    # returns: List of operation results in context order.
    # side_effects: Performs concurrent project-local reads.
    # emitted_logs: cross_project_fanout_start, cross_project_fanout_done.
    # error_behavior: Converts unexpected operation exceptions into a result
    #                  only when the operation itself returns a row; transport
    #                  requests are isolated by _request.
    # END_FUNCTION_CONTRACT
    async def _fanout(
        self,
        contexts: Sequence[ProjectContext],
        operation_fn: Callable[[ProjectContext], Awaitable[Any]],
        *,
        operation: str,
    ) -> list[Any]:
        _log.info("cross_project_fanout_start", operation=operation, project_count=len(contexts))
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def run(context: ProjectContext) -> Any:
            if not context.enabled:
                return await operation_fn(context)
            async with semaphore:
                return await operation_fn(context)

        results = await asyncio.gather(*(run(context) for context in contexts))
        _log.info("cross_project_fanout_done", operation=operation, project_count=len(results))
        return list(results)

    # START_FUNCTION_CONTRACT
    # name: _request
    # purpose: Call one project-local API path through ProjectClient or a
    #          compatible test client and normalize its response.
    # inputs: context, path, optional query params and operation name.
    # returns: Internal isolated _RemoteResult.
    # side_effects: One bounded project-local API request.
    # emitted_logs: cross_project_project_error on failures.
    # error_behavior: Never raises transport/JSON errors; returns typed failure.
    # END_FUNCTION_CONTRACT
    async def _request(
        self,
        context: ProjectContext,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        operation: str = "read",
    ) -> _RemoteResult:
        if not context.enabled:
            return _RemoteResult(context, False, error_class="disabled", error="project is disabled")
        try:
            client = self._client_factory(context)
            query_path = _with_query(path, params)
            raw = await _invoke_client(client, path, query_path, params or {}, operation)
            result = _coerce_remote(context, raw)
            if operation == "health" and result.ok and result.payload:
                mismatches = _identity_mismatches(context, result.payload)
                if mismatches:
                    result = _RemoteResult(
                        context,
                        False,
                        result.payload,
                        "identity_mismatch",
                        "; ".join(mismatches),
                        result.http_status,
                        result.headers,
                    )
            if result.http_status == 404 and operation in {"logs", "search"} and not result.ok:
                return _RemoteResult(
                    context,
                    False,
                    error_class="capability_unavailable",
                    error="project capability is unavailable",
                    http_status=404,
                )
            if not result.ok:
                _log.error(
                    "cross_project_project_error",
                    project_key=context.key,
                    operation=operation,
                    error_class=result.error_class or "project_error",
                )
            return result
        except Exception as exc:
            _log.error(
                "cross_project_project_error",
                project_key=context.key,
                operation=operation,
                error_class="client_error",
            )
            return _RemoteResult(
                context,
                False,
                error_class="client_error",
                error=_safe_error_text(exc),
            )


# END_BLOCK_SERVICE
