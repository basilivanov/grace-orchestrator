# ############################################################################
# AI_HEADER: admin_control_center — bounded project-aware control-center facade
# ROLE: Preserves the public AdminControlCenterService import, constructor and
#       page method signatures while composing explicit focused collaborators.
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
)
from grace_control.services.admin_control_center_packet_service import AdminControlCenterPacketService
from grace_control.services.admin_control_center_page_service import AdminControlCenterPageService
from grace_control.services.admin_control_center_project_service import AdminControlCenterProjectService
from grace_control.services.admin_control_center_project_shell import (
    _PACKET_TABS,
    AdminControlCenterProjectShell,
)
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.services.admin_mutation_service import AdminMutationService
from grace_control.services.admin_project_access import AdminProjectAccess

_log = GraceLogger("admin_control_center")


# START_BLOCK_SERVICE
class AdminControlCenterService:
    """Stable composition root and public facade for Control Center pages."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Validate the accepted Hub and construct the complete acyclic
    #          Control Center collaborator graph.
    # inputs: hub — configured AdminCrossProjectService.
    # returns: None.
    # side_effects: Initializes an app-scoped project access cache and focused
    #               collaborators; no remote request is made during construction.
    # emitted_logs: None.
    # error_behavior: Raises TypeError when hub is not an AdminCrossProjectService.
    # END_FUNCTION_CONTRACT
    def __init__(self, hub: AdminCrossProjectService) -> None:
        if not isinstance(hub, AdminCrossProjectService):
            raise TypeError("AdminControlCenterService requires the Admin Hub service")
        self._hub = hub
        self._access = AdminProjectAccess(hub.transport)
        self._mutation = AdminMutationService(hub)
        self._shell = AdminControlCenterProjectShell(self._access, hub)
        self._explorer = AdminControlCenterExplorerService(
            self._access,
            self._shell,
            self._mutation,
        )
        self._packet = AdminControlCenterPacketService(
            self._access,
            self._explorer,
            self._mutation,
            _PACKET_TABS,
        )
        self._project = AdminControlCenterProjectService(
            self._access,
            self._shell,
            self._packet,
        )
        self._pages = AdminControlCenterPageService(hub, self._shell)

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
        return self._access.contexts()

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
        return await self._shell.dashboard(filter_name)

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
    # emitted_logs: Owner and Hub read logs.
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
    # emitted_logs: Owner and Hub read logs.
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
    # emitted_logs: Explorer and Hub read logs.
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
    # emitted_logs: Explorer and Hub Git read logs.
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
    # emitted_logs: Explorer and mutation service logs.
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
