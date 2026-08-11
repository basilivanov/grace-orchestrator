# ############################################################################
# AI_HEADER: admin_control_center_project_service — project shell and dashboard owner
# ROLE: Owns project-selector, dashboard, entity-tree and system-page composition
#       for the Admin Control Center while preserving the facade's explicit Hub boundary.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Compose project-scoped dashboard, tree, system and maintenance view models.
# inputs: AdminControlCenterService facade and explicit registry project keys.
# returns: JSON-safe project and dashboard view-model dictionaries.
# side_effects: Bounded Hub overview and selected-project reads; never changes
#               process-global project state.
# emitted_logs: admin_control_center_read_error for isolated dashboard failures.
# error_behavior: Unknown project keys raise KeyError; disabled projects return
#                 explicit no-read models.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminControlCenterProjectService
#     methods:
#       - contexts
#       - dashboard
#       - project_page
#       - system_page
#       - maintenance_page
#       - explorer_shell
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from grace_control.config.project_registry import ProjectContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_explorer_helpers import _lease_views
from grace_control.services.admin_control_center_helpers import (
    _card_sort_key,
    _effective_config,
    _feature_by_id,
    _find_entity,
    _first_value,
    _has_card_attention,
    _mask_secrets,
    _matches_dashboard_filter,
    _normalize_features,
    _sum_states,
    _unwrap,
    _waits_from,
    _wave_by_id,
)

if TYPE_CHECKING:
    from grace_control.services.admin_control_center import AdminControlCenterService

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


# START_BLOCK_SERVICE
class AdminControlCenterProjectService:
    """Own project-aware shell, dashboard and system page composition."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind project composition to the stable control-center facade.
    # inputs: facade — initialized AdminControlCenterService coordinator.
    # returns: None.
    # side_effects: None; no project request is made during construction.
    # emitted_logs: None.
    # error_behavior: Type validation is retained by the facade constructor.
    # END_FUNCTION_CONTRACT
    def __init__(self, facade: AdminControlCenterService) -> None:
        self._facade = facade

    # START_FUNCTION_CONTRACT
    # name: contexts
    # purpose: Return immutable registry contexts in configured order.
    # inputs: None.
    # returns: Tuple of immutable ProjectContext values.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def contexts(self) -> tuple[ProjectContext, ...]:
        return self._facade._hub._registry.list_projects()

    # START_FUNCTION_CONTRACT
    # name: dashboard
    # purpose: Build the multi-project landing view with deterministic filters
    #          and registry ordering.
    # inputs: filter_name — one of all/running/attention/blocked/offline/idle.
    # returns: Dashboard view model with selector projects and project cards.
    # side_effects: Bounded Hub overview fan-out for configured projects.
    # emitted_logs: admin_control_center_read_error for isolated failures.
    # error_behavior: Unknown filters are normalized to all.
    # END_FUNCTION_CONTRACT
    async def dashboard(self, filter_name: str = "all") -> dict[str, Any]:
        selected_filter = filter_name if filter_name in _DASHBOARD_FILTERS else "all"
        try:
            overview = await self._facade._hub.get_projects_overview()
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
    # purpose: Build one project overview and optionally select a feature, wave
    #          or packet without crossing project boundaries.
    # inputs: project_key — explicit key; entity and packet tab selectors.
    # returns: Project-scoped tree and selected-entity view model.
    # side_effects: Reads only the selected enabled project's Admin APIs.
    # emitted_logs: Hub-owned read logs and packet-owner logs.
    # error_behavior: Unknown projects raise KeyError; missing entities remain
    #                 explicit in the returned model.
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
        source: str | None = None,
        log_tail: int = 500,
        artifact_path: str | None = None,
        file_root: str | None = None,
        file_path: str = "",
        git_ref: str | None = None,
        git_path: str | None = None,
    ) -> dict[str, Any]:
        context = self._facade._context(project_key)
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

        tree_result = await self._facade._read(project_key, "/api/admin/features", operation="features")
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
            base["packet_data"] = await self._facade._packet_page(
                project_key,
                entity_id,
                project_info=self._context_info(context, card),
                tree_packet=packet,
                tab=base["tab"],
                run_id=run_id,
                stage_id=stage_id,
                event=event,
                component=component,
                run_stage=run_stage,
                trace_id=trace_id,
                text=text,
                source=source,
                log_tail=log_tail,
                artifact_path=artifact_path,
                file_root=file_root,
                file_path=file_path,
                git_ref=git_ref,
                git_path=git_path,
            )
            if base["packet_data"]:
                base["packet"] = base["packet_data"].get("packet") or packet
                base["feature"] = _feature_by_id(base["features"], base["packet"].get("feature_id")) or feature
                base["wave"] = _wave_by_id(base["features"], base["packet"].get("wave_id")) or wave
        base["entity_missing"] = bool(entity_type and entity_id and feature is None and wave is None and packet is None)
        return base

    # START_FUNCTION_CONTRACT
    # name: system_page
    # purpose: Build selected-project health, workers, runtime, leases and
    #          masked configuration diagnostics.
    # inputs: project_key — explicit registry key.
    # returns: Project system view model.
    # side_effects: Reads selected project APIs only when enabled.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Unknown project raises KeyError; disabled/unavailable
    #                 projects return a status-aware model.
    # END_FUNCTION_CONTRACT
    async def system_page(self, project_key: str) -> dict[str, Any]:
        context = self._facade._context(project_key)
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
            "capabilities": {},
            "supervisor": {},
            "leases": {"ordinary": [], "parallel": [], "merge": []},
            "error": None,
        }
        if not context.enabled:
            model["error"] = "Project is disabled; no remote read was attempted."
            return model
        health_result, workers_result, diagnostics_result, capabilities_result, supervisor_result = await asyncio.gather(
            self._facade._read(project_key, "/api/admin/system/health", operation="health"),
            self._facade._read(project_key, "/api/admin/system/workers", operation="workers"),
            self._facade._read(project_key, "/api/diagnostics/state", operation="diagnostics"),
            self._facade._read(project_key, "/api/admin/capabilities", operation="capabilities"),
            self._facade._read(project_key, "/api/admin/lifecycle/status", operation="supervisor_status"),
        )
        health = _unwrap(health_result.get("payload")) if health_result.get("ok") else {}
        workers = _unwrap(workers_result.get("payload")) if workers_result.get("ok") else {}
        diagnostics = _unwrap(diagnostics_result.get("payload")) if diagnostics_result.get("ok") else {}
        capabilities = _unwrap(capabilities_result.get("payload")) if capabilities_result.get("ok") else {}
        model["health"] = self._mask(health)
        model["workers"] = workers.get("workers", []) if isinstance(workers, Mapping) else []
        model["diagnostics"] = self._mask(diagnostics)
        model["config"] = self._mask(_effective_config(health, diagnostics))
        model["capabilities"] = self._mask(capabilities)
        model["supervisor"] = self._mask(_unwrap(supervisor_result.get("payload"))) if supervisor_result.get("ok") else {}
        model["leases"] = _lease_views(diagnostics)
        failures = [
            result.get("error")
            for result in (health_result, workers_result, diagnostics_result, capabilities_result, supervisor_result)
            if not result.get("ok") and result.get("error")
        ]
        model["error"] = failures[0] if failures else None
        return model

    # START_FUNCTION_CONTRACT
    # name: maintenance_page
    # purpose: Build the selected-project maintenance snapshot view.
    # inputs: project_key — explicit registry key.
    # returns: Maintenance view model with snapshot and error fields.
    # side_effects: One selected-project bounded GET plus dashboard context.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Unknown projects raise KeyError; remote gaps remain visible.
    # END_FUNCTION_CONTRACT
    async def maintenance_page(self, project_key: str) -> dict[str, Any]:
        shell = await self.explorer_shell(project_key)
        result = await self._facade._read(
            project_key,
            "/api/admin/maintenance/snapshot",
            operation="maintenance_snapshot",
        )
        payload = _unwrap(result.get("payload")) if result.get("ok") else {}
        data = payload.get("data") if isinstance(payload, Mapping) else {}
        return {
            **shell,
            "maintenance": data if isinstance(data, Mapping) else {},
            "error": None if result.get("ok") else result.get("error") or "Maintenance unavailable.",
        }

    # START_FUNCTION_CONTRACT
    # name: explorer_shell
    # purpose: Build shared project selector context for project-scoped explorers.
    # inputs: project_key — explicit registry key.
    # returns: project/projects/current_project mapping.
    # side_effects: Bounded dashboard read through the Hub.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Unknown project raises KeyError.
    # END_FUNCTION_CONTRACT
    async def explorer_shell(self, project_key: str) -> dict[str, Any]:
        context = self._facade._context(project_key)
        dashboard = await self.dashboard()
        card = next(
            (row for row in dashboard["cards"] if row.get("project_key") == project_key),
            None,
        )
        if card is None:
            card = await self._project_card(project_key)
        return {
            "project": self._context_info(context, card),
            "projects": dashboard["projects"],
            "current_project": self._selector_current(dashboard["projects"], project_key),
        }

    # START_FUNCTION_CONTRACT
    # name: _project_card
    # purpose: Read and normalize one selected project's dashboard card.
    # inputs: project_key — explicit registry key.
    # returns: Normalized card or an isolated offline card.
    # side_effects: Bounded selected-project overview read.
    # emitted_logs: Hub-owned read logs.
    # error_behavior: Unknown project raises KeyError.
    # END_FUNCTION_CONTRACT
    async def _project_card(self, project_key: str) -> dict[str, Any]:
        overview = await self._facade._hub.get_projects_overview(project_key)
        cards = self._cards(overview.get("projects", []))
        if cards:
            return cards[0]
        context = self._facade._context(project_key)
        return self._context_info(context, {"status": "offline", "error": "Project overview unavailable."})

    # START_FUNCTION_CONTRACT
    # name: _cards
    # purpose: Enrich Hub project cards with immutable registry metadata.
    # inputs: Stage 03 project card mappings.
    # returns: Enriched cards in registry order.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Malformed rows are ignored while registry cards remain.
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
    # inputs: context — ProjectContext; card — optional remote card.
    # returns: Selector-safe project metadata mapping.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Missing card fields use safe defaults.
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
    # purpose: Return compact status-bearing selector rows.
    # inputs: Enriched project cards.
    # returns: Selector mappings in registry order.
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
    # purpose: Resolve the current selector row by explicit project key.
    # inputs: projects — selector rows; project_key — optional selected key.
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

    # START_FUNCTION_CONTRACT
    # name: _mask
    # purpose: Apply the existing operator-data masking boundary to a value.
    # inputs: value — JSON-like project response.
    # returns: Masked JSON-safe value.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Masking degrades malformed values safely.
    # END_FUNCTION_CONTRACT
    def _mask(self, value: Any) -> Any:
        return _mask_secrets(value)


# END_BLOCK_SERVICE
