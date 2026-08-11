# ############################################################################
# AI_HEADER: admin_control_center — project-aware Jinja2/HTMX control center
# ROLE: Builds project-scoped read view models and binds the explicit Stage 06
#       OpenAPI control-mode result. Every remote read/mutation is routed through
#       the accepted Hub boundary with an explicit registry project key.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide project-aware dashboard, entity drill-down, timeline,
#          pipeline, system and explorer models, plus a bounded discovered
#          OpenAPI mutation view when server control mode is enabled.
# inputs: AdminCrossProjectService and explicit project/entity/tab selectors.
# returns: JSON-safe view-model dictionaries for server-rendered templates.
# side_effects: Bounded reads and one delegated project-local mutation through
#               AdminMutationService; never changes process-global settings or
#               opens another project's DB.
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
#       - maintenance_page
#       - events_page
#       - logs_page
#       - files_page
#       - git_page
#       - api_page
#       - search_page
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from grace_control.config.project_registry import ProjectContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_explorer_helpers import (
    _artifact_kind,
    _json_preview,
    _json_query_params,
    _lease_views,
    _normalize_artifacts,
    _normalize_worktrees,
    _openapi_operations,
    _openapi_request,
    _safe_relative_path,
    _stale_base_view,
)
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
from grace_control.services.admin_mutation_service import AdminMutationService

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


# START_FUNCTION_CONTRACT
# name: _json_body
# purpose: Parse a bounded OpenAPI mutation body object for the Control Center.
# inputs: value — optional JSON object string.
# returns: (mapping, error) pair.
# side_effects: None.
# error_behavior: Arrays, nested oversized values and malformed JSON reject.
# END_FUNCTION_CONTRACT
def _json_body(value: str | None) -> tuple[dict[str, Any], str | None]:
    if not value:
        return {}, None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, "API_BODY_INVALID"
    if not isinstance(parsed, Mapping) or len(parsed) > 32 or len(value) > 64 * 1024:
        return {}, "API_BODY_INVALID"
    return dict(parsed), None


# START_FUNCTION_CONTRACT
# name: _json_confirmation
# purpose: Parse explicit server-enforced Control Center confirmation JSON.
# inputs: value — optional JSON object/string.
# returns: confirmation mapping/string or error.
# side_effects: None.
# error_behavior: Missing/malformed values reject before a remote mutation.
# END_FUNCTION_CONTRACT
def _json_confirmation(value: str | None) -> tuple[dict[str, Any] | str, str | None]:
    if not value:
        return {}, "CONFIRMATION_REQUIRED"
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, "CONFIRMATION_INVALID"
    if isinstance(parsed, Mapping):
        return dict(parsed), None
    if isinstance(parsed, str):
        return parsed, None
    return {}, "CONFIRMATION_INVALID"
_LOG_TAILS = (100, 500, 2000)
_OPENAPI_CACHE_TTL_SECONDS = 5.0


# START_BLOCK_SERVICE
class AdminControlCenterService:
    """Compose explicit project-local read models for the Stage 04 UI."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the UI read model to the accepted cross-project Hub service.
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
        source: str | None = None,
        log_tail: int = 500,
        artifact_path: str | None = None,
        file_root: str | None = None,
        file_path: str = "",
        git_ref: str | None = None,
        git_path: str | None = None,
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
            "capabilities": {},
            "supervisor": {},
            "leases": {"ordinary": [], "parallel": [], "merge": []},
            "error": None,
        }
        if not context.enabled:
            model["error"] = "Project is disabled; no remote read was attempted."
            return model
        health_result, workers_result, diagnostics_result, capabilities_result, supervisor_result = await asyncio.gather(
            self._read(project_key, "/api/admin/system/health", operation="health"),
            self._read(project_key, "/api/admin/system/workers", operation="workers"),
            self._read(project_key, "/api/diagnostics/state", operation="diagnostics"),
            self._read(project_key, "/api/admin/capabilities", operation="capabilities"),
            self._read(project_key, "/api/admin/lifecycle/status", operation="supervisor_status"),
        )
        health = _unwrap(health_result.get("payload")) if health_result.get("ok") else {}
        workers = _unwrap(workers_result.get("payload")) if workers_result.get("ok") else {}
        diagnostics = _unwrap(diagnostics_result.get("payload")) if diagnostics_result.get("ok") else {}
        capabilities = _unwrap(capabilities_result.get("payload")) if capabilities_result.get("ok") else {}
        model["health"] = _mask_secrets(health)
        model["workers"] = workers.get("workers", []) if isinstance(workers, Mapping) else []
        model["diagnostics"] = _mask_secrets(diagnostics)
        model["config"] = _mask_secrets(_effective_config(health, diagnostics))
        model["capabilities"] = _mask_secrets(capabilities)
        model["supervisor"] = _mask_secrets(_unwrap(supervisor_result.get("payload"))) if supervisor_result.get("ok") else {}
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
    # purpose: Build a selected-project dry-run/snapshot maintenance page from
    #          the narrow local maintenance API.
    # inputs: project_key — explicit immutable registry key.
    # returns: Maintenance view model with snapshot/plan/error fields.
    # side_effects: One selected-project bounded GET plus dashboard context.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Unknown project raises KeyError; remote gaps stay visible.
    # END_FUNCTION_CONTRACT
    async def maintenance_page(self, project_key: str) -> dict[str, Any]:
        shell = await self._explorer_shell(project_key)
        result = await self._read(
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
        selected = project_key if isinstance(project_key, Sequence) and not isinstance(project_key, str) else ([project_key] if project_key else None)
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
        dashboard = await self.dashboard()
        current = self._selector_current(dashboard["projects"], project_key if isinstance(project_key, str) else None)
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
    # inputs: project_key — optional explicit key; contains/level — optional
    #          server-side log filters.
    # returns: Logs page view model with isolated errors.
    # side_effects: Bounded Hub log reads.
    # emitted_logs: Hub-owned cross-project read logs.
    # error_behavior: Invalid regex/cursor errors propagate to the router as 400.
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
        selected = project_key if isinstance(project_key, Sequence) and not isinstance(project_key, str) else ([project_key] if project_key else None)
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
        dashboard = await self.dashboard()
        return {
            "projects": dashboard["projects"],
            "current_project": self._selector_current(dashboard["projects"], project_key if isinstance(project_key, str) else None),
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
    # name: files_page
    # purpose: Build a project-scoped named-root filesystem explorer with
    #          bounded directory, stat and preview reads.
    # inputs: project_key — explicit registry key; root/path — advertised
    #          logical root and relative directory; preview_path — optional
    #          relative file to preview; tail — optional bounded text tail.
    # returns: Files view model with roots, entries, preview and typed errors.
    # side_effects: Reads only selected project /api/admin/fs endpoints.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Unsafe paths are rejected before a remote read; typed
    #                 project filesystem errors remain visible in the model.
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
        shell = await self._explorer_shell(project_key)
        model: dict[str, Any] = {
            **shell,
            "root": root or "",
            "path": path or "",
            "entries": [],
            "roots": [],
            "preview": None,
            "stat": None,
            "preview_path": preview_path or "",
            "path_error": None,
            "error": None,
            "source": "FILE",
            "capability_available": False,
        }
        context = self._context(project_key)
        if not context.enabled:
            model["error"] = "Project is disabled; filesystem capability was not requested."
            return model
        roots_result = await self._read(project_key, "/api/admin/fs/roots", operation="filesystem_roots")
        roots_payload = _unwrap(roots_result.get("payload")) if roots_result.get("ok") else {}
        roots = roots_payload.get("roots", []) if isinstance(roots_payload, Mapping) else []
        if not roots_result.get("ok"):
            model["error"] = _capability_message(roots_result)
            model["error_class"] = roots_result.get("error_class")
            model["http_status"] = roots_result.get("http_status")
            return model
        model["capability_available"] = True
        model["roots"] = [dict(item) for item in roots if isinstance(item, Mapping)]
        root_names = [str(item.get("root")) for item in model["roots"] if item.get("root")]
        selected_root = str(root or (root_names[0] if root_names else ""))
        model["root"] = selected_root
        if selected_root not in root_names:
            model["error"] = "The selected filesystem root is not advertised by this project."
            model["error_class"] = "ROOT_NOT_FOUND"
            return model
        safe, clean_path, path_error = _safe_relative_path(path)
        if not safe:
            model["path_error"] = {"code": path_error, "message": "Only a relative logical path is allowed."}
            return model
        model["path"] = clean_path
        listing_result = await self._read(
            project_key,
            "/api/admin/fs/list",
            params={"root": selected_root, "path": clean_path},
            operation="filesystem_list",
        )
        listing = _unwrap(listing_result.get("payload")) if listing_result.get("ok") else {}
        if listing_result.get("ok"):
            model["entries"] = [
                {**dict(entry), "source": "FILE"}
                for entry in listing.get("entries", [])
                if isinstance(entry, Mapping)
            ]
            model["truncated"] = bool(listing.get("truncated"))
        else:
            model["error"] = _capability_message(listing_result)
            model["error_class"] = listing_result.get("error_class")
            model["http_status"] = listing_result.get("http_status")
        if preview_path:
            preview_safe, clean_preview, preview_error = _safe_relative_path(preview_path)
            model["preview_path"] = clean_preview if preview_safe else str(preview_path)
            if not preview_safe:
                model["path_error"] = {"code": preview_error, "message": "Only a relative logical path is allowed."}
                return model
            endpoint = "/api/admin/fs/tail" if tail and tail > 0 else "/api/admin/fs/file"
            params: dict[str, Any] = {"root": selected_root, "path": clean_preview}
            stat_result = await self._read(
                project_key,
                "/api/admin/fs/stat",
                params={"root": selected_root, "path": clean_preview},
                operation="filesystem_stat",
            )
            if stat_result.get("ok"):
                model["stat"] = {**_unwrap(stat_result.get("payload")), "source": "FILE"}
            if tail and tail > 0:
                params["lines"] = min(int(tail), 1000)
            else:
                params["max_bytes"] = 512 * 1024
            preview_result = await self._read(
                project_key,
                endpoint,
                params=params,
                operation="filesystem_preview",
            )
            if preview_result.get("ok"):
                preview = _unwrap(preview_result.get("payload"))
                preview["source"] = "FILE"
                model["preview"] = preview
            else:
                model["error"] = _capability_message(preview_result)
                model["error_class"] = preview_result.get("error_class")
                model["http_status"] = preview_result.get("http_status")
        return model

    # START_FUNCTION_CONTRACT
    # name: git_page
    # purpose: Build a bounded project/packet Git explorer from explicit Stage
    #          02 read APIs, including display-only worktree classifications.
    # inputs: project_key; optional packet and safe ref/path selectors.
    # returns: Git repository, worktree, packet metadata, changed-file and diff
    #          view model with source attribution.
    # side_effects: Reads only selected project Git APIs.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Git validation errors remain typed in the view model.
    # END_FUNCTION_CONTRACT
    async def git_page(
        self,
        project_key: str,
        *,
        packet: Mapping[str, Any] | None = None,
        ref: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        shell = await self._explorer_shell(project_key)
        model: dict[str, Any] = {
            **shell,
            "repository": {},
            "worktrees": [],
            "changed_files": [],
            "diff_stat": {},
            "diff": {},
            "packet_git": {},
            "ref": ref or "",
            "path": path or "",
            "error": None,
            "source": "GIT",
        }
        context = self._context(project_key)
        if not context.enabled:
            model["error"] = "Project is disabled; Git capability was not requested."
            return model
        repository_result, worktree_result, changed_result = await asyncio.gather(
            self._read(project_key, "/api/admin/git/repository", operation="git_repository"),
            self._read(project_key, "/api/admin/git/worktrees", operation="git_worktrees"),
            self._read(
                project_key,
                "/api/admin/git/changed-files",
                params={"ref": ref} if ref else None,
                operation="git_changed_files",
            ),
        )
        if repository_result.get("ok"):
            model["repository"] = _mask_secrets(_unwrap(repository_result.get("payload")))
            if isinstance(model["repository"], Mapping):
                repository = dict(model["repository"])
                repo_root = str(repository.get("repo_root") or "")
                repository["repo_display"] = repo_root.rstrip("/").rsplit("/", 1)[-1] if repo_root else "unknown"
                model["repository"] = repository
        if worktree_result.get("ok"):
            worktrees_payload = _unwrap(worktree_result.get("payload"))
            model["worktrees"] = _normalize_worktrees(worktrees_payload, packet)
        if changed_result.get("ok"):
            changed_payload = _unwrap(changed_result.get("payload"))
            model["changed_files"] = [
                {**dict(row), "source": "GIT"}
                for row in changed_payload.get("changed_files", changed_payload.get("data", []))
                if isinstance(row, Mapping)
            ]
        selected_path_allowed = not path or not changed_result.get("ok") or any(
            str(row.get("path") or "") == str(path)
            for row in model["changed_files"]
        )
        if path and changed_result.get("ok") and not selected_path_allowed:
            model["error"] = "GIT_PATH_NOT_CHANGED"
            model["error_class"] = "GIT_PATH_NOT_CHANGED"
            stat_result: dict[str, Any] = {"ok": False, "error": "GIT_PATH_NOT_CHANGED"}
            diff_result: dict[str, Any] = {"ok": False, "error": "GIT_PATH_NOT_CHANGED"}
        else:
            stat_result, diff_result = await asyncio.gather(
                self._read(
                    project_key,
                    "/api/admin/git/diff-stat",
                    params={"ref": ref, "path": path} if ref or path else None,
                    operation="git_diff_stat",
                ),
                self._read(
                    project_key,
                    "/api/admin/git/diff",
                    params={"ref": ref, "path": path} if ref or path else None,
                    operation="git_diff",
                ),
            )
        if stat_result.get("ok"):
            model["diff_stat"] = {**_unwrap(stat_result.get("payload")), "source": "GIT"}
        if diff_result.get("ok"):
            model["diff"] = {**_unwrap(diff_result.get("payload")), "source": "GIT"}
        failures = [result for result in (repository_result, worktree_result, changed_result, stat_result, diff_result) if not result.get("ok")]
        if path and changed_result.get("ok") and not selected_path_allowed:
            failures = []
        if failures:
            model["error"] = _capability_message(failures[0])
            model["error_class"] = failures[0].get("error_class")
            model["http_status"] = failures[0].get("http_status")
        packet_map = packet if isinstance(packet, Mapping) else {}
        model["packet_git"] = {
            "branch": packet_map.get("branch") or packet_map.get("branch_name") or "unknown",
            "commit": packet_map.get("commit_sha") or packet_map.get("head_sha") or packet_map.get("merge_commit") or "unknown",
            "base_sha": packet_map.get("base_sha"),
            "integration_base_sha": packet_map.get("integration_base_sha"),
            "merge_commit": packet_map.get("merge_commit"),
            "merge_status": packet_map.get("merge_status") or packet_map.get("integration_recheck"),
            "source": "API",
        }
        return model

    # START_FUNCTION_CONTRACT
    # name: api_page
    # purpose: Discover a selected project's OpenAPI operations and execute an
    #          exact GET or authorized mutation only when explicitly requested.
    # inputs: project_key; path — exact discovered path; execute — execution
    #          flag; params_json/body_json/confirmation_json — bounded JSON;
    #          control_mode — explicit mutation gate; allow_mutation — true
    #          only for an authorized POST UI route.
    # returns: API documentation plus optional bounded response/error DTO.
    # side_effects: Reads selected project /openapi.json and, for an explicitly
    #                 authorized POST UI call, one exact discovered mutation.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Mutation execution and arbitrary/non-discovered paths are
    #                 rejected without a project request.
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
        shell = await self._explorer_shell(project_key)
        model: dict[str, Any] = {
            **shell,
            "document": {},
            "operations": [],
            "selected_path": path or "",
            "request_path": "",
            "request_params": {},
            "params_display": "",
            "body_display": "",
            "confirmation_display": "",
            "response": None,
            "response_status": None,
            "response_headers": {},
            "response_error": None,
            "mutation_execution_disabled": not control_mode,
            "control_mode": bool(control_mode),
            "selected_method": str(method or "GET").upper(),
            "mutation_response": None,
            "execution_requested": bool(execute),
            "source": "API",
        }
        context = self._context(project_key)
        if not context.enabled:
            model["response_error"] = "Project is disabled; API discovery was not requested."
            return model
        openapi_result = await self._cached_openapi(project_key)
        if not openapi_result.get("ok"):
            model["response_error"] = _capability_message(openapi_result)
            model["error_class"] = openapi_result.get("error_class")
            return model
        document = _unwrap(openapi_result.get("payload"))
        operations, get_paths = _openapi_operations(document)
        model["document"] = _mask_secrets(document)
        model["operations"] = _mask_secrets(operations)
        if not execute:
            return model
        selected_path = str(path or "")
        selected_method = str(method or "GET").upper()
        operation = next(
            (row for row in operations if row.get("method") == selected_method and row.get("path") == selected_path),
            None,
        )
        if selected_method == "GET" and selected_path not in get_paths:
            operation = None
        if operation is None:
            model["response_error"] = "API_PATH_NOT_DISCOVERED"
            return model
        params, params_error = _json_query_params(params_json)
        if params_error:
            model["response_error"] = params_error
            return model
        model["params_display"] = json.dumps(
            _mask_secrets(params), ensure_ascii=False, sort_keys=True,
        )
        request_path, query_params, request_error = _openapi_request(
            selected_path,
            operation,
            params,
        )
        if request_error:
            model["response_error"] = request_error
            return model
        model["request_path"] = request_path
        model["request_params"] = _mask_secrets(query_params)
        if selected_method != "GET":
            if not control_mode:
                model["response_error"] = "API_CONTROL_MODE_REQUIRED"
                return model
            if not allow_mutation:
                model["response_error"] = None
                return model
            body, body_error = _json_body(body_json)
            if body_error:
                model["response_error"] = body_error
                return model
            model["body_display"] = json.dumps(
                _mask_secrets(body), ensure_ascii=False, sort_keys=True,
            )
            confirmation, confirmation_error = _json_confirmation(confirmation_json)
            if confirmation_error:
                model["response_error"] = confirmation_error
                return model
            model["confirmation_display"] = json.dumps(
                _mask_secrets(confirmation), ensure_ascii=False, sort_keys=True,
            )
            mutation = await AdminMutationService(self._hub).execute_openapi(
                project_key,
                path=selected_path,
                method=selected_method,
                confirmation=confirmation,
                parameters={**params},
                body=body,
                actor=actor,
            )
            model["mutation_response"] = mutation
            model["response_status"] = mutation.get("status")
            if mutation.get("ok"):
                model["response"] = {
                    "body": mutation.get("response") or {},
                    "headers": {},
                    "request_path": request_path,
                    "request_params": _mask_secrets(query_params),
                    "source": "API",
                    "mutation": True,
                }
            else:
                model["response_error"] = mutation.get("display_message") or mutation.get("error") or mutation.get("error_code")
            return model
        result = await self._read(
            project_key,
            request_path,
            params=query_params,
            operation="api_explorer_get",
        )
        model["response_status"] = result.get("http_status")
        model["response_headers"] = result.get("headers") or {}
        if result.get("ok"):
            model["response"] = {
                "body": _mask_secrets(_unwrap(result.get("payload"))),
                "headers": result.get("headers") or {},
                "request_path": request_path,
                "request_params": _mask_secrets(query_params),
                "source": "API",
                "truncated": False,
            }
        else:
            model["response_error"] = result.get("error") or result.get("error_class")
        return model

    # START_FUNCTION_CONTRACT
    # name: _cached_openapi
    # purpose: Read and project-key-cache a successful OpenAPI document for a
    #          short interval so repeated explorer renders do not fan out a
    #          full schema request on every page refresh.
    # inputs: project_key — explicit immutable registry key.
    # returns: Normalized project read result for `/openapi.json`.
    # side_effects: At most one bounded project API GET per project per TTL.
    # emitted_logs: Hub-owned project read logs on cache misses.
    # error_behavior: Transport/capability errors are returned uncached.
    # END_FUNCTION_CONTRACT
    async def _cached_openapi(self, project_key: str) -> dict[str, Any]:
        now = time.monotonic()
        cached = self._openapi_cache.get(project_key)
        if cached is not None and now - cached[0] < _OPENAPI_CACHE_TTL_SECONDS:
            return cached[1]
        result = await self._read(project_key, "/openapi.json", operation="openapi")
        if result.get("ok"):
            self._openapi_cache[project_key] = (now, result)
        return result

    # START_FUNCTION_CONTRACT
    # name: _explorer_shell
    # purpose: Build shared project selector context for project-scoped
    #          explorer pages without changing request/global project state.
    # inputs: project_key — explicit registry key.
    # returns: project/projects/current_project mapping.
    # side_effects: Bounded dashboard read through the Hub.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Unknown project raises KeyError.
    # END_FUNCTION_CONTRACT
    async def _explorer_shell(self, project_key: str) -> dict[str, Any]:
        context = self._context(project_key)
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
        evidence: dict[str, Any] = {}
        evidence_raw: dict[str, Any] = {}
        artifacts: dict[str, Any] = {"artifacts": [], "truncated": False}
        artifact_preview: dict[str, Any] | None = None
        packet_logs: dict[str, Any] = {}
        packet_files: dict[str, Any] = {}
        packet_git: dict[str, Any] = {}
        run_raw: dict[str, Any] = {}
        stage_raw: dict[str, Any] = {}
        selected_run: dict[str, Any] | None = None
        selected_stage: dict[str, Any] | None = None

        if tab in {"spec", "pipeline", "stages", "evidence", "logs", "artifacts", "files", "git", "raw"}:
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
        if tab in {"runs", "evidence", "logs", "artifacts", "files", "raw", "git"} or run_id:
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
            if selected_run is None and runs and not run_id:
                selected_run = runs[-1]
        if tab in {"stages", "pipeline", "evidence", "logs", "raw"} and stage_id:
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
                    stage_raw = _mask_secrets(_unwrap(stage_result.get("payload")))
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

        evidence_run = selected_run
        if tab == "evidence" and evidence_run:
            evidence_result = await self._read(
                project_key,
                f"/api/admin/packet/{packet_id}/runs/{evidence_run.get('id')}/evidence",
                operation="evidence",
            )
            evidence_payload = _mask_secrets(_unwrap(evidence_result.get("payload"))) if evidence_result.get("ok") else {
                "available": False,
                "message": _capability_message(evidence_result),
            }
            if isinstance(evidence_payload, Mapping):
                evidence_raw = dict(evidence_payload)
            evidence = evidence_payload
            if isinstance(evidence, Mapping):
                evidence = dict(evidence)
                evidence.setdefault("available", True)
                evidence.setdefault("source", "API")
        elif tab == "evidence":
            evidence = {"available": False, "message": "Select a run to inspect evidence.", "source": "API"}

        if tab == "logs":
            log_run = selected_run
            selected_source = str(source or "all")
            if stage_id:
                stage_selector = (
                    selected_stage.get("stage_key")
                    if isinstance(selected_stage, Mapping)
                    else None
                ) or stage_id
                logs_result = await self._read(
                    project_key,
                    f"/api/admin/packet/{quote(str(packet_id), safe='-_.~')}/stages/{quote(str(stage_selector), safe='-_.~')}/logs",
                    params={"stream": "all", "tail": min(max(int(log_tail), 1), 2000)},
                    operation="packet_stage_logs",
                )
            elif log_run:
                stream = selected_source if selected_source in {"stdout", "stderr", "agent"} else "stderr"
                logs_result = await self._read(
                    project_key,
                    f"/api/admin/packet/{packet_id}/runs/{log_run.get('id')}/logs",
                    params={"stream": stream, "tail": min(max(int(log_tail), 1), 2000)},
                    operation="packet_run_logs",
                )
            else:
                logs_result = await self._read(
                    project_key,
                    f"/api/admin/packet/{packet_id}/logs/aggregated",
                    params={"sources": selected_source or "all", "tail": min(max(int(log_tail), 1), 2000)},
                    operation="packet_logs",
                )
            packet_logs = _mask_secrets(_unwrap(logs_result.get("payload"))) if logs_result.get("ok") else {
                "available": False,
                "message": _capability_message(logs_result),
            }
            if isinstance(packet_logs, Mapping):
                packet_logs = dict(packet_logs)
                packet_logs.setdefault("available", True)
                packet_logs.setdefault("source", selected_source or "all")
                packet_logs.setdefault("source_label", "API")
                packet_logs.setdefault("truncated", bool(packet_logs.get("truncated", False)))
                packet_logs.setdefault("tail", min(max(int(log_tail), 1), 2000))
                packet_logs.setdefault("follow", False)
                packet_logs.setdefault("wrap", False)

        if tab == "artifacts" and selected_run:
            artifact_result = await self._read(
                project_key,
                f"/api/admin/packet/{packet_id}/runs/{selected_run.get('id')}/artifacts",
                operation="artifacts",
            )
            if artifact_result.get("ok"):
                artifacts = _normalize_artifacts(_unwrap(artifact_result.get("payload")))
                artifacts["source"] = "API"
            else:
                artifacts = {"artifacts": [], "truncated": False, "error": _capability_message(artifact_result), "source": "API"}
            if artifact_path:
                preview_result = await self._read(
                    project_key,
                    f"/api/admin/packet/{packet_id}/runs/{selected_run.get('id')}/artifacts/preview",
                    params={"path": artifact_path, "max_bytes": 512 * 1024},
                    operation="artifact_preview",
                )
                if preview_result.get("ok"):
                    artifact_preview = _mask_secrets(_unwrap(preview_result.get("payload")))
                    if isinstance(artifact_preview, Mapping):
                        artifact_preview = dict(artifact_preview)
                        kind, previewable, category = _artifact_kind(
                            artifact_path,
                            artifact_preview.get("mime"),
                            bool(artifact_preview.get("binary")),
                            artifact_preview.get("size"),
                        )
                        artifact_preview.update({
                            "path": artifact_path,
                            "kind": kind,
                            "category": category,
                            "previewable": previewable,
                            "source": "API",
                            "json_structured": _json_preview(artifact_preview.get("content"), kind),
                        })
                else:
                    artifact_preview = {"path": artifact_path, "error": _capability_message(preview_result), "source": "API"}
        elif tab == "artifacts":
            artifacts = {"artifacts": [], "truncated": False, "message": "Select a run to inspect artifacts.", "source": "API"}

        if tab == "files":
            packet_files = await self.files_page(
                project_key,
                root=file_root,
                path=file_path,
                preview_path=file_path if file_path and not file_path.endswith("/") else None,
            )

        if tab == "raw" and selected_run:
            run_raw_result = await self._read(
                project_key,
                f"/api/admin/packet/{packet_id}/runs/{selected_run.get('id')}/raw",
                operation="run_raw",
            )
            if run_raw_result.get("ok"):
                run_raw = _mask_secrets(_unwrap(run_raw_result.get("payload")))

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
        control_actions: dict[str, bool] = {}
        try:
            control_catalog = await AdminMutationService(self._hub).available_controls(
                project_key,
                entity_type="packet",
                entity_id=packet_id,
                state_hint=str(packet.get("state") or "unknown"),
            )
            control_actions = {
                str(action): bool(available)
                for action, available in (control_catalog.get("control_actions") or {}).items()
            }
        except (KeyError, ValueError):
            control_actions = {}
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
        if tab == "git":
            packet_git = await self.git_page(
                project_key,
                packet=packet,
                ref=git_ref,
                path=git_path,
            )
        stale_base = _stale_base_view(packet, selected_run, project_info)
        packet_diagnostics = _mask_secrets(diagnostics)
        if not isinstance(packet_diagnostics, Mapping):
            packet_diagnostics = {}
        return {
            "packet": packet,
            "control_actions": control_actions,
            "detail": detail,
            "blocking": blocking,
            "timeline": timeline,
            "timeline_total": len(timeline),
            "runs": runs,
            "selected_run": selected_run,
            "stages": stages,
            "selected_stage": selected_stage,
            "sessions": sessions,
            "diagnostics": packet_diagnostics,
            "leases": _lease_views(packet_diagnostics),
            "evidence": evidence,
            "evidence_raw": evidence_raw,
            "artifacts": artifacts,
            "artifact_preview": artifact_preview,
            "logs": packet_logs,
            "files": packet_files,
            "git": packet_git,
            "run_raw": run_raw,
            "stage_raw": stage_raw,
            "stale_base": stale_base,
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
            "log_source": source or "all",
            "log_tail": min(max(int(log_tail), 1), 2000),
            "artifact_path": artifact_path or "",
            "file_root": file_root or "",
            "file_path": file_path or "",
            "git_ref": git_ref or "",
            "git_path": git_path or "",
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
