# ############################################################################
# AI_HEADER: admin_control_center_page_service — global read-page owner
# ROLE: Composes Events, Logs and Search page view models from the accepted Hub
#       query boundary while retaining explicit project selector context.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build project-aware global and project-local Events, Logs and Search
#          view models for the Admin Control Center.
# inputs: Public AdminCrossProjectService, project shell and page filters.
# returns: Existing JSON-safe page dictionaries consumed by templates/routes.
# side_effects: Bounded Hub query reads and dashboard context reads.
# emitted_logs: Hub-owned query read logs.
# error_behavior: Unknown projects raise KeyError; partial query data remains
#                 visible with the existing errors and coverage fields.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminControlCenterPageService
#     methods:
#       - events_page
#       - logs_page
#       - search_page
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_helpers import _normalize_event
from grace_control.services.admin_control_center_project_shell import AdminControlCenterProjectShell
from grace_control.services.admin_cross_project_service import AdminCrossProjectService

_log = GraceLogger("admin_control_center")

_LOG_TAILS = (100, 500, 2000)
_LOG_SOURCES = (
    "all",
    "api",
    "worker",
    "supervisor",
    "structured",
    "packet_stdout",
    "packet_stderr",
    "agent",
    "stage_stdout",
    "stage_stderr",
    "acceptance",
    "browser",
    "visual",
    "merge",
    "recheck",
    "recovery",
    "stdout",
    "stderr",
)


# START_BLOCK_SERVICE
class AdminControlCenterPageService:
    """Own bounded Events, Logs and Search page composition."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind global page composition to explicit public Hub and shell
    #          collaborators.
    # inputs: hub — public cross-project read service; shell — dashboard and
    #         selector owner.
    # returns: None.
    # side_effects: None; no query is issued during construction.
    # emitted_logs: None.
    # error_behavior: Collaborator contract errors propagate at construction.
    # END_FUNCTION_CONTRACT
    def __init__(self, hub: AdminCrossProjectService, shell: AdminControlCenterProjectShell) -> None:
        self._hub = hub
        self._shell = shell

    # START_FUNCTION_CONTRACT
    # name: events_page
    # purpose: Build a project-aware canonical event page with complete payloads.
    # inputs: project selectors and optional entity/event filters.
    # returns: Event page view model with selector context and cursor fields.
    # side_effects: Bounded Hub event read and dashboard read.
    # emitted_logs: Hub-owned event read logs.
    # error_behavior: Unknown project raises KeyError; partial data remains visible.
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
        selected = (
            project_key
            if isinstance(project_key, Sequence) and not isinstance(project_key, str)
            else ([project_key] if project_key else None)
        )
        project_label = ",".join(str(value) for value in selected) if selected else ""
        data = await self._hub.query_events(
            project=selected,
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
        dashboard = await self._shell.dashboard()
        current = self._shell.selector_current(
            dashboard["projects"],
            project_key if isinstance(project_key, str) else None,
        )
        return {
            "projects": dashboard["projects"],
            "current_project": current,
            "events": [_normalize_event(row) for row in data.get("events", [])],
            "coverage": data.get("coverage", {}),
            "errors": data.get("errors", []),
            "filters": {
                "project": project_label,
                "entity_id": entity_id or "",
                "entity_type": entity_type or "",
                "event_type": event_type or "",
                "trace_id": trace_id or "",
                "since": since or "",
                "until": until or "",
                "text": text or "",
                "limit": data.get("limit", limit),
                "offset": data.get("offset", offset),
                "cursor": cursor or "",
            },
            "next_cursor": data.get("next_cursor"),
            "total": data.get("total"),
            "partial": data.get("partial", False),
            "entity_id": entity_id or "",
            "entity_type": entity_type or "",
            "event_type": event_type or "",
        }

    # START_FUNCTION_CONTRACT
    # name: logs_page
    # purpose: Build a project-aware bounded Logs view from the Hub log API.
    # inputs: project selectors and source/identity/filter/cursor arguments.
    # returns: Logs page view model with filter and pagination fields.
    # side_effects: Bounded Hub log read and dashboard read.
    # emitted_logs: Hub-owned log read logs.
    # error_behavior: Invalid regex/cursor behavior remains owned by the Hub.
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
        selected = (
            project_key
            if isinstance(project_key, Sequence) and not isinstance(project_key, str)
            else ([project_key] if project_key else None)
        )
        project_label = ",".join(str(value) for value in selected) if selected else ""
        data = await self._hub.query_logs(
            project=selected,
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
        )
        dashboard = await self._shell.dashboard()
        return {
            "projects": dashboard["projects"],
            "current_project": self._shell.selector_current(
                dashboard["projects"],
                project_key if isinstance(project_key, str) else None,
            ),
            "logs": data.get("logs", []),
            "coverage": data.get("coverage", {}),
            "errors": data.get("errors", []),
            "filters": {
                "project": project_label,
                "source": source or "all",
                "worker": worker or "",
                "packet": packet or "",
                "run": run or "",
                "stage": stage or "",
                "contains": contains or "",
                "level": level or "",
                "trace_id": trace_id or "",
                "regex": regex or "",
                "since": since or "",
                "until": until or "",
            },
            "source_options": _LOG_SOURCES,
            "tail_options": _LOG_TAILS,
            "tail": data.get("limit", tail),
            "cursor": cursor or "",
            "next_cursor": data.get("next_cursor"),
            "partial": data.get("partial", False),
            "follow": bool(follow),
            "wrap": bool(wrap),
            "contains": contains or "",
            "level": level or "",
        }

    # START_FUNCTION_CONTRACT
    # name: search_page
    # purpose: Build project-aware search results with canonical Hub targets.
    # inputs: query — search text; project_key — optional explicit project key.
    # returns: Search page view model.
    # side_effects: Bounded Hub search and dashboard reads.
    # emitted_logs: Hub-owned search read logs.
    # error_behavior: Unknown project raises KeyError; errors remain visible.
    # END_FUNCTION_CONTRACT
    async def search_page(
        self,
        query: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        selected = [project_key] if project_key else None
        data = await self._hub.search(query, project=selected, limit=200)
        dashboard = await self._shell.dashboard()
        return {
            "projects": dashboard["projects"],
            "current_project": self._shell.selector_current(dashboard["projects"], project_key),
            "results": data.get("results", []),
            "errors": data.get("errors", []),
            "query": query,
        }


# END_BLOCK_SERVICE
