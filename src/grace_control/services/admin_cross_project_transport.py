# ############################################################################
# AI_HEADER: admin_cross_project_transport — explicit cross-project read transport
# ROLE: Owns project selection, bounded fan-out and project-local request
#       normalization for the Admin Hub read services.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide the single explicit transport boundary for cross-project
#          Admin Hub reads.
# inputs: Immutable ProjectRegistry, optional ProjectClient factory, bounded
#          concurrency and connect/read timeout policies.
# returns: Ordered ProjectContext selections, isolated _RemoteResult values and
#          ordered operation fan-out results.
# side_effects: Performs bounded project-local API requests only; never opens a
#                project database, filesystem, worktree or Git repository.
# emitted_logs: cross_project_fanout_start, cross_project_project_error,
#                cross_project_fanout_done.
# error_behavior: Unknown explicit project keys raise KeyError; transport,
#                 HTTP, malformed-response and capability errors are normalized
#                 into isolated _RemoteResult values.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: CrossProjectTransport
#     methods:
#       - list_contexts
#       - select_contexts
#       - fanout
#       - request
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
from grace_control.services.project_client import ProjectClient

_log = GraceLogger("admin_cross_project_transport")


# START_BLOCK_TRANSPORT
class CrossProjectTransport:
    """Explicit project selection, fan-out and request transport boundary."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure the immutable registry reference and bounded project-
    #          local client policy used by all composed read services.
    # inputs: registry — immutable ProjectRegistry; client_factory — optional
    #          ProjectClient factory; positive concurrency and timeout values.
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
    # name: registry
    # purpose: Expose the immutable registry reference to frozen compatibility
    #          consumers without moving selection ownership out of transport.
    # inputs: None.
    # returns: Configured ProjectRegistry.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    @property
    def registry(self) -> ProjectRegistry:
        return self._registry

    # START_FUNCTION_CONTRACT
    # name: client_factory
    # purpose: Expose the configured project-local client factory to frozen
    #          mutation compatibility consumers.
    # inputs: None.
    # returns: ProjectClient-compatible factory.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    @property
    def client_factory(self) -> Callable[[ProjectContext], Any]:
        return self._client_factory

    # START_FUNCTION_CONTRACT
    # name: list_contexts
    # purpose: Return all registry contexts in their configured deterministic
    #          order, including disabled projects for overview cards.
    # inputs: None.
    # returns: Ordered immutable ProjectContext tuple.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def list_contexts(self) -> tuple[ProjectContext, ...]:
        return self._registry.list_projects()

    # START_FUNCTION_CONTRACT
    # name: select_contexts
    # purpose: Resolve explicit project selectors while preserving registry
    #          order and excluding disabled projects from default fan-out.
    # inputs: project — None, one key, comma-separated keys or a sequence.
    # returns: Ordered immutable enabled ProjectContext tuple.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises KeyError for an unknown explicit key.
    # END_FUNCTION_CONTRACT
    def select_contexts(
        self,
        project: Sequence[str] | str | None,
    ) -> tuple[ProjectContext, ...]:
        if project is None:
            return self._registry.enabled_projects()
        requested = _selector_values(project)
        if not requested or "all" in requested:
            return self._registry.enabled_projects()
        selected = set(requested)
        contexts = tuple(
            context
            for context in self._registry.list_projects()
            if context.key in selected
        )
        found = {context.key for context in contexts}
        missing = selected - found
        if missing:
            raise KeyError(sorted(missing)[0])
        return contexts

    # START_FUNCTION_CONTRACT
    # name: fanout
    # purpose: Run one operation for selected contexts with a shared bounded
    #          semaphore and deterministic registry-order results.
    # inputs: contexts, operation function and operation label.
    # returns: List of operation results in context order.
    # side_effects: Performs concurrent project-local reads.
    # emitted_logs: cross_project_fanout_start, cross_project_fanout_done.
    # error_behavior: Propagates operation-level projection errors exactly as
    #                  the previous service fan-out did; request failures are
    #                  isolated by request.
    # END_FUNCTION_CONTRACT
    async def fanout(
        self,
        contexts: Sequence[ProjectContext],
        operation_fn: Callable[[ProjectContext], Awaitable[Any]],
        *,
        operation: str,
    ) -> list[Any]:
        _log.info(
            "cross_project_fanout_start",
            operation=operation,
            project_count=len(contexts),
        )
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def run(context: ProjectContext) -> Any:
            if not context.enabled:
                return await operation_fn(context)
            async with semaphore:
                return await operation_fn(context)

        results = await asyncio.gather(*(run(context) for context in contexts))
        _log.info(
            "cross_project_fanout_done",
            operation=operation,
            project_count=len(results),
        )
        return list(results)

    # START_FUNCTION_CONTRACT
    # name: request
    # purpose: Call one project-local API path through ProjectClient or a
    #          compatible test client and normalize its response.
    # inputs: context, path, optional query params and operation name.
    # returns: Internal isolated _RemoteResult.
    # side_effects: One bounded project-local API request.
    # emitted_logs: cross_project_project_error on failures.
    # error_behavior: Never raises transport/JSON errors; returns typed failure.
    # END_FUNCTION_CONTRACT
    async def request(
        self,
        context: ProjectContext,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        operation: str = "read",
    ) -> _RemoteResult:
        if not context.enabled:
            return _RemoteResult(
                context,
                False,
                error_class="disabled",
                error="project is disabled",
            )
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


# END_BLOCK_TRANSPORT
