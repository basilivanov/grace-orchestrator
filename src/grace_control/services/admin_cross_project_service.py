# ############################################################################
# AI_HEADER: admin_cross_project_service — bounded cross-project observability
# ROLE: Composes project-local Admin APIs for the central Admin Hub. It owns
#       project selection, bounded concurrent fan-out, normalization, ordering,
#       coverage and attention classification; routers only bind HTTP inputs.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build safe Hub-level overview, event, log, search and diagnostics
#          read models from immutable ProjectContext values.
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
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from grace_control.config.project_registry import ProjectContext, ProjectRegistry
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_cross_project_helpers import (
    _aggregate_snapshots,
    _attention_for_project,
    _attention_for_snapshot,
    _bounded_limit,
    _bounded_offset,
    _coerce_remote,
    _compact,
    _coverage,
    _coverage_from_results,
    _data_mapping,
    _decode_cursor,
    _encode_cursor,
    _error_dto,
    _event_row,
    _event_sort_key,
    _health_status,
    _identity_mismatches,
    _invoke_client,
    _log_matches,
    _log_row,
    _log_sort_key,
    _malformed_error,
    _matches_project,
    _now_iso,
    _project_search_row,
    _project_url,
    _RemoteResult,
    _safe_error_text,
    _safe_int,
    _safe_json,
    _search_row,
    _selector_values,
    _sizes,
    _sort_attention,
    _value,
    _with_query,
)
from grace_control.services.project_client import ProjectClient

_log = GraceLogger("admin_cross_project_service")

_MAX_EVENTS_PER_PROJECT = 1000
_MAX_LOG_LINES_PER_PROJECT = 5000
_EVENT_FILTER_NAMES = (
    "entity_id",
    "entity_type",
    "event_type",
    "trace_id",
    "since",
    "until",
)


# START_BLOCK_SERVICE
class AdminCrossProjectService:
    """Service-layer composition for cross-project observability."""

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
    # name: get_projects_overview
    # purpose: Return project cards, mathematically scoped aggregate counts,
    #          coverage metadata and normalized operator attention items.
    # inputs: project — optional one-or-many explicit registry keys; omitted
    #          means enabled projects only.
    # returns: Hub overview DTO with projects, aggregates, coverage, errors and
    #          attention.
    # side_effects: Concurrently reads health, diagnostics and latest event
    #                data through selected project-local APIs.
    # emitted_logs: cross_project_fanout_start, cross_project_project_error,
    #                cross_project_fanout_done.
    # error_behavior: Offline/partial projects remain attributed rows; unknown
    #                 project keys raise KeyError.
    # END_FUNCTION_CONTRACT
    async def get_projects_overview(
        self,
        project: Sequence[str] | str | None = None,
    ) -> dict[str, Any]:
        contexts = self._select_contexts(project)

        async def collect(context: ProjectContext) -> dict[str, Any]:
            if not context.enabled:
                return self._overview_for_disabled(context)
            health, diagnostics, events = await asyncio.gather(
                self._request(context, "/api/admin/system/health", operation="health"),
                self._request(context, "/api/diagnostics/state"),
                self._request(context, "/api/events", {"limit": 1, "offset": 0}),
            )
            return self._overview_for_context(context, health, diagnostics, events)

        rows = await self._fanout(contexts, collect, operation="overview")
        projects = [row["project"] for row in rows]
        errors = [error for row in rows for error in row["errors"]]
        attention = [item for row in rows for item in row["attention"]]
        snapshots = [row["diagnostics"] for row in rows if row["diagnostics"] is not None]
        coverage = _coverage(rows, len(contexts))
        aggregate = _aggregate_snapshots(snapshots)
        aggregate["complete"] = coverage["projects_failed"] == 0 and coverage["partial"] == 0
        return {
            "projects": projects,
            "aggregate": aggregate,
            "aggregates": aggregate,
            "coverage": coverage,
            "errors": errors,
            "attention": _sort_attention(attention),
            "fetched_at": _now_iso(),
        }

    # START_FUNCTION_CONTRACT
    # name: query_events
    # purpose: Query canonical project-local events, merge them by original
    #          timestamp and expose explicit bounded continuation semantics.
    # inputs: Canonical event filters; project — optional selected keys; limit,
    #          offset and cursor — bounded global page controls.
    # returns: Hub event page with full safe payloads, coverage, errors and a
    #          bounded_offset continuation document.
    # side_effects: Concurrently requests /api/events from selected projects.
    # emitted_logs: cross_project_fanout_start, cross_project_project_error,
    #                cross_project_fanout_done.
    # error_behavior: Per-project failures are returned in errors; malformed
    #                 cursors raise ValueError.
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
        limit: int = 100,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        page_limit = _bounded_limit(limit, 200)
        page_offset = _bounded_offset(offset)
        contexts = self._select_contexts(project)
        filters = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "event_type": event_type,
            "trace_id": trace_id,
            "since": since,
            "until": until,
        }
        cursor_data = _decode_cursor(cursor)
        if cursor_data is not None:
            expected_projects = [context.key for context in contexts]
            if cursor_data.get("projects") != expected_projects:
                raise ValueError("event cursor project selection does not match request")
            if cursor_data.get("filters") != _compact(filters):
                raise ValueError("event cursor filters do not match request")
            page_offset = _bounded_offset(cursor_data.get("offset", 0))
        fetch_limit = min(_MAX_EVENTS_PER_PROJECT, max(page_limit, page_offset + page_limit))
        params = {**filters, "limit": fetch_limit, "offset": 0}

        async def query(context: ProjectContext) -> _RemoteResult:
            return await self._request(context, "/api/events", params)

        results = await self._fanout(contexts, query, operation="events")
        merged: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        totals: list[int] = []
        partial = False
        for result in results:
            if not result.ok:
                errors.append(_error_dto(result, "/api/events"))
                continue
            data = _data_mapping(result.payload)
            raw_events = data.get("events")
            if not isinstance(raw_events, list):
                errors.append(_malformed_error(result.context, "/api/events", "events list is missing"))
                continue
            total = _safe_int(data.get("total"), len(raw_events))
            totals.append(total)
            if total > fetch_limit:
                partial = True
            for event in raw_events:
                if isinstance(event, Mapping):
                    merged.append(_event_row(result.context, event))
        merged.sort(key=_event_sort_key, reverse=True)
        page = merged[page_offset:page_offset + page_limit]
        coverage = {
            "projects_total": len(contexts),
            "projects_responded": len(results) - len(errors),
            "projects_failed": len(errors),
        }
        if errors:
            partial = True
        known_total = sum(totals) if totals else 0
        bounded_total = min(known_total, _MAX_EVENTS_PER_PROJECT)
        if errors:
            has_more = page_offset + page_limit < _MAX_EVENTS_PER_PROJECT and (
                len(merged) > page_offset + page_limit or partial
            )
        else:
            has_more = page_offset + page_limit < bounded_total
        next_offset = page_offset + page_limit if has_more else None
        next_cursor = None
        if next_offset is not None:
            next_cursor = _encode_cursor({
                "version": 1,
                "strategy": "bounded_offset",
                "offset": next_offset,
                "projects": [context.key for context in contexts],
                "filters": _compact(filters),
            })
        return {
            "events": page,
            "total": known_total if not errors else None,
            "known_total": known_total,
            "limit": page_limit,
            "offset": page_offset,
            "partial": partial,
            "coverage": coverage,
            "errors": errors,
            "continuation": {
                "strategy": "bounded_offset",
                "description": (
                    "Each selected project contributes a prefix of offset+limit events; "
                    "use next_cursor while partial is true."
                ),
                "next_offset": next_offset,
                "next_cursor": next_cursor,
            },
            "next_cursor": next_cursor,
            "fetched_at": _now_iso(),
        }

    # START_FUNCTION_CONTRACT
    # name: query_logs
    # purpose: Read project-local bounded system logs and normalize heterogeneous
    #          line shapes into one project-attributed Hub row model.
    # inputs: Log source/entity/time/text filters; project — selected keys;
    #          tail and cursor — bounded global window controls.
    # returns: Normalized log rows with coverage, errors and continuation data.
    # side_effects: Concurrently requests project-local bounded log APIs.
    # emitted_logs: cross_project_fanout_start, cross_project_project_error,
    #                cross_project_fanout_done.
    # error_behavior: One malformed project response becomes an isolated error;
    #                 invalid regex/cursor raises ValueError.
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
        page_limit = _bounded_limit(tail, 500)
        page_offset = _bounded_offset(0)
        expression = re.compile(regex) if regex else None
        contexts = self._select_contexts(project)
        filters = {
            "source": source,
            "worker": worker,
            "packet": packet,
            "run": run,
            "stage": stage,
            "level": level,
            "trace_id": trace_id,
            "contains": contains,
            "regex": regex,
            "since": since,
            "until": until,
        }
        cursor_data = _decode_cursor(cursor)
        if cursor_data is not None:
            if cursor_data.get("strategy") != "bounded_tail":
                raise ValueError("log cursor strategy is invalid")
            if cursor_data.get("projects") != [context.key for context in contexts]:
                raise ValueError("log cursor project selection does not match request")
            if cursor_data.get("filters") != _compact(filters):
                raise ValueError("log cursor filters do not match request")
            page_offset = _bounded_offset(cursor_data.get("offset", 0))
        fetch_tail = min(_MAX_LOG_LINES_PER_PROJECT, max(page_limit, page_offset + page_limit))

        async def query(context: ProjectContext) -> _RemoteResult:
            return await self._request(
                context,
                "/api/admin/system/logs",
                {"tail": fetch_tail},
                operation="logs",
            )

        results = await self._fanout(contexts, query, operation="logs")
        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        partial = False
        for result in results:
            if not result.ok:
                errors.append(_error_dto(result, "/api/admin/system/logs"))
                continue
            data = _data_mapping(result.payload)
            lines = data.get("lines", data.get("logs"))
            if not isinstance(lines, list):
                errors.append(_malformed_error(result.context, "/api/admin/system/logs", "lines list is missing"))
                continue
            source_total = _safe_int(data.get("total"), len(lines))
            if bool(data.get("truncated")) or source_total > fetch_tail:
                partial = True
            for line in lines:
                row = _log_row(result.context, line, data.get("source"))
                if _log_matches(row, source, worker, packet, run, stage, level, trace_id,
                                contains, expression, since, until):
                    rows.append(row)
        rows.sort(key=_log_sort_key, reverse=True)
        page = rows[page_offset:page_offset + page_limit]
        if errors:
            partial = True
        next_offset = None
        if page_offset + page_limit < _MAX_LOG_LINES_PER_PROJECT and (
            len(rows) > page_offset + page_limit or partial
        ):
            next_offset = page_offset + page_limit
        next_cursor = None
        if next_offset is not None:
            next_cursor = _encode_cursor({
                "version": 1,
                "strategy": "bounded_tail",
                "offset": next_offset,
                "projects": [context.key for context in contexts],
                "filters": _compact(filters),
            })
        coverage = _coverage_from_results(results, len(contexts))
        coverage["partial"] = partial
        return {
            "logs": page,
            "total": len(rows) if not partial else None,
            "limit": page_limit,
            "offset": page_offset,
            "partial": partial,
            "coverage": coverage,
            "errors": errors,
            "continuation": {
                "strategy": "bounded_tail",
                "description": "Rows are merged from each project's bounded system-log tail.",
                "next_cursor": next_cursor,
            },
            "next_cursor": next_cursor,
            "fetched_at": _now_iso(),
        }

    # START_FUNCTION_CONTRACT
    # name: search
    # purpose: Search canonical project-local Admin search results and project
    #          metadata, adding project-aware Hub targets.
    # inputs: q — search text; project — optional selected keys; limit — global
    #          result cap.
    # returns: Normalized project/feature/wave/packet/run/stage/worker/event
    #          results with canonical target URLs and isolated errors.
    # side_effects: Concurrently requests /api/admin/search from selected APIs.
    # emitted_logs: cross_project_fanout_start, cross_project_project_error,
    #                cross_project_fanout_done.
    # error_behavior: Failed projects appear in errors while healthy results
    #                 remain available; unknown keys raise KeyError.
    # END_FUNCTION_CONTRACT
    async def search(
        self,
        q: str = "",
        *,
        project: Sequence[str] | str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        result_limit = _bounded_limit(limit, 200)
        contexts = self._select_contexts(project)

        async def query(context: ProjectContext) -> _RemoteResult:
            return await self._request(context, "/api/admin/search", {"q": q, "limit": result_limit}, operation="search")

        results = await self._fanout(contexts, query, operation="search")
        normalized: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for result in results:
            if not result.ok:
                errors.append(_error_dto(result, "/api/admin/search"))
                continue
            data = _data_mapping(result.payload)
            raw_results = data.get("results", [])
            if not isinstance(raw_results, list):
                errors.append(_malformed_error(result.context, "/api/admin/search", "results list is missing"))
                continue
            for item in raw_results:
                if isinstance(item, Mapping):
                    normalized.append(_search_row(result.context, item))
            if _matches_project(q, result.context):
                normalized.append(_project_search_row(result.context))
        normalized.sort(key=lambda item: (
            str(item.get("project_key", "")),
            str(item.get("kind", "")),
            str(item.get("id", "")),
            str(item.get("title", "")),
        ))
        return {
            "q": q,
            "results": normalized[:result_limit],
            "coverage": _coverage_from_results(results, len(contexts)),
            "errors": errors,
            "fetched_at": _now_iso(),
        }

    # START_FUNCTION_CONTRACT
    # name: get_diagnostics
    # purpose: Return per-project Stage 02 diagnostic snapshots and aggregate
    #          counts only with explicit response coverage.
    # inputs: project — optional one project key; omitted means enabled projects.
    # returns: One project snapshot or a global snapshots/aggregates DTO.
    # side_effects: Concurrently requests /api/diagnostics/state and the
    #                project-local system-health endpoint.
    # emitted_logs: cross_project_fanout_start, cross_project_project_error,
    #                cross_project_fanout_done.
    # error_behavior: Isolates unavailable, malformed and partial project data;
    #                 unknown project keys raise KeyError.
    # END_FUNCTION_CONTRACT
    async def get_diagnostics(self, project: str | None = None) -> dict[str, Any]:
        contexts = self._select_contexts(project)

        async def query(context: ProjectContext) -> tuple[_RemoteResult, _RemoteResult]:
            diagnostics, health = await asyncio.gather(
                self._request(context, "/api/diagnostics/state", operation="diagnostics"),
                self._request(context, "/api/admin/system/health", operation="health"),
            )
            return diagnostics, health

        results = await self._fanout(contexts, query, operation="diagnostics")
        snapshots: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        coverage_rows: list[dict[str, bool]] = []
        project_errors: dict[str, list[dict[str, Any]]] = {}
        for diagnostics_result, health_result in results:
            current_errors = [
                _error_dto(result, endpoint)
                for result, endpoint in (
                    (diagnostics_result, "/api/diagnostics/state"),
                    (health_result, "/api/admin/system/health"),
                )
                if not result.ok
            ]
            errors.extend(current_errors)
            project_errors[diagnostics_result.context.key] = current_errors
            coverage_rows.append({
                "responded": diagnostics_result.ok or health_result.ok,
                "partial": bool(current_errors),
            })
            snapshot = _safe_json(_data_mapping(diagnostics_result.payload)) if diagnostics_result.ok else {}
            if health_result.ok:
                snapshot["system_health"] = _safe_json(_data_mapping(health_result.payload))
            if not snapshot:
                continue
            snapshot.update({
                "project_key": diagnostics_result.context.key,
                "project_name": diagnostics_result.context.name,
            })
            snapshots.append(snapshot)
        coverage = _coverage(coverage_rows, len(contexts))
        attention = _sort_attention(
            [item for snapshot in snapshots for item in _attention_for_snapshot(snapshot)]
        )
        selected_values = _selector_values(project) if project is not None else []
        if project is not None and len(contexts) == 1 and selected_values != ["all"]:
            diagnostics_result, _ = results[0]
            snapshot = snapshots[0] if snapshots else None
            return {
                "project_key": diagnostics_result.context.key,
                "project_name": diagnostics_result.context.name,
                "snapshot": snapshot,
                "data": snapshot,
                "error": (project_errors.get(diagnostics_result.context.key) or [None])[0],
                "attention": attention,
                "coverage": coverage,
                "fetched_at": _now_iso(),
            }
        aggregate = _aggregate_snapshots(snapshots)
        aggregate["complete"] = not errors and coverage["projects_failed"] == 0
        return {
            "projects": snapshots,
            "snapshots": snapshots,
            "aggregate": aggregate,
            "aggregates": aggregate,
            "coverage": coverage,
            "errors": errors,
            "attention": attention,
            "fetched_at": _now_iso(),
        }

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

    # START_FUNCTION_CONTRACT
    # name: _overview_for_context
    # purpose: Normalize one project's health/diagnostic/latest-event responses
    #          without replacing missing data with healthy zeroes.
    # inputs: Context and three isolated remote results.
    # returns: Internal row containing project card, snapshot, errors and
    #          attention items.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Preserves partial response errors in the row.
    # END_FUNCTION_CONTRACT
    def _overview_for_context(
        self,
        context: ProjectContext,
        health: _RemoteResult,
        diagnostics: _RemoteResult,
        events: _RemoteResult,
    ) -> dict[str, Any]:
        errors = [
            _error_dto(result, endpoint)
            for result, endpoint in (
                (health, "/api/admin/system/health"),
                (diagnostics, "/api/diagnostics/state"),
                (events, "/api/events"),
            )
            if not result.ok
        ]
        runtime = _safe_json(health.payload) if health.ok and health.payload else None
        snapshot = _safe_json(_data_mapping(diagnostics.payload)) if diagnostics.ok else None
        event_data = _data_mapping(events.payload) if events.ok else {}
        event_rows = event_data.get("events", [])
        latest_event = _event_row(context, event_rows[0]) if event_rows and isinstance(event_rows[0], Mapping) else None
        health_status = _health_status(health, runtime)
        attention = _attention_for_project(context, health_status, runtime, snapshot, latest_event, errors)
        card = {
            "project_key": context.key,
            "project_name": context.name,
            "key": context.key,
            "name": context.name,
            "enabled": context.enabled,
            "status": health_status,
            "runtime": runtime,
            "version": _value(runtime, "version"),
            "code_sha": _value(runtime, "code_sha"),
            "target_head": _value(runtime, "target_head"),
            "workers": _value(snapshot, "workers"),
            "packets_by_state": _value(snapshot, "packets_by_state"),
            "active_ordinary_leases": _value(snapshot, "ordinary_leases"),
            "active_parallel_leases": _value(snapshot, "active_parallel_leases"),
            "merge_lease": _value(snapshot, "active_merge_lease_holder"),
            "latest_event": latest_event,
            "latest_attention": attention[0] if attention else None,
            "sizes": _sizes(runtime),
            "error": errors[0] if errors else None,
            "partial": bool(errors),
            "fetched_at": _now_iso(),
        }
        return {
            "project": card,
            "diagnostics": snapshot,
            "errors": errors,
            "attention": attention,
            "responded": health.ok or diagnostics.ok or events.ok,
            "partial": bool(errors),
        }

    # START_FUNCTION_CONTRACT
    # name: _overview_for_disabled
    # purpose: Build an explicit disabled project card without performing a
    #          remote request or presenting disabled data as healthy zeroes.
    # inputs: Disabled ProjectContext.
    # returns: Internal overview row.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _overview_for_disabled(self, context: ProjectContext) -> dict[str, Any]:
        item = {
            "severity": "info",
            "project_key": context.key,
            "project_name": context.name,
            "kind": "disabled",
            "entity_type": "project",
            "entity_id": context.key,
            "title": "Project is disabled",
            "reason": "registry entry is disabled",
            "timestamp": None,
            "detail_url": _project_url(context.key),
        }
        return {
            "project": {
                "project_key": context.key,
                "project_name": context.name,
                "key": context.key,
                "name": context.name,
                "enabled": False,
                "status": "disabled",
                "runtime": None,
                "version": None,
                "code_sha": None,
                "target_head": None,
                "workers": None,
                "packets_by_state": None,
                "active_ordinary_leases": None,
                "active_parallel_leases": None,
                "merge_lease": None,
                "latest_event": None,
                "latest_attention": item,
                "sizes": None,
                "error": None,
                "partial": False,
                "fetched_at": _now_iso(),
            },
            "diagnostics": None,
            "errors": [],
            "attention": [item],
            "responded": False,
            "partial": False,
        }


# END_BLOCK_SERVICE
