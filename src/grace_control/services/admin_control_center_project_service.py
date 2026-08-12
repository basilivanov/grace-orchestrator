# ############################################################################
# AI_HEADER: admin_control_center_project_service — project page owner
# ROLE: Owns project tree, packet detail, system and maintenance page models
#       using explicit lower-level collaborators.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Compose project-scoped tree, packet, system and maintenance view
#          models for the Admin Control Center.
# inputs: AdminProjectAccess, project shell and packet-page owner.
# returns: Existing JSON-safe project page dictionaries.
# side_effects: Bounded selected-project reads and packet-page reads.
# emitted_logs: Transport, shell and packet-owner structured logs.
# error_behavior: Unknown projects raise KeyError; disabled projects return
#                 explicit no-read models.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminControlCenterProjectService
#     methods:
#       - project_page
#       - system_page
#       - maintenance_page
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_explorer_helpers import _lease_views
from grace_control.services.admin_control_center_helpers import (
    _effective_config,
    _feature_by_id,
    _find_entity,
    _normalize_features,
    _unwrap,
    _wave_by_id,
)
from grace_control.services.admin_control_center_packet_service import AdminControlCenterPacketService
from grace_control.services.admin_control_center_project_shell import (
    _PACKET_TABS,
    AdminControlCenterProjectShell,
)
from grace_control.services.admin_project_access import AdminProjectAccess

_log = GraceLogger("admin_control_center_project_service")


# START_BLOCK_SERVICE
class AdminControlCenterProjectService:
    """Own project tree, system and maintenance page composition."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind project pages to explicit lower-level collaborators.
    # inputs: access — project read boundary; shell — dashboard/selector owner;
    #         packet — packet-page owner.
    # returns: None.
    # side_effects: None; no project request is made during construction.
    # emitted_logs: None.
    # error_behavior: Collaborator contract errors propagate at construction.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        access: AdminProjectAccess,
        shell: AdminControlCenterProjectShell,
        packet: AdminControlCenterPacketService,
    ) -> None:
        self._access = access
        self._shell = shell
        self._packet = packet

    # START_FUNCTION_CONTRACT
    # name: project_page
    # purpose: Build one project overview and optionally select a feature, wave
    #          or packet without crossing project boundaries.
    # inputs: project_key — explicit key; entity and packet tab selectors.
    # returns: Project-scoped tree and selected-entity view model.
    # side_effects: Reads only the selected enabled project's Admin APIs.
    # emitted_logs: Project access, shell and packet-owner logs.
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
        context = self._access.context(project_key)
        dashboard = await self._shell.dashboard()
        card = next(
            (row for row in dashboard["cards"] if row.get("project_key") == project_key),
            None,
        )
        if card is None:
            card = await self._shell.project_card(project_key)
        base = {
            "project": self._shell.context_info(context, card),
            "projects": dashboard["projects"],
            "current_project": self._shell.selector_current(dashboard["projects"], project_key),
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

        tree_result = await self._access.read(project_key, "/api/admin/features", operation="features")
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
            base["packet_data"] = await self._packet.packet_page(
                project_key,
                entity_id,
                project_info=self._shell.context_info(context, card),
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
        base["entity_missing"] = bool(
            entity_type and entity_id and feature is None and wave is None and packet is None
        )
        return base

    # START_FUNCTION_CONTRACT
    # name: system_page
    # purpose: Build selected-project health, workers, runtime, leases and
    #          masked configuration diagnostics.
    # inputs: project_key — explicit registry key.
    # returns: Project system view model.
    # side_effects: Reads selected project APIs only when enabled.
    # emitted_logs: Project access and Hub overview logs.
    # error_behavior: Unknown project raises KeyError; disabled/unavailable
    #                 projects return a status-aware model.
    # END_FUNCTION_CONTRACT
    async def system_page(self, project_key: str) -> dict[str, Any]:
        context = self._access.context(project_key)
        dashboard = await self._shell.dashboard()
        card = next(
            (row for row in dashboard["cards"] if row.get("project_key") == project_key),
            None,
        )
        if card is None:
            card = await self._shell.project_card(project_key)
        model: dict[str, Any] = {
            "project": self._shell.context_info(context, card),
            "projects": dashboard["projects"],
            "current_project": self._shell.selector_current(dashboard["projects"], project_key),
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
            self._access.read(project_key, "/api/admin/system/health", operation="health"),
            self._access.read(project_key, "/api/admin/system/workers", operation="workers"),
            self._access.read(project_key, "/api/diagnostics/state", operation="diagnostics"),
            self._access.read(project_key, "/api/admin/capabilities", operation="capabilities"),
            self._access.read(project_key, "/api/admin/lifecycle/status", operation="supervisor_status"),
        )
        health = _unwrap(health_result.get("payload")) if health_result.get("ok") else {}
        workers = _unwrap(workers_result.get("payload")) if workers_result.get("ok") else {}
        diagnostics = _unwrap(diagnostics_result.get("payload")) if diagnostics_result.get("ok") else {}
        capabilities = _unwrap(capabilities_result.get("payload")) if capabilities_result.get("ok") else {}
        model["health"] = self._shell.mask(health)
        model["workers"] = workers.get("workers", []) if isinstance(workers, Mapping) else []
        model["diagnostics"] = self._shell.mask(diagnostics)
        model["config"] = self._shell.mask(_effective_config(health, diagnostics))
        model["capabilities"] = self._shell.mask(capabilities)
        model["supervisor"] = self._shell.mask(_unwrap(supervisor_result.get("payload"))) if supervisor_result.get("ok") else {}
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
    # emitted_logs: Project access and shell logs.
    # error_behavior: Unknown projects raise KeyError; remote gaps remain visible.
    # END_FUNCTION_CONTRACT
    async def maintenance_page(self, project_key: str) -> dict[str, Any]:
        shell = await self._shell.explorer_shell(project_key)
        result = await self._access.read(
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


# END_BLOCK_SERVICE
