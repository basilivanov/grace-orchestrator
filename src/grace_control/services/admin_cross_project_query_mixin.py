# ############################################################################
# AI_HEADER: admin_cross_project_query_mixin — cross-project query composition
# ROLE: Owns event, log and search read-model composition for the Admin Hub.
#       It delegates project selection, bounded fan-out and transport to the
#       compatibility facade so callers and tests retain the same seams.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Query project-local events, logs and search endpoints and merge their
#          bounded results into project-attributed Hub DTOs.
# inputs: ProjectContext values, query filters and facade-provided selection,
#          fan-out and request methods.
# returns: JSON-safe event, log and search pages with ordering, cursors,
#          coverage and isolated errors.
# side_effects: Performs bounded project-local read requests through the facade
#                transport seam.
# emitted_logs: cross_project_fanout_start, cross_project_project_error,
#                cross_project_fanout_done.
# error_behavior: Isolates project failures and malformed responses; invalid
#                 cursors or regular expressions raise ValueError.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminCrossProjectQueryMixin
#     methods:
#       - query_events
#       - query_logs
#       - search
# END_MODULE_MAP

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from grace_control.config.project_registry import ProjectContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_explorer_helpers import _event_matches_text
from grace_control.services.admin_cross_project_helpers import (
    _bounded_limit,
    _bounded_offset,
    _compact,
    _coverage_from_results,
    _data_mapping,
    _decode_cursor,
    _encode_cursor,
    _error_dto,
    _event_row,
    _event_sort_key,
    _log_matches,
    _log_row,
    _log_sort_key,
    _malformed_error,
    _matches_project,
    _now_iso,
    _project_search_row,
    _RemoteResult,
    _safe_int,
    _search_row,
)

_log = GraceLogger("admin_cross_project_query")

_MAX_EVENTS_PER_PROJECT = 1000
_MAX_LOG_LINES_PER_PROJECT = 5000
_RUN_LOG_STREAMS = {
    "stdout": "stdout",
    "packet_stdout": "stdout",
    "stderr": "stderr",
    "packet_stderr": "stderr",
    "agent": "agent",
}
_STAGE_LOG_STREAMS = {
    "stdout": "stdout",
    "stage_stdout": "stdout",
    "stderr": "stderr",
    "stage_stderr": "stderr",
}
_AGGREGATED_LOG_SOURCES = {
    "api": "server",
    "worker": "worker_stdout,worker_stderr",
    "supervisor": "supervisor",
    "structured": "db_events",
    "packet_stdout": "worker_stdout",
    "packet_stderr": "worker_stderr",
    "agent": "agent",
    "acceptance": "db_events",
    "browser": "agent",
    "visual": "agent",
    "merge": "db_events",
    "recheck": "db_events",
    "recovery": "recovery",
}


# START_BLOCK_SERVICE
class AdminCrossProjectQueryMixin:
    """Event, log and search composition for the cross-project facade."""

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
        text: str | None = None,
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
            "text": text,
        }
        cursor_data = _decode_cursor(cursor)
        if cursor_data is not None:
            expected_projects = [context.key for context in contexts]
            if cursor_data.get("projects") != expected_projects:
                raise ValueError("event cursor project selection does not match request")
            if cursor_data.get("filters") != _compact(filters):
                raise ValueError("event cursor filters do not match request")
            page_offset = _bounded_offset(cursor_data.get("offset", 0))
        fetch_limit = min(
            _MAX_EVENTS_PER_PROJECT,
            max(page_limit, page_offset + page_limit, _MAX_EVENTS_PER_PROJECT if text else 0),
        )
        params = {**filters, "limit": fetch_limit, "offset": 0}

        async def query(context: ProjectContext) -> _RemoteResult:
            return await self._request(context, "/api/events", params)

        results = await self._fanout(contexts, query, operation="events")
        merged: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        totals: list[int] = []
        bounded_totals: list[int] = []
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
            bounded_totals.append(min(total, _MAX_EVENTS_PER_PROJECT))
            if total > fetch_limit:
                partial = True
            for event in raw_events[:fetch_limit]:
                if isinstance(event, Mapping):
                    row = _event_row(result.context, event)
                    if _event_matches_text(row, text):
                        merged.append(row)
        merged.sort(key=_event_sort_key, reverse=True)
        page = merged[page_offset:page_offset + page_limit]
        coverage = {
            "projects_total": len(contexts),
            "projects_responded": len(results) - len(errors),
            "projects_failed": len(errors),
        }
        if errors:
            partial = True
        known_total = sum(totals) if not text else len(merged)
        accessible_total = len(merged) if text else sum(bounded_totals)
        has_more = page_offset + page_limit < accessible_total and (
            len(merged) > page_offset + page_limit or partial
        )
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
        page_limit = _bounded_limit(tail, 2000)
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
            source_key = str(source or "").casefold()
            safe_packet = quote(str(packet), safe="-_.~") if packet else ""
            safe_run = quote(str(run), safe="-_.~") if run else ""
            safe_stage = quote(str(stage), safe="-_.~") if stage else ""
            if packet and run:
                log_path = f"/api/admin/packet/{safe_packet}/runs/{safe_run}/logs"
                log_params: dict[str, Any] = {
                    "tail": fetch_tail,
                    "stream": _RUN_LOG_STREAMS.get(source_key, "stderr"),
                }
            elif packet and stage:
                log_path = f"/api/admin/packet/{safe_packet}/stages/{safe_stage}/logs"
                log_params = {"tail": fetch_tail, "stream": _STAGE_LOG_STREAMS.get(source_key, "all")}
            elif packet:
                log_path = f"/api/admin/packet/{safe_packet}/logs/aggregated"
                log_params = {
                    "tail": fetch_tail,
                    "sources": _AGGREGATED_LOG_SOURCES.get(source_key, "all")
                    if source_key not in {"", "all"}
                    else "all",
                }
            else:
                log_path = "/api/admin/system/logs"
                log_params = {"tail": fetch_tail}
            return await self._request(
                context,
                log_path,
                log_params,
                operation="logs",
            )

        results = await self._fanout(contexts, query, operation="logs")
        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        bounded_totals: list[int] = []
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
            bounded_totals.append(min(source_total, _MAX_LOG_LINES_PER_PROJECT))
            if bool(data.get("truncated")) or source_total > fetch_tail:
                partial = True
            for line_index, line in enumerate(lines[:fetch_tail]):
                row = _log_row(result.context, line, data.get("source"))
                row["_line_index"] = line_index
                if _log_matches(row, source, worker, packet, run, stage, level, trace_id,
                                contains, expression, since, until):
                    rows.append(row)
        rows.sort(key=_log_sort_key, reverse=True)
        page = rows[page_offset:page_offset + page_limit]
        for row in page:
            row.pop("_line_index", None)
        if errors:
            partial = True
        next_offset = None
        accessible_total = sum(bounded_totals)
        if page_offset + page_limit < accessible_total and (
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
            if _matches_project(q, result.context):
                normalized.append(_project_search_row(result.context))
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


# END_BLOCK_SERVICE
