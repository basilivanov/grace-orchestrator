# ############################################################################
# AI_HEADER: admin_control_center_project_shell — shared project selector shell
# ROLE: Owns dashboard/card normalization and selector context shared by the
#       project, explorer and page Control Center services.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build the shared project/dashboard shell without depending on any
#          Control Center child service.
# inputs: AdminProjectAccess and the public cross-project overview service.
# returns: JSON-safe dashboard, selector and project-shell dictionaries.
# side_effects: Bounded public Hub overview reads; no project-local mutation.
# emitted_logs: admin_control_center_read_error for isolated dashboard failures.
# error_behavior: Unknown project keys raise KeyError; invalid filters normalize
#                 to all and malformed overview rows are isolated.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminControlCenterProjectShell
#     methods:
#       - contexts
#       - dashboard
#       - project_card
#       - cards
#       - context_info
#       - selector_projects
#       - selector_current
#       - explorer_shell
#       - mask
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from grace_control.config.project_registry import ProjectContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_helpers import (
    _card_sort_key,
    _first_value,
    _has_card_attention,
    _mask_secrets,
    _matches_dashboard_filter,
    _sum_states,
    _waits_from,
)
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.services.admin_project_access import AdminProjectAccess

_log = GraceLogger("admin_control_center_project_shell")

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
class AdminControlCenterProjectShell:
    """Own shared dashboard and project-selector composition."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind shared selector composition to explicit access and Hub
    #          overview collaborators.
    # inputs: access — project context/read boundary; hub — public overview
    #         service.
    # returns: None.
    # side_effects: None; no overview request during construction.
    # emitted_logs: None.
    # error_behavior: None beyond collaborator contract errors.
    # END_FUNCTION_CONTRACT
    def __init__(self, access: AdminProjectAccess, hub: AdminCrossProjectService) -> None:
        self._access = access
        self._hub = hub

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
        return self._access.contexts()

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
            overview = await self._hub.get_projects_overview()
        except Exception as exc:
            _log.error("admin_control_center_read_error", operation="dashboard")
            overview = {"projects": [], "errors": [{"error": str(exc)[:200]}]}
        cards = self.cards(overview.get("projects", []))
        visible = [card for card in cards if _matches_dashboard_filter(card, selected_filter)]
        visible.sort(key=_card_sort_key)
        return {
            "filter": selected_filter,
            "filters": _DASHBOARD_FILTERS,
            "projects": self.selector_projects(cards),
            "cards": visible,
            "coverage": overview.get("coverage", {}),
            "errors": overview.get("errors", []),
            "attention": overview.get("attention", []),
            "fetched_at": overview.get("fetched_at"),
        }

    # START_FUNCTION_CONTRACT
    # name: project_card
    # purpose: Read and normalize one selected project's dashboard card.
    # inputs: project_key — explicit registry key.
    # returns: Normalized card or an isolated offline card.
    # side_effects: Bounded selected-project overview read.
    # emitted_logs: Hub-owned read logs.
    # error_behavior: Unknown project raises KeyError.
    # END_FUNCTION_CONTRACT
    async def project_card(self, project_key: str) -> dict[str, Any]:
        overview = await self._hub.get_projects_overview(project_key)
        cards = self.cards(overview.get("projects", []))
        if cards:
            return cards[0]
        context = self._access.context(project_key)
        return self.context_info(context, {"status": "offline", "error": "Project overview unavailable."})

    # START_FUNCTION_CONTRACT
    # name: cards
    # purpose: Enrich public Hub project cards with immutable registry metadata.
    # inputs: Public Hub project card mappings.
    # returns: Enriched cards in registry order.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Malformed rows are ignored while registry cards remain.
    # END_FUNCTION_CONTRACT
    def cards(self, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
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
    # name: context_info
    # purpose: Merge immutable registry identity with an optional remote card.
    # inputs: context — ProjectContext; card — optional remote card.
    # returns: Selector-safe project metadata mapping.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Missing card fields use safe defaults.
    # END_FUNCTION_CONTRACT
    def context_info(
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
    # name: selector_projects
    # purpose: Return compact status-bearing selector rows.
    # inputs: Enriched project cards.
    # returns: Selector mappings in registry order.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def selector_projects(self, cards: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
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
    # name: selector_current
    # purpose: Resolve the current selector row by explicit project key.
    # inputs: projects — selector rows; project_key — optional selected key.
    # returns: Matching row or None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def selector_current(
        self,
        projects: Sequence[Mapping[str, Any]],
        project_key: str | None,
    ) -> dict[str, Any] | None:
        if not project_key:
            return None
        return next((dict(row) for row in projects if row.get("project_key") == project_key), None)

    # START_FUNCTION_CONTRACT
    # name: explorer_shell
    # purpose: Build shared project selector context for project-scoped
    #          explorers.
    # inputs: project_key — explicit registry key.
    # returns: project/projects/current_project mapping.
    # side_effects: Bounded dashboard read through the public Hub overview.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Unknown project raises KeyError.
    # END_FUNCTION_CONTRACT
    async def explorer_shell(self, project_key: str) -> dict[str, Any]:
        context = self._access.context(project_key)
        dashboard = await self.dashboard()
        card = next(
            (row for row in dashboard["cards"] if row.get("project_key") == project_key),
            None,
        )
        if card is None:
            card = await self.project_card(project_key)
        return {
            "project": self.context_info(context, card),
            "projects": dashboard["projects"],
            "current_project": self.selector_current(dashboard["projects"], project_key),
        }

    # START_FUNCTION_CONTRACT
    # name: mask
    # purpose: Apply the existing operator-data masking boundary to a value.
    # inputs: value — JSON-like project response.
    # returns: Masked JSON-safe value.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Masking degrades malformed values safely.
    # END_FUNCTION_CONTRACT
    def mask(self, value: Any) -> Any:
        return _mask_secrets(value)


# END_BLOCK_SERVICE
