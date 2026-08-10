# ############################################################################
# AI_HEADER: admin_control_center — project-aware Jinja2/HTMX control center
# ROLE: Builds the read-only project-scoped view models used by the Stage 04
#       Admin Control Center. Every remote read is routed through the accepted
#       Admin Hub service with an explicit registry project key.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide project-aware dashboard, entity drill-down, timeline,
#          pipeline, system and cross-project read models for the Jinja2 UI.
# inputs: AdminCrossProjectService and explicit project/entity/tab selectors.
# returns: JSON-safe view-model dictionaries for server-rendered templates.
# side_effects: Bounded reads through project-local Admin APIs only; never
#                changes process-global settings or opens another project's DB.
# emitted_logs: admin_control_center_read_error.
# error_behavior: Unknown projects raise KeyError; unavailable project APIs are
#                 isolated into view-model error/capability fields.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminControlCenterService
#     methods:
#       - contexts
#       - dashboard
#       - project_page
#       - system_page
#       - events_page
#       - logs_page
#       - search_page
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from grace_control.config.project_registry import ProjectContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_helpers import (
    _capability_message,
    _card_sort_key,
    _effective_config,
    _feature_by_id,
    _filter_timeline,
    _find_entity,
    _first_value,
    _has_card_attention,
    _mask_secrets,
    _matches_dashboard_filter,
    _normalize_blocking,
    _normalize_event,
    _normalize_features,
    _normalize_packet,
    _normalize_run,
    _normalize_stage,
    _normalize_stages,
    _sum_states,
    _unwrap,
    _waits_from,
    _wave_by_id,
)
from grace_control.services.admin_cross_project_service import AdminCrossProjectService

_log = GraceLogger("admin_control_center")

_DASHBOARD_FILTERS = ("all", "running", "attention", "blocked", "offline", "idle")
_PACKET_TABS = (
    "overview",
    "timeline",
    "pipeline",
    "spec",
    "runs",
    "stages",
    "sessions",
    "evidence",
    "logs",
    "artifacts",
    "files",
    "git",
    "diagnostics",
    "raw",
)
_SECRET_KEYS = frozenset({
    "api_key",
    "api_password",
    "api_token",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
})
_ATTENTION_STATES = frozenset({
    "blocked",
    "blocked_recoverable",
    "blocked_final",
    "failed",
    "rejected",
    "BLOCKED",
    "BLOCKED_FINAL",
    "FAILED",
    "REJECTED",
})


# START_BLOCK_SERVICE
class AdminControlCenterService:
    """Compose explicit project-local read models for the Stage 04 UI."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the UI read model to the accepted cross-project Hub service.
    # inputs: hub — configured AdminCrossProjectService.
    # returns: None.
    # side_effects: None; no remote request is made during construction.
    # emitted_logs: None.
    # error_behavior: Raises TypeError when hub is not an AdminCrossProjectService.
    # END_FUNCTION_CONTRACT
    def __init__(self, hub: AdminCrossProjectService) -> None:
        if not isinstance(hub, AdminCrossProjectService):
            raise TypeError("AdminControlCenterService requires the Admin Hub service")
        self._hub = hub

    # START_FUNCTION_CONTRACT
    # name: contexts
    # purpose: Return immutable registry contexts in configured order for the
    #          persistent selector and project URL validation.
    # inputs: None.
    # returns: Tuple of immutable ProjectContext values.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def contexts(self) -> tuple[ProjectContext, ...]:
        return self._hub._registry.list_projects()

    # START_FUNCTION_CONTRACT
    # name: dashboard
    # purpose: Build the multi-project landing view from Stage 03 overview and
    #          attention data with deterministic filters and ordering.
    # inputs: filter_name — one of all/running/attention/blocked/offline/idle.
    # returns: Dashboard view model with selector projects and project cards.
    # side_effects: Bounded Hub overview fan-out for configured projects.
    # emitted_logs: admin_control_center_read_error for isolated failures.
    # error_behavior: Unknown filters are normalized to all.
    # END_FUNCTION_CONTRACT
    async def dashboard(self, filter_name: str = "all") -> dict[str, Any]:
        selected_filter = filter_name if filter_name in _DASHBOARD_FILTERS else "all"
        try:
            overview = await self._hub.get_projects_overview()
        except Exception as exc:
            _log.error("admin_control_center_read_error", operation="dashboard")
            overview = {"projects": [], "errors": [{"error": str(exc)[:200]}]}
        cards = self._cards(overview.get("projects", []))
        visible = [card for card in cards if _matches_dashboard_filter(card, selected_filter)]
        visible.sort(key=_card_sort_key)
        return {
            "filter": selected_filter,
            "filters": _DASHBOARD_FILTERS,
            "projects": self._selector_projects(cards),
            "cards": visible,
            "coverage": overview.get("coverage", {}),
            "errors": overview.get("errors", []),
            "attention": overview.get("attention", []),
            "fetched_at": overview.get("fetched_at"),
        }

    # START_FUNCTION_CONTRACT
    # name: project_page
    # purpose: Build one project overview and optionally select its feature,
    #          wave or packet without crossing project boundaries.
    # inputs: project_key — explicit registry key; entity_type/id — optional
    #          feature, wave or packet selection; tab/run_id/stage_id and
    #          timeline filters — packet drill-down context.
    # returns: Project-scoped view model with tree and selected entity data.
    # side_effects: Reads only the selected enabled project's Admin APIs.
    # emitted_logs: admin_control_center_read_error for isolated failures.
    # error_behavior: Raises KeyError for an unknown project; missing entities
    #                 render as explicit not-found view state.
    # END_FUNCTION_CONTRACT
    async def project_page(
        self,
        project_key: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        tab: str = "overview",
        run_id: str | None = None,
        stage_id: str | None = None,
        event: str | None = None,
        component: str | None = None,
        run_stage: str | None = None,
        trace_id: str | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(project_key)
        dashboard = await self.dashboard()
        card = next(
            (row for row in dashboard["cards"] if row.get("project_key") == project_key),
            None,
        )
        if card is None:
            card = await self._project_card(project_key)
        base = {
            "project": self._context_info(context, card),
            "projects": dashboard["projects"],
            "current_project": self._selector_current(dashboard["projects"], project_key),
            "features": [],
            "tree_error": None,
            "entity_type": entity_type if entity_type in {"feature", "wave", "packet"} else None,
            "entity_id": entity_id,
            "tab": tab if tab in _PACKET_TABS else "overview",
            "run_id": run_id,
            "stage_id": stage_id,
            "timeline_filters": {
                "event": event or "",
                "component": component or "",
                "run_stage": run_stage or "",
                "trace_id": trace_id or "",
                "text": text or "",
            },
            "feature": None,
            "wave": None,
            "packet": None,
            "packet_data": None,
        }
        if not context.enabled:
            base["tree_error"] = "Project is disabled; no remote read was attempted."
            return base

        tree_result = await self._read(project_key, "/api/admin/features", operation="features")
        tree = _unwrap(tree_result.get("payload")) if tree_result.get("ok") else {}
        features = tree.get("features", []) if isinstance(tree, Mapping) else []
        if not tree_result.get("ok"):
            base["tree_error"] = tree_result.get("error") or "Project feature tree is unavailable."
        base["features"] = _normalize_features(features)

        feature, wave, packet = _find_entity(base["features"], entity_type, entity_id)
        base["feature"] = feature
        base["wave"] = wave
        if packet is not None and base["entity_type"] == "packet":
            base["packet"] = packet

        if base["entity_type"] == "packet" and entity_id:
            base["packet_data"] = await self._packet_page(
                project_key,
                entity_id,
                tree_packet=packet,
                tab=base["tab"],
                run_id=run_id,
                stage_id=stage_id,
                event=event,
                component=component,
                run_stage=run_stage,
                trace_id=trace_id,
                text=text,
            )
            if base["packet_data"]:
                base["packet"] = base["packet_data"].get("packet") or packet
                base["feature"] = _feature_by_id(base["features"], base["packet"].get("feature_id")) or feature
                base["wave"] = _wave_by_id(base["features"], base["packet"].get("wave_id")) or wave
        base["entity_missing"] = bool(entity_type and entity_id and feature is None and wave is None and packet is None)
        return base

    # START_FUNCTION_CONTRACT
    # name: system_page
    # purpose: Build selected-project health, worker, runtime, lease and wait
    #          diagnostics while masking credential-shaped configuration keys.
    # inputs: project_key — explicit registry key.
    # returns: Project system view model.
    # side_effects: Reads selected project APIs only when enabled.
    # emitted_logs: admin_control_center_read_error for isolated failures.
    # error_behavior: Unknown project raises KeyError; disabled/unavailable
    #                 projects return a status-aware model.
    # END_FUNCTION_CONTRACT
    async def system_page(self, project_key: str) -> dict[str, Any]:
        context = self._context(project_key)
        dashboard = await self.dashboard()
        card = next(
            (row for row in dashboard["cards"] if row.get("project_key") == project_key),
            None,
        )
        if card is None:
            card = await self._project_card(project_key)
        model: dict[str, Any] = {
            "project": self._context_info(context, card),
            "projects": dashboard["projects"],
            "current_project": self._selector_current(dashboard["projects"], project_key),
            "health": {},
            "workers": [],
            "diagnostics": {},
            "config": {},
            "error": None,
        }
        if not context.enabled:
            model["error"] = "Project is disabled; no remote read was attempted."
            return model
        health_result, workers_result, diagnostics_result = await asyncio.gather(
            self._read(project_key, "/api/admin/system/health", operation="health"),
            self._read(project_key, "/api/admin/system/workers", operation="workers"),
            self._read(project_key, "/api/diagnostics/state", operation="diagnostics"),
        )
        health = _unwrap(health_result.get("payload")) if health_result.get("ok") else {}
        workers = _unwrap(workers_result.get("payload")) if workers_result.get("ok") else {}
        diagnostics = _unwrap(diagnostics_result.get("payload")) if diagnostics_result.get("ok") else {}
        model["health"] = _mask_secrets(health)
        model["workers"] = workers.get("workers", []) if isinstance(workers, Mapping) else []
        model["diagnostics"] = _mask_secrets(diagnostics)
        model["config"] = _mask_secrets(_effective_config(health, diagnostics))
        failures = [
            result.get("error")
            for result in (health_result, workers_result, diagnostics_result)
            if not result.get("ok") and result.get("error")
        ]
        model["error"] = failures[0] if failures else None
        return model

    # START_FUNCTION_CONTRACT
    # name: events_page
    # purpose: Build a project-aware canonical event page for the shell Events
    #          view while preserving complete payloads and trace IDs.
    # inputs: project_key — optional explicit key; entity_id/type/event_type —
    #          optional event filters.
    # returns: Event page view model with project selector context.
    # side_effects: Bounded Hub event reads.
    # emitted_logs: Hub-owned cross-project read logs.
    # error_behavior: Unknown project raises KeyError; partial data is visible.
    # END_FUNCTION_CONTRACT
    async def events_page(
        self,
        project_key: str | None = None,
        *,
        entity_id: str | None = None,
        entity_type: str | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        selected = [project_key] if project_key else None
        data = await self._hub.query_events(
            project=selected,
            entity_id=entity_id,
            entity_type=entity_type,
            event_type=event_type,
            limit=200,
        )
        dashboard = await self.dashboard()
        current = self._selector_current(dashboard["projects"], project_key)
        return {
            "projects": dashboard["projects"],
            "current_project": current,
            "events": [_normalize_event(row) for row in data.get("events", [])],
            "coverage": data.get("coverage", {}),
            "errors": data.get("errors", []),
            "filters": {"entity_id": entity_id, "entity_type": entity_type, "event_type": event_type},
        }

    # START_FUNCTION_CONTRACT
    # name: logs_page
    # purpose: Build a project-aware bounded Logs view from the Hub log API.
    # inputs: project_key — optional explicit key; contains/level — optional
    #          server-side log filters.
    # returns: Logs page view model with isolated errors.
    # side_effects: Bounded Hub log reads.
    # emitted_logs: Hub-owned cross-project read logs.
    # error_behavior: Invalid regex/cursor errors propagate to the router as 400.
    # END_FUNCTION_CONTRACT
    async def logs_page(
        self,
        project_key: str | None = None,
        *,
        contains: str | None = None,
        level: str | None = None,
    ) -> dict[str, Any]:
        selected = [project_key] if project_key else None
        data = await self._hub.query_logs(
            project=selected,
            contains=contains,
            level=level,
            tail=200,
        )
        dashboard = await self.dashboard()
        return {
            "projects": dashboard["projects"],
            "current_project": self._selector_current(dashboard["projects"], project_key),
            "logs": data.get("logs", []),
            "coverage": data.get("coverage", {}),
            "errors": data.get("errors", []),
            "contains": contains or "",
            "level": level or "",
        }

    # START_FUNCTION_CONTRACT
    # name: search_page
    # purpose: Build a project-aware search result page with canonical entity
    #          target URLs returned by the Stage 03 Hub service.
    # inputs: query — search text; project_key — optional explicit key.
    # returns: Search page view model.
    # side_effects: Bounded Hub search and dashboard reads.
    # emitted_logs: Hub-owned cross-project read logs.
    # error_behavior: Unknown project raises KeyError; project errors are shown.
    # END_FUNCTION_CONTRACT
    async def search_page(
        self,
        query: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        selected = [project_key] if project_key else None
        data = await self._hub.search(query, project=selected, limit=200)
        dashboard = await self.dashboard()
        return {
            "projects": dashboard["projects"],
            "current_project": self._selector_current(dashboard["projects"], project_key),
            "results": data.get("results", []),
            "errors": data.get("errors", []),
            "query": query,
        }

    # START_FUNCTION_CONTRACT
    # name: _packet_page
    # purpose: Read packet detail, blocking decision and the selected tab's
    #          project-local data without losing explicit project identity.
    # inputs: project_key, packet_id, optional tree packet, tab, run/stage
    #         selectors and timeline filters.
    # returns: Packet drill-down view model.
    # side_effects: Reads selected project's canonical Admin endpoints.
    # emitted_logs: admin_control_center_read_error for isolated failures.
    # error_behavior: Missing endpoint data becomes a capability-aware model.
    # END_FUNCTION_CONTRACT
    async def _packet_page(
        self,
        project_key: str,
        packet_id: str,
        *,
        tree_packet: Mapping[str, Any] | None,
        tab: str,
        run_id: str | None,
        stage_id: str | None,
        event: str | None,
        component: str | None,
        run_stage: str | None,
        trace_id: str | None,
        text: str | None,
    ) -> dict[str, Any]:
        detail_result, blocking_result = await asyncio.gather(
            self._read(project_key, f"/api/admin/packet/{packet_id}/detail", operation="packet_detail"),
            self._read(project_key, f"/api/admin/packet/{packet_id}/blocking_decision", operation="blocking"),
        )
        detail = _unwrap(detail_result.get("payload")) if detail_result.get("ok") else {}
        raw: dict[str, Any] = {}
        runs: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = []
        sessions: dict[str, Any] = {}
        diagnostics: dict[str, Any] = {}
        selected_run: dict[str, Any] | None = None
        selected_stage: dict[str, Any] | None = None

        if tab in {"spec", "pipeline", "stages", "raw"}:
            raw_result = await self._read(
                project_key,
                f"/api/admin/packet/{packet_id}/raw",
                operation="packet_raw",
            )
            raw = _unwrap(raw_result.get("payload")) if raw_result.get("ok") else {}
        if tab == "timeline":
            timeline_result = await self._read(
                project_key,
                f"/api/admin/packet/{packet_id}/timeline?limit=200&offset=0",
                operation="timeline",
            )
            timeline_payload = _unwrap(timeline_result.get("payload")) if timeline_result.get("ok") else {}
            timeline = [_normalize_event(row) for row in timeline_payload.get("events", [])]
        if tab == "runs" or run_id:
            runs_result = await self._read(
                project_key,
                f"/api/admin/packet/{packet_id}/runs",
                operation="runs",
            )
            runs_payload = _unwrap(runs_result.get("payload")) if runs_result.get("ok") else {}
            runs = [_normalize_run(row) for row in runs_payload.get("runs", [])]
            if run_id:
                selected_run = next(
                    (
                        row for row in runs
                        if str(row.get("id")) == str(run_id)
                        and (row.get("packet_id") in (None, packet_id))
                    ),
                    None,
                )
                if selected_run is None:
                    run_result = await self._read(
                        project_key,
                        f"/api/admin/packet/{packet_id}/runs/{run_id}",
                        operation="run_detail",
                    )
                    if run_result.get("ok"):
                        candidate = _normalize_run(_unwrap(run_result.get("payload")))
                        if (
                            str(candidate.get("id")) == str(run_id)
                            and candidate.get("packet_id") in (None, packet_id)
                        ):
                            selected_run = candidate
        if tab in {"stages", "pipeline"} and stage_id:
            stage_rows = raw.get("stages", []) if isinstance(raw, Mapping) else []
            stage_rows = self._scope_rows_to_run(stage_rows, run_id)
            stage_match = next(
                (
                    row for row in stage_rows
                    if isinstance(row, Mapping) and str(row.get("id") or row.get("stage_run_id")) == str(stage_id)
                ),
                None,
            )
            if stage_match is not None:
                stage_result = await self._read(
                    project_key,
                    f"/api/admin/stage/{stage_id}/raw",
                    operation="stage_detail",
                )
                if stage_result.get("ok"):
                    selected_stage = _normalize_stage(_unwrap(stage_result.get("payload")))
        if tab == "sessions":
            sessions_result = await self._read(
                project_key,
                f"/api/admin/packet/{packet_id}/sessions",
                operation="sessions",
            )
            if sessions_result.get("ok"):
                sessions = _unwrap(sessions_result.get("payload"))
                if not isinstance(sessions, Mapping):
                    sessions = {"available": False, "message": "Sessions response is unavailable."}
                else:
                    sessions = dict(sessions)
                    sessions.setdefault("available", True)
            else:
                sessions = {
                    "available": False,
                    "message": _capability_message(sessions_result),
                }
        if tab == "diagnostics":
            diagnostics_result = await self._read(
                project_key,
                "/api/diagnostics/state",
                operation="diagnostics",
            )
            diagnostics = _unwrap(diagnostics_result.get("payload")) if diagnostics_result.get("ok") else {
                "error": _capability_message(diagnostics_result),
            }

        if tab == "timeline":
            timeline = self._scope_rows_to_run(timeline, run_id)
            timeline = _filter_timeline(
                timeline,
                event_filter=event,
                component_filter=component,
                run_stage_filter=run_stage,
                trace_filter=trace_id,
                text_filter=text,
            )

        packet = _normalize_packet(
            detail,
            tree_packet,
            raw.get("packet") if isinstance(raw, Mapping) else None,
            runs,
            selected_run if run_id else None,
        )
        blocking = _normalize_blocking(detail, blocking_result, packet)
        detail_stages = detail.get("stages") if isinstance(detail, Mapping) else None
        raw_stages = raw.get("stages") if isinstance(raw, Mapping) else None
        stages = _normalize_stages(
            None if run_id and isinstance(raw_stages, list) else detail_stages,
            raw_stages,
            detail.get("pipeline") if isinstance(detail, Mapping) else None,
        )
        stages = self._scope_rows_to_run(stages, run_id)
        if selected_stage is not None:
            selected_stage = _normalize_stage(selected_stage)
        return {
            "packet": packet,
            "detail": detail,
            "blocking": blocking,
            "timeline": timeline,
            "timeline_total": len(timeline),
            "runs": runs,
            "selected_run": selected_run,
            "stages": stages,
            "selected_stage": selected_stage,
            "sessions": sessions,
            "diagnostics": _mask_secrets(diagnostics),
            "raw": _mask_secrets(raw),
            "tabs": _PACKET_TABS,
            "tab": tab if tab in _PACKET_TABS else "overview",
            "run_id": run_id,
            "stage_id": stage_id,
            "timeline_filters": {
                "event": event or "",
                "component": component or "",
                "run_stage": run_stage or "",
                "trace_id": trace_id or "",
                "text": text or "",
            },
        }

    # START_FUNCTION_CONTRACT
    # name: _scope_rows_to_run
    # purpose: Keep packet rows associated with the explicit selected run while
    #          retaining packet-wide rows that have no run association.
    # inputs: raw/normalized row sequence and optional selected run ID.
    # returns: Rows belonging to the selected run or packet-wide rows.
    # side_effects: None; returned rows are shallow copies.
    # emitted_logs: None.
    # error_behavior: Skips malformed non-mapping rows.
    # END_FUNCTION_CONTRACT
    def _scope_rows_to_run(
        self,
        rows: Any,
        run_id: str | None,
    ) -> list[dict[str, Any]]:
        if not isinstance(rows, list):
            return []
        scoped: list[dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
            row_run_id = row.get("run_id") or payload.get("run_id")
            if run_id and row_run_id is not None and str(row_run_id) != str(run_id):
                continue
            scoped.append(row)
        return scoped

    # START_FUNCTION_CONTRACT
    # name: _project_card
    # purpose: Read one project card through Stage 03 without mutating global
    #          project state.
    # inputs: project_key — explicit registry key.
    # returns: Normalized card or an isolated error card.
    # side_effects: Bounded selected-project health/diagnostics/event reads.
    # emitted_logs: Hub-owned fan-out logs.
    # error_behavior: Unknown project raises KeyError.
    # END_FUNCTION_CONTRACT
    async def _project_card(self, project_key: str) -> dict[str, Any]:
        overview = await self._hub.get_projects_overview(project_key)
        cards = self._cards(overview.get("projects", []))
        if cards:
            return cards[0]
        context = self._context(project_key)
        return self._context_info(context, {"status": "offline", "error": "Project overview unavailable."})

    # START_FUNCTION_CONTRACT
    # name: _read
    # purpose: Execute one explicit project-local GET through the Hub service's
    #          bounded transport and normalize typed errors for templates.
    # inputs: project_key, absolute API path and optional operation label.
    # returns: Internal result mapping with ok/payload/error fields.
    # side_effects: One bounded remote project API read; disabled projects are
    #                rejected before a client is created.
    # emitted_logs: Hub-owned cross-project project error logs.
    # error_behavior: Never raises transport errors; unknown project raises KeyError.
    # END_FUNCTION_CONTRACT
    async def _read(
        self,
        project_key: str,
        path: str,
        *,
        operation: str,
    ) -> dict[str, Any]:
        context = self._context(project_key)
        result = await self._hub._request(context, path, operation=operation)
        return {
            "ok": bool(result.ok),
            "payload": result.payload or {},
            "error": result.error or result.error_class,
            "error_class": result.error_class,
            "http_status": result.http_status,
        }

    # START_FUNCTION_CONTRACT
    # name: _context
    # purpose: Resolve one immutable project context for an explicit request.
    # inputs: project_key — URL path key.
    # returns: ProjectContext.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises KeyError for unknown project keys.
    # END_FUNCTION_CONTRACT
    def _context(self, project_key: str) -> ProjectContext:
        return self._hub._registry.get(project_key)

    # START_FUNCTION_CONTRACT
    # name: _cards
    # purpose: Enrich Stage 03 project cards with immutable registry metadata
    #          needed by the UI selector and operational card.
    # inputs: Stage 03 project card mappings.
    # returns: Enriched cards in registry order.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Ignores malformed card rows while preserving registry cards.
    # END_FUNCTION_CONTRACT
    def _cards(self, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        by_key = {
            str(row.get("project_key") or row.get("key")): dict(row)
            for row in rows
            if isinstance(row, Mapping)
        }
        cards: list[dict[str, Any]] = []
        for context in self.contexts():
            card = dict(by_key.get(context.key) or {})
            card.setdefault("project_key", context.key)
            card.setdefault("project_name", context.name)
            card.setdefault("key", context.key)
            card.setdefault("name", context.name)
            card.setdefault("enabled", context.enabled)
            runtime = card.get("runtime") if isinstance(card.get("runtime"), Mapping) else {}
            card["unix_user"] = context.unix_user
            card["project_root"] = str(context.project_root)
            card["description"] = context.description
            card["tags"] = list(context.tags)
            card["target_branch"] = _first_value(card, runtime, "target_branch")
            card["target_head"] = _first_value(card, runtime, "target_head")
            card["grace_version"] = _first_value(card, runtime, "version")
            card["grace_code_sha"] = _first_value(card, runtime, "code_sha")
            card["api_health"] = _first_value(card, runtime, "api_status", "api_alive")
            card["supervisor_health"] = _first_value(card, runtime, "supervisor_status", "supervisor_alive")
            card["db_health"] = _first_value(card, runtime, "db_ok")
            card["active_parallel_lease_count"] = len(card.get("active_parallel_leases") or [])
            card["merge_owner"] = card.get("merge_lease")
            card["blocked_count"] = _sum_states(
                card.get("packets_by_state"),
                "blocked",
                "blocked_recoverable",
                "blocked_final",
            )
            card["waits"] = _waits_from(card)
            card["has_attention"] = _has_card_attention(card)
            cards.append(card)
        return cards

    # START_FUNCTION_CONTRACT
    # name: _context_info
    # purpose: Merge immutable registry identity with an optional remote card.
    # inputs: ProjectContext and optional card mapping.
    # returns: Selector-safe project metadata mapping.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for ordinary missing card fields.
    # END_FUNCTION_CONTRACT
    def _context_info(
        self,
        context: ProjectContext,
        card: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        source = dict(card or {})
        return {
            **source,
            "project_key": context.key,
            "project_name": context.name,
            "key": context.key,
            "name": context.name,
            "enabled": context.enabled,
            "unix_user": context.unix_user,
            "project_root": str(context.project_root),
            "description": context.description,
            "tags": list(context.tags),
            "status": source.get("status") or ("disabled" if not context.enabled else "unknown"),
        }

    # START_FUNCTION_CONTRACT
    # name: _selector_projects
    # purpose: Return compact status-bearing project selector rows.
    # inputs: Enriched project cards.
    # returns: List of selector mappings in registry order.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _selector_projects(self, cards: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "project_key": card.get("project_key"),
                "project_name": card.get("project_name") or card.get("name"),
                "name": card.get("name") or card.get("project_name"),
                "status": card.get("status", "unknown"),
                "enabled": card.get("enabled", True),
                "has_attention": card.get("has_attention", False),
            }
            for card in cards
        ]

    # START_FUNCTION_CONTRACT
    # name: _selector_current
    # purpose: Resolve current selector row by explicit project key.
    # inputs: selector project rows and optional project key.
    # returns: Matching row or None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _selector_current(
        self,
        projects: Sequence[Mapping[str, Any]],
        project_key: str | None,
    ) -> dict[str, Any] | None:
        if not project_key:
            return None
        return next((dict(row) for row in projects if row.get("project_key") == project_key), None)


# END_BLOCK_SERVICE
