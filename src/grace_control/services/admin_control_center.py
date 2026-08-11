# ############################################################################
# AI_HEADER: admin_control_center — bounded project-aware control-center facade
# ROLE: Preserves the public AdminControlCenterService import, constructor and
#       page method signatures while delegating coherent project, packet, explorer
#       and global-page responsibilities to focused owners.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide the stable project-aware Admin Control Center service surface
#          for dashboard, entity, system, maintenance and explorer pages.
# inputs: AdminCrossProjectService and explicit project/entity/tab selectors.
# returns: Existing JSON-safe view-model dictionaries for server-rendered pages.
# side_effects: Bounded reads through the accepted Hub and one delegated mutation
#               through AdminMutationService; no global project state changes.
# emitted_logs: Owner and Hub structured read/mutation logs.
# error_behavior: Unknown projects raise KeyError; capability gaps remain typed
#                 in view-model error fields.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminControlCenterService
#     methods:
#       - contexts
#       - dashboard
#       - project_page
#       - system_page
#       - maintenance_page
#       - events_page
#       - logs_page
#       - files_page
#       - git_page
#       - api_page
#       - search_page
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from grace_control.config.project_registry import ProjectContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_explorer_service import (
    _OPENAPI_CACHE_TTL_SECONDS,  # noqa: F401
    AdminControlCenterExplorerService,
    _json_body,  # noqa: F401
    _json_confirmation,  # noqa: F401
)
from grace_control.services.admin_control_center_packet_service import AdminControlCenterPacketService
from grace_control.services.admin_control_center_page_service import AdminControlCenterPageService
from grace_control.services.admin_control_center_project_service import (
    _DASHBOARD_FILTERS,  # noqa: F401
    _PACKET_TABS,
    AdminControlCenterProjectService,
)
from grace_control.services.admin_cross_project_service import AdminCrossProjectService

_log = GraceLogger("admin_control_center")


# START_BLOCK_SERVICE
class AdminControlCenterService:
    """Stable compatibility facade for project-aware Admin Control Center pages."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the facade to the accepted cross-project Hub service and
    #          initialize focused page owners behind the stable import.
    # inputs: hub — configured AdminCrossProjectService.
    # returns: None.
    # side_effects: Initializes an app-scoped project-keyed OpenAPI cache;
    #               no remote request is made during construction.
    # emitted_logs: None.
    # error_behavior: Raises TypeError when hub is not an AdminCrossProjectService.
    # END_FUNCTION_CONTRACT
    def __init__(self, hub: AdminCrossProjectService) -> None:
        if not isinstance(hub, AdminCrossProjectService):
            raise TypeError("AdminControlCenterService requires the Admin Hub service")
        self._hub = hub
        cache = getattr(hub, "_admin_openapi_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            hub._admin_openapi_cache = cache
        self._openapi_cache: dict[str, tuple[float, dict[str, Any]]] = cache
        self._packet_tabs = _PACKET_TABS
        self._project = AdminControlCenterProjectService(self)
        self._explorer = AdminControlCenterExplorerService(self)
        self._packet = AdminControlCenterPacketService(self)
        self._pages = AdminControlCenterPageService(self)

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
        return self._project.contexts()

    # START_FUNCTION_CONTRACT
    # name: dashboard
    # purpose: Build the multi-project landing view from Hub overview data.
    # inputs: filter_name — one of all/running/attention/blocked/offline/idle.
    # returns: Dashboard view model with selector projects and project cards.
    # side_effects: Bounded Hub overview fan-out.
    # emitted_logs: Owner and Hub read logs.
    # error_behavior: Unknown filters are normalized to all.
    # END_FUNCTION_CONTRACT
    async def dashboard(self, filter_name: str = "all") -> dict[str, Any]:
        return await self._project.dashboard(filter_name)

    # START_FUNCTION_CONTRACT
    # name: project_page
    # purpose: Build a project overview and optional feature/wave/packet detail.
    # inputs: project_key and existing entity/tab/run/stage/explorer selectors.
    # returns: Project-scoped view model with existing template-facing keys.
    # side_effects: Reads only the selected enabled project's APIs.
    # emitted_logs: Owner and Hub read logs.
    # error_behavior: Unknown project raises KeyError; missing entities render in-page.
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
        return await self._project.project_page(
            project_key,
            entity_type=entity_type,
            entity_id=entity_id,
            tab=tab,
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

    # START_FUNCTION_CONTRACT
    # name: system_page
    # purpose: Build selected-project health, runtime, workers, leases and
    #          masked configuration diagnostics.
    # inputs: project_key — explicit registry key.
    # returns: Project system view model.
    # side_effects: Selected-project bounded reads when enabled.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Disabled/unavailable projects return status-aware DTOs.
    # END_FUNCTION_CONTRACT
    async def system_page(self, project_key: str) -> dict[str, Any]:
        return await self._project.system_page(project_key)

    # START_FUNCTION_CONTRACT
    # name: maintenance_page
    # purpose: Build selected-project maintenance snapshot view.
    # inputs: project_key — explicit registry key.
    # returns: Maintenance view model with snapshot/error fields.
    # side_effects: Selected-project bounded read plus dashboard context.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Unknown project raises KeyError; remote gaps remain visible.
    # END_FUNCTION_CONTRACT
    async def maintenance_page(self, project_key: str) -> dict[str, Any]:
        return await self._project.maintenance_page(project_key)

    # START_FUNCTION_CONTRACT
    # name: events_page
    # purpose: Build the project-aware canonical event page.
    # inputs: project selector and optional event/entity filters.
    # returns: Event page view model with complete payload and cursor fields.
    # side_effects: Bounded Hub event and dashboard reads.
    # emitted_logs: Hub-owned event read logs.
    # error_behavior: Partial data remains visible.
    # END_FUNCTION_CONTRACT
    async def events_page(
        self,
        project_key: str | Sequence[str] | None = None,
        *,
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
        return await self._pages.events_page(
            project_key,
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
    # name: logs_page
    # purpose: Build the project-aware bounded Logs page.
    # inputs: project selector and existing source/filter/pagination arguments.
    # returns: Logs page view model with filters and cursor fields.
    # side_effects: Bounded Hub log and dashboard reads.
    # emitted_logs: Hub-owned log read logs.
    # error_behavior: Hub-owned invalid regex/cursor behavior is preserved.
    # END_FUNCTION_CONTRACT
    async def logs_page(
        self,
        project_key: str | Sequence[str] | None = None,
        *,
        source: str | None = None,
        worker: str | None = None,
        packet: str | None = None,
        run: str | None = None,
        stage: str | None = None,
        contains: str | None = None,
        level: str | None = None,
        trace_id: str | None = None,
        regex: str | None = None,
        since: str | None = None,
        until: str | None = None,
        tail: int = 500,
        cursor: str | None = None,
        follow: bool = False,
        wrap: bool = False,
    ) -> dict[str, Any]:
        return await self._pages.logs_page(
            project_key,
            source=source,
            worker=worker,
            packet=packet,
            run=run,
            stage=stage,
            contains=contains,
            level=level,
            trace_id=trace_id,
            regex=regex,
            since=since,
            until=until,
            tail=tail,
            cursor=cursor,
            follow=follow,
            wrap=wrap,
        )

    # START_FUNCTION_CONTRACT
    # name: files_page
    # purpose: Build the selected project's named-root filesystem explorer.
    # inputs: project_key and existing root/path/preview/tail selectors.
    # returns: Files view model with path safety and capability fields.
    # side_effects: Selected-project filesystem reads only.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Unsafe paths are rejected before remote reads.
    # END_FUNCTION_CONTRACT
    async def files_page(
        self,
        project_key: str,
        *,
        root: str | None = None,
        path: str = "",
        preview_path: str | None = None,
        tail: int = 0,
    ) -> dict[str, Any]:
        return await self._explorer.files_page(
            project_key,
            root=root,
            path=path,
            preview_path=preview_path,
            tail=tail,
        )

    # START_FUNCTION_CONTRACT
    # name: git_page
    # purpose: Build the selected project's bounded Git explorer.
    # inputs: project_key and optional packet/ref/path selectors.
    # returns: Git repository, worktree, changed-file and diff view model.
    # side_effects: Selected-project Git reads only.
    # emitted_logs: Hub-owned Git read logs.
    # error_behavior: Typed Git errors remain visible in the model.
    # END_FUNCTION_CONTRACT
    async def git_page(
        self,
        project_key: str,
        *,
        packet: Mapping[str, Any] | None = None,
        ref: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        return await self._explorer.git_page(project_key, packet=packet, ref=ref, path=path)

    # START_FUNCTION_CONTRACT
    # name: api_page
    # purpose: Discover exact OpenAPI operations and execute only an exact GET
    #          or authorized mutation delegated to AdminMutationService.
    # inputs: project_key, path/method/execution selectors and bounded JSON gates.
    # returns: API explorer documentation plus response/error DTO.
    # side_effects: OpenAPI read and optional delegated project mutation.
    # emitted_logs: Hub-owned read and mutation service logs.
    # error_behavior: Mutation/arbitrary-path execution remains gated/rejected.
    # END_FUNCTION_CONTRACT
    async def api_page(
        self,
        project_key: str,
        *,
        path: str | None = None,
        execute: bool = False,
        params_json: str | None = None,
        method: str = "GET",
        control_mode: bool = False,
        body_json: str | None = None,
        confirmation_json: str | None = None,
        actor: str = "operator",
        allow_mutation: bool = False,
    ) -> dict[str, Any]:
        return await self._explorer.api_page(
            project_key,
            path=path,
            execute=execute,
            params_json=params_json,
            method=method,
            control_mode=control_mode,
            body_json=body_json,
            confirmation_json=confirmation_json,
            actor=actor,
            allow_mutation=allow_mutation,
        )

    # START_FUNCTION_CONTRACT
    # name: search_page
    # purpose: Build project-aware search results with canonical Hub targets.
    # inputs: query — search text; project_key — optional explicit key.
    # returns: Search page view model.
    # side_effects: Bounded Hub search and dashboard reads.
    # emitted_logs: Hub-owned search read logs.
    # error_behavior: Unknown project raises KeyError; errors remain visible.
    # END_FUNCTION_CONTRACT
    async def search_page(self, query: str = "", project_key: str | None = None) -> dict[str, Any]:
        return await self._pages.search_page(query, project_key)

    # END_BLOCK_SERVICE

    # START_BLOCK_COMPATIBILITY
    # START_FUNCTION_CONTRACT
    # name: _packet_page
    # purpose: Preserve the historical private packet seam while delegating to
    #          the decomposed packet owner.
    # inputs: Existing packet page arguments.
    # returns: Existing packet drill-down view model.
    # side_effects: Selected-project packet reads.
    # emitted_logs: Owner and Hub read logs.
    # error_behavior: Preserves packet-owner fallbacks and identity checks.
    # END_FUNCTION_CONTRACT
    async def _packet_page(
        self,
        project_key: str,
        packet_id: str,
        *,
        project_info: Mapping[str, Any] | None,
        tree_packet: Mapping[str, Any] | None,
        tab: str,
        run_id: str | None,
        stage_id: str | None,
        event: str | None,
        component: str | None,
        run_stage: str | None,
        trace_id: str | None,
        text: str | None,
        source: str | None,
        log_tail: int,
        artifact_path: str | None,
        file_root: str | None,
        file_path: str,
        git_ref: str | None,
        git_path: str | None,
    ) -> dict[str, Any]:
        return await self._packet.packet_page(
            project_key,
            packet_id,
            project_info=project_info,
            tree_packet=tree_packet,
            tab=tab,
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

    # START_FUNCTION_CONTRACT
    # name: _scope_rows_to_run
    # purpose: Preserve the historical private run-scoping seam.
    # inputs: rows — packet rows; run_id — optional selected run.
    # returns: Shallow-copied rows scoped to the selected run.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Malformed rows are skipped.
    # END_FUNCTION_CONTRACT
    def _scope_rows_to_run(self, rows: Any, run_id: str | None) -> list[dict[str, Any]]:
        return self._packet._scope_rows_to_run(rows, run_id)

    # START_FUNCTION_CONTRACT
    # name: _project_card
    # purpose: Preserve the historical selected-project card seam.
    # inputs: project_key — explicit registry key.
    # returns: Normalized project card.
    # side_effects: Bounded selected-project overview read.
    # emitted_logs: Hub-owned read logs.
    # error_behavior: Unknown project raises KeyError.
    # END_FUNCTION_CONTRACT
    async def _project_card(self, project_key: str) -> dict[str, Any]:
        return await self._project._project_card(project_key)

    # START_FUNCTION_CONTRACT
    # name: _read
    # purpose: Execute one explicit project-local GET through the Hub transport.
    # inputs: project_key, absolute API path and optional operation label.
    # returns: Internal result mapping with ok/payload/error fields.
    # side_effects: One bounded remote project API read.
    # emitted_logs: Hub-owned project error logs.
    # error_behavior: Transport errors are normalized; unknown project raises KeyError.
    # END_FUNCTION_CONTRACT
    async def _read(
        self,
        project_key: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        operation: str,
    ) -> dict[str, Any]:
        context = self._context(project_key)
        result = await self._hub._request(context, path, params=params, operation=operation)
        return {
            "ok": bool(result.ok),
            "payload": result.payload or {},
            "error": result.error or result.error_class,
            "error_class": result.error_class,
            "http_status": result.http_status,
            "headers": result.headers or {},
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
    # purpose: Preserve the historical card normalization seam.
    # inputs: Stage 03 project card mappings.
    # returns: Enriched cards in registry order.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Malformed rows are ignored.
    # END_FUNCTION_CONTRACT
    def _cards(self, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return self._project._cards(rows)

    # START_FUNCTION_CONTRACT
    # name: _context_info
    # purpose: Preserve the historical registry/card merge seam.
    # inputs: ProjectContext and optional remote card.
    # returns: Selector-safe project metadata.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Missing card fields use safe defaults.
    # END_FUNCTION_CONTRACT
    def _context_info(
        self,
        context: ProjectContext,
        card: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        return self._project._context_info(context, card)

    # START_FUNCTION_CONTRACT
    # name: _selector_projects
    # purpose: Preserve compact selector-row normalization.
    # inputs: Enriched project cards.
    # returns: Selector mappings in registry order.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _selector_projects(self, cards: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return self._project._selector_projects(cards)

    # START_FUNCTION_CONTRACT
    # name: _selector_current
    # purpose: Preserve current selector-row lookup by explicit project key.
    # inputs: projects — selector rows; project_key — selected key.
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
        return self._project._selector_current(projects, project_key)

    # START_FUNCTION_CONTRACT
    # name: _explorer_shell
    # purpose: Preserve the shared explorer-shell private seam.
    # inputs: project_key — explicit registry key.
    # returns: project/projects/current_project mapping.
    # side_effects: Bounded dashboard read.
    # emitted_logs: Hub-owned read logs.
    # error_behavior: Unknown project raises KeyError.
    # END_FUNCTION_CONTRACT
    async def _explorer_shell(self, project_key: str) -> dict[str, Any]:
        return await self._project.explorer_shell(project_key)

    # END_BLOCK_COMPATIBILITY
