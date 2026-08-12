# ############################################################################
# AI_HEADER: admin_cross_project_overview_service — cross-project overview reads
# ROLE: Owns the Admin Hub overview and diagnostics read-model composition.
#       It delegates all project selection, fan-out and requests to one
#       explicit CrossProjectTransport boundary.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Compose project overview and diagnostic DTOs for the Admin Hub.
# inputs: ProjectContext values and explicit CrossProjectTransport selection,
#          fan-out and request methods.
# returns: JSON-safe project cards, diagnostic snapshots, aggregates, coverage
#          and normalized attention items.
# side_effects: Performs bounded project-local health, diagnostics and event
#                reads through the explicit transport seam.
# emitted_logs: cross_project_fanout_start, cross_project_project_error,
#                cross_project_fanout_done.
# error_behavior: Isolates project-local failures; unknown project keys and
#                 invalid explicit selectors follow transport selection behavior.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminCrossProjectOverviewService
#     methods:
#       - get_projects_overview
#       - get_diagnostics
#       - _overview_for_context
#       - _overview_for_disabled
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from grace_control.config.project_registry import ProjectContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_cross_project_helpers import (
    _aggregate_snapshots,
    _attention_for_project,
    _attention_for_snapshot,
    _coverage,
    _data_mapping,
    _error_dto,
    _event_row,
    _health_status,
    _malformed_error,
    _now_iso,
    _project_url,
    _RemoteResult,
    _safe_json,
    _selector_values,
    _sizes,
    _sort_attention,
    _value,
)
from grace_control.services.admin_cross_project_transport import CrossProjectTransport

_log = GraceLogger("admin_cross_project_overview")

_DIAGNOSTIC_FIELDS = frozenset({
    "packets_by_state",
    "features_by_status",
    "workers",
    "runs_total",
    "active_leases",
    "ordinary_leases",
    "active_parallel_leases",
    "active_merge_leases",
    "effective_max_concurrency",
    "waits",
    "packet_parallel",
    "parallel_scope_guard",
    "merge_serialization",
    "stale_base_recheck",
})


# START_BLOCK_SERVICE
class AdminCrossProjectOverviewService:
    """Overview and diagnostics projection over an explicit transport."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind overview and diagnostics projection to one explicit
    #          CrossProjectTransport boundary.
    # inputs: transport — configured cross-project transport.
    # returns: None.
    # side_effects: None; no project request is made during construction.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def __init__(self, transport: CrossProjectTransport) -> None:
        self._transport = transport

    # START_FUNCTION_CONTRACT
    # name: get_attention
    # purpose: Return the normalized operator attention model for selected
    #          projects using the overview projection.
    # inputs: project — optional one-or-many explicit project keys.
    # returns: Attention, coverage, errors and fetched timestamp DTO.
    # side_effects: Reads overview/diagnostic project APIs through transport.
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
    # name: get_projects_overview
    # purpose: Return project cards, mathematically scoped aggregate counts,
    #          coverage metadata and normalized operator attention items.
    # inputs: project — optional one-or-many explicit registry keys; omitted
    #          means all configured projects; disabled cards are registry-only
    #          and never receive remote requests.
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
        selected_values = _selector_values(project) if project is not None else []
        contexts = (
            self._transport.list_contexts()
            if project is None or "all" in selected_values
            else self._transport.select_contexts(project)
        )

        async def collect(context: ProjectContext) -> dict[str, Any]:
            if not context.enabled:
                return self._overview_for_disabled(context)
            health, diagnostics, events = await asyncio.gather(
                self._transport.request(context, "/api/admin/system/health", operation="health"),
                self._transport.request(context, "/api/diagnostics/state"),
                self._transport.request(context, "/api/events", {"limit": 1, "offset": 0}),
            )
            return self._overview_for_context(context, health, diagnostics, events)

        rows = await self._transport.fanout(contexts, collect, operation="overview")
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
        contexts = self._transport.select_contexts(project)

        async def query(context: ProjectContext) -> tuple[_RemoteResult, _RemoteResult]:
            diagnostics, health = await asyncio.gather(
                self._transport.request(context, "/api/diagnostics/state", operation="diagnostics"),
                self._transport.request(context, "/api/admin/system/health", operation="health"),
            )
            return diagnostics, health

        results = await self._transport.fanout(contexts, query, operation="diagnostics")
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
            diagnostic_data = _data_mapping(diagnostics_result.payload) if diagnostics_result.ok else {}
            diagnostics_available = bool(_DIAGNOSTIC_FIELDS.intersection(diagnostic_data))
            snapshot = _safe_json(diagnostic_data) if diagnostics_available else {}
            snapshot["diagnostics_available"] = diagnostics_available
            if health_result.ok:
                snapshot["system_health"] = _safe_json(_data_mapping(health_result.payload))
            if not diagnostics_available and not health_result.ok:
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
        aggregate = _aggregate_snapshots(
            [snapshot for snapshot in snapshots if snapshot.get("diagnostics_available", True)]
        )
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
        diagnostic_data = _data_mapping(diagnostics.payload) if diagnostics.ok else {}
        diagnostics_available = bool(_DIAGNOSTIC_FIELDS.intersection(diagnostic_data))
        if diagnostics.ok and not diagnostics_available:
            errors.append(_malformed_error(
                context,
                "/api/diagnostics/state",
                "diagnostics snapshot is missing canonical fields",
            ))
        snapshot = _safe_json(diagnostic_data) if diagnostics_available else None
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
            "disabled": False,
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
            "disabled": True,
        }


# END_BLOCK_SERVICE
