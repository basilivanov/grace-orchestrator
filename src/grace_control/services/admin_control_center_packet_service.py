# ############################################################################
# AI_HEADER: admin_control_center_packet_service — packet drill-down owner
# ROLE: Coordinates bounded packet detail, run/stage selection, timeline, logs,
#       evidence, artifacts and packet explorer tabs for the Control Center.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Decompose packet drill-down reads into bounded base, selection and
#          tab responsibilities while preserving the facade's DTO contract.
# inputs: AdminProjectAccess, explorer, mutation and explicit project/packet selectors.
# returns: Existing packet tab view-model dictionaries.
# side_effects: Selected-project Admin reads and read-only control availability;
#               explorer tabs delegate to their focused owner.
# emitted_logs: Hub-owned read logs and AdminMutationService capability logs.
# error_behavior: Missing capabilities become explicit fallback DTOs; packet,
#                 run and stage identity remains scoped to the selected project.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminControlCenterPacketService
#     methods:
#       - packet_page
#       - scope_rows_to_run
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_explorer_helpers import (
    _artifact_kind,
    _json_preview,
    _lease_views,
    _normalize_artifacts,
    _stale_base_view,
)
from grace_control.services.admin_control_center_explorer_service import AdminControlCenterExplorerService
from grace_control.services.admin_control_center_helpers import (
    _capability_message,
    _filter_timeline,
    _mask_secrets,
    _normalize_blocking,
    _normalize_event,
    _normalize_packet,
    _normalize_run,
    _normalize_stage,
    _normalize_stages,
    _unwrap,
)
from grace_control.services.admin_mutation_service import AdminMutationService
from grace_control.services.admin_project_access import AdminProjectAccess

_log = GraceLogger("admin_control_center")


@dataclass(slots=True)
class _PacketPageState:
    """Mutable internal accumulator for one packet page request."""

    detail: dict[str, Any] = field(default_factory=dict)
    blocking: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    sessions: Any = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    evidence: Any = field(default_factory=dict)
    evidence_raw: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=lambda: {"artifacts": [], "truncated": False})
    artifact_preview: dict[str, Any] | None = None
    packet_logs: dict[str, Any] = field(default_factory=dict)
    packet_files: dict[str, Any] = field(default_factory=dict)
    packet_git: dict[str, Any] = field(default_factory=dict)
    run_raw: dict[str, Any] = field(default_factory=dict)
    stage_raw: dict[str, Any] = field(default_factory=dict)
    selected_run: dict[str, Any] | None = None
    selected_stage: dict[str, Any] | None = None


# START_BLOCK_SERVICE
class AdminControlCenterPacketService:
    """Own decomposed packet detail and tab orchestration."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind packet composition to explicit read, explorer and mutation
    #          collaborators.
    # inputs: access — project read boundary; explorer — Files/Git owner;
    #         mutation — one app-scoped mutation owner; packet_tabs — tab names.
    # returns: None.
    # side_effects: None; no project request is made during construction.
    # emitted_logs: None.
    # error_behavior: Collaborator contract errors propagate at construction.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        access: AdminProjectAccess,
        explorer: AdminControlCenterExplorerService,
        mutation: AdminMutationService,
        packet_tabs: Sequence[str],
    ) -> None:
        self._access = access
        self._explorer = explorer
        self._mutation = mutation
        self._packet_tabs = tuple(packet_tabs)

    # START_FUNCTION_CONTRACT
    # name: packet_page
    # purpose: Coordinate decomposed packet base, selection and tab reads.
    # inputs: project_key, packet_id, tree/project context, tab, run/stage and
    #         timeline/explorer selectors.
    # returns: Existing packet drill-down view model.
    # side_effects: Reads only the selected project's canonical Admin endpoints.
    # emitted_logs: Hub-owned project read logs and control capability logs.
    # error_behavior: Missing endpoint data becomes capability-aware DTOs.
    # END_FUNCTION_CONTRACT
    async def packet_page(
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
        state = await self._load_base(project_key, packet_id, tab, run_id, stage_id)
        await self._load_tab_data(
            project_key,
            packet_id,
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
            page_context=state,
        )
        return await self._build_packet_model(
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
            page_context=state,
        )

    # START_FUNCTION_CONTRACT
    # name: _load_base
    # purpose: Read packet detail/blocking data and conditionally load raw,
    #          timeline, runs and selected stage context.
    # inputs: project_key, packet_id, tab and optional run/stage selectors.
    # returns: PacketPageState containing canonical base and selection data.
    # side_effects: Bounded selected-project packet reads.
    # emitted_logs: Hub-owned packet read logs.
    # error_behavior: Failed reads degrade to empty base mappings.
    # END_FUNCTION_CONTRACT
    async def _load_base(
        self,
        project_key: str,
        packet_id: str,
        tab: str,
        run_id: str | None,
        stage_id: str | None,
    ) -> _PacketPageState:
        detail_result, blocking_result = await asyncio.gather(
            self._access.read(project_key, f"/api/admin/packet/{packet_id}/detail", operation="packet_detail"),
            self._access.read(project_key, f"/api/admin/packet/{packet_id}/blocking_decision", operation="blocking"),
        )
        detail = _unwrap(detail_result.get("payload")) if detail_result.get("ok") else {}
        state = _PacketPageState(
            detail=detail if isinstance(detail, dict) else {},
            blocking=blocking_result,
        )
        if tab in {"spec", "pipeline", "stages", "evidence", "logs", "artifacts", "files", "git", "raw"}:
            raw_result = await self._access.read(
                project_key,
                f"/api/admin/packet/{packet_id}/raw",
                operation="packet_raw",
            )
            raw = _unwrap(raw_result.get("payload")) if raw_result.get("ok") else {}
            state.raw = raw if isinstance(raw, dict) else {}
        if tab == "timeline":
            timeline_result = await self._access.read(
                project_key,
                f"/api/admin/packet/{packet_id}/timeline?limit=200&offset=0",
                operation="timeline",
            )
            timeline_payload = _unwrap(timeline_result.get("payload")) if timeline_result.get("ok") else {}
            if isinstance(timeline_payload, Mapping):
                state.timeline = [_normalize_event(row) for row in timeline_payload.get("events", [])]
        if tab in {"runs", "evidence", "logs", "artifacts", "files", "raw", "git"} or run_id:
            runs_result = await self._access.read(
                project_key,
                f"/api/admin/packet/{packet_id}/runs",
                operation="runs",
            )
            runs_payload = _unwrap(runs_result.get("payload")) if runs_result.get("ok") else {}
            if isinstance(runs_payload, Mapping):
                state.runs = [_normalize_run(row) for row in runs_payload.get("runs", [])]
            state.selected_run = await self._select_run(project_key, packet_id, run_id, state.runs)
        if tab in {"stages", "pipeline", "evidence", "logs", "raw"} and stage_id:
            await self._select_stage(project_key, packet_id, stage_id, run_id, state)
        return state

    # START_FUNCTION_CONTRACT
    # name: _select_run
    # purpose: Select a run by packet-scoped identity, falling back to the
    #          canonical run-detail endpoint only for an explicit selector.
    # inputs: project_key, packet_id, optional run_id and normalized runs.
    # returns: Selected run mapping or None.
    # side_effects: At most one selected-project run-detail read.
    # emitted_logs: Hub-owned run read logs.
    # error_behavior: Cross-packet or missing selectors remain unselected.
    # END_FUNCTION_CONTRACT
    async def _select_run(
        self,
        project_key: str,
        packet_id: str,
        run_id: str | None,
        runs: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if run_id:
            selected = next(
                (
                    row
                    for row in runs
                    if str(row.get("id")) == str(run_id)
                    and row.get("packet_id") in (None, packet_id)
                ),
                None,
            )
            if selected is None:
                run_result = await self._access.read(
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
                        selected = candidate
            return selected
        return runs[-1] if runs else None

    # START_FUNCTION_CONTRACT
    # name: _select_stage
    # purpose: Validate a stage selector against the selected packet/run raw
    #          rows before reading its canonical raw endpoint.
    # inputs: project_key, packet_id, stage_id, optional run_id and page state.
    # returns: None; updates selected_stage and stage_raw in state.
    # side_effects: At most one selected-project stage raw read after validation.
    # emitted_logs: Hub-owned stage read logs.
    # error_behavior: Invalid/cross-run stage selectors are ignored.
    # END_FUNCTION_CONTRACT
    async def _select_stage(
        self,
        project_key: str,
        packet_id: str,
        stage_id: str,
        run_id: str | None,
        page_state: _PacketPageState,
    ) -> None:
        state = page_state
        stage_rows = self._scope_rows_to_run(state.raw.get("stages", []), run_id)
        stage_match = next(
            (
                row
                for row in stage_rows
                if isinstance(row, Mapping)
                and str(row.get("id") or row.get("stage_run_id")) == str(stage_id)
            ),
            None,
        )
        if stage_match is None:
            return
        stage_result = await self._access.read(
            project_key,
            f"/api/admin/stage/{stage_id}/raw",
            operation="stage_detail",
        )
        if stage_result.get("ok"):
            payload = _unwrap(stage_result.get("payload"))
            state.selected_stage = _normalize_stage(payload)
            state.stage_raw = _mask_secrets(payload)

    # START_FUNCTION_CONTRACT
    # name: _load_tab_data
    # purpose: Dispatch tab-specific reads for sessions, diagnostics, evidence,
    #          logs, artifacts, Files, Git, raw and timeline filtering.
    # inputs: explicit packet selectors and mutable packet page state.
    # returns: None; updates state with tab view fragments.
    # side_effects: Bounded selected-project tab reads and explorer delegation.
    # emitted_logs: Hub-owned read logs.
    # error_behavior: Capability gaps become existing fallback DTOs.
    # END_FUNCTION_CONTRACT
    async def _load_tab_data(
        self,
        project_key: str,
        packet_id: str,
        *,
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
        page_context: _PacketPageState,
    ) -> None:
        state = page_context
        if tab == "sessions":
            state.sessions = await self._load_sessions(project_key, packet_id)
        if tab == "diagnostics":
            state.diagnostics = await self._load_diagnostics(project_key)
        if tab == "evidence":
            state.evidence, state.evidence_raw = await self._load_evidence(project_key, packet_id, state.selected_run)
        if tab == "logs":
            state.packet_logs = await self._load_logs(
                project_key,
                packet_id,
                stage_id=stage_id,
                source=source,
                log_tail=log_tail,
                selected_run=state.selected_run,
                selected_stage=state.selected_stage,
            )
        if tab == "artifacts":
            state.artifacts, state.artifact_preview = await self._load_artifacts(
                project_key,
                packet_id,
                state.selected_run,
                artifact_path,
            )
        if tab == "files":
            state.packet_files = await self._explorer.files_page(
                project_key,
                root=file_root,
                path=file_path,
                preview_path=file_path if file_path and not file_path.endswith("/") else None,
            )
        if tab == "raw" and state.selected_run:
            run_raw_result = await self._access.read(
                project_key,
                f"/api/admin/packet/{packet_id}/runs/{state.selected_run.get('id')}/raw",
                operation="run_raw",
            )
            if run_raw_result.get("ok"):
                state.run_raw = _mask_secrets(_unwrap(run_raw_result.get("payload")))
        if tab == "timeline":
            state.timeline = self._scope_rows_to_run(state.timeline, run_id)
            state.timeline = _filter_timeline(
                state.timeline,
                event_filter=event,
                component_filter=component,
                run_stage_filter=run_stage,
                trace_filter=trace_id,
                text_filter=text,
            )

    # START_FUNCTION_CONTRACT
    # name: _load_sessions
    # purpose: Read and normalize packet session availability.
    # inputs: project_key and packet_id.
    # returns: Session mapping or explicit unavailable DTO.
    # side_effects: One selected-project sessions read.
    # emitted_logs: Hub-owned session read logs.
    # error_behavior: Capability gaps become available=false messages.
    # END_FUNCTION_CONTRACT
    async def _load_sessions(self, project_key: str, packet_id: str) -> Any:
        result = await self._access.read(
            project_key,
            f"/api/admin/packet/{packet_id}/sessions",
            operation="sessions",
        )
        if not result.get("ok"):
            return {"available": False, "message": _capability_message(result)}
        sessions = _unwrap(result.get("payload"))
        if not isinstance(sessions, Mapping):
            return {"available": False, "message": "Sessions response is unavailable."}
        data = dict(sessions)
        data.setdefault("available", True)
        return data

    # START_FUNCTION_CONTRACT
    # name: _load_diagnostics
    # purpose: Read packet diagnostics with capability fallback.
    # inputs: project_key — explicit registry key.
    # returns: Diagnostics mapping or error DTO.
    # side_effects: One selected-project diagnostics read.
    # emitted_logs: Hub-owned diagnostics read logs.
    # error_behavior: Failed reads return a typed error mapping.
    # END_FUNCTION_CONTRACT
    async def _load_diagnostics(self, project_key: str) -> dict[str, Any]:
        result = await self._access.read(
            project_key,
            "/api/diagnostics/state",
            operation="diagnostics",
        )
        if result.get("ok"):
            payload = _unwrap(result.get("payload"))
            return payload if isinstance(payload, dict) else {}
        return {"error": _capability_message(result)}

    # START_FUNCTION_CONTRACT
    # name: _load_evidence
    # purpose: Read selected-run evidence and preserve raw masked evidence.
    # inputs: project_key, packet_id and optional selected run.
    # returns: (display evidence, raw evidence) pair.
    # side_effects: One selected-project evidence read when a run is selected.
    # emitted_logs: Hub-owned evidence read logs.
    # error_behavior: Missing run/evidence returns existing unavailable DTOs.
    # END_FUNCTION_CONTRACT
    async def _load_evidence(
        self,
        project_key: str,
        packet_id: str,
        selected_run: Mapping[str, Any] | None,
    ) -> tuple[Any, dict[str, Any]]:
        if not selected_run:
            return {"available": False, "message": "Select a run to inspect evidence.", "source": "API"}, {}
        result = await self._access.read(
            project_key,
            f"/api/admin/packet/{packet_id}/runs/{selected_run.get('id')}/evidence",
            operation="evidence",
        )
        evidence = (
            _mask_secrets(_unwrap(result.get("payload")))
            if result.get("ok")
            else {"available": False, "message": _capability_message(result)}
        )
        raw = dict(evidence) if isinstance(evidence, Mapping) else {}
        if isinstance(evidence, Mapping):
            evidence = dict(evidence)
            evidence.setdefault("available", True)
            evidence.setdefault("source", "API")
        return evidence, raw

    # START_FUNCTION_CONTRACT
    # name: _load_logs
    # purpose: Select packet, run or stage log source and apply bounded tail.
    # inputs: project_key, packet_id, stage/run selectors, source and log_tail.
    # returns: Normalized packet log DTO.
    # side_effects: One selected-project log read.
    # emitted_logs: Hub-owned log read logs.
    # error_behavior: Capability gaps become unavailable log DTOs.
    # END_FUNCTION_CONTRACT
    async def _load_logs(
        self,
        project_key: str,
        packet_id: str,
        *,
        stage_id: str | None,
        source: str | None,
        log_tail: int,
        selected_run: Mapping[str, Any] | None,
        selected_stage: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        selected_source = str(source or "all")
        bounded_tail = min(max(int(log_tail), 1), 2000)
        if stage_id:
            stage_selector = (
                selected_stage.get("stage_key") if isinstance(selected_stage, Mapping) else None
            ) or stage_id
            path = f"/api/admin/packet/{quote(str(packet_id), safe='-_.~')}/stages/{quote(str(stage_selector), safe='-_.~')}/logs"
            params = {"stream": "all", "tail": bounded_tail}
            operation = "packet_stage_logs"
        elif selected_run:
            stream = selected_source if selected_source in {"stdout", "stderr", "agent"} else "stderr"
            path = f"/api/admin/packet/{packet_id}/runs/{selected_run.get('id')}/logs"
            params = {"stream": stream, "tail": bounded_tail}
            operation = "packet_run_logs"
        else:
            path = f"/api/admin/packet/{packet_id}/logs/aggregated"
            params = {"sources": selected_source or "all", "tail": bounded_tail}
            operation = "packet_logs"
        result = await self._access.read(project_key, path, params=params, operation=operation)
        logs = (
            _mask_secrets(_unwrap(result.get("payload")))
            if result.get("ok")
            else {"available": False, "message": _capability_message(result)}
        )
        if not isinstance(logs, Mapping):
            return {"available": False, "message": "Logs response is unavailable."}
        data = dict(logs)
        data.setdefault("available", True)
        data.setdefault("source", selected_source or "all")
        data.setdefault("source_label", "API")
        data.setdefault("truncated", bool(data.get("truncated", False)))
        data.setdefault("tail", bounded_tail)
        data.setdefault("follow", False)
        data.setdefault("wrap", False)
        return data

    # START_FUNCTION_CONTRACT
    # name: _load_artifacts
    # purpose: Read bounded artifact metadata and optional selected preview.
    # inputs: project_key, packet_id, selected run and artifact path.
    # returns: (artifact DTO, optional preview DTO) pair.
    # side_effects: Artifact metadata and optional preview reads.
    # emitted_logs: Hub-owned artifact read logs.
    # error_behavior: Missing run/path becomes explicit fallback DTO.
    # END_FUNCTION_CONTRACT
    async def _load_artifacts(
        self,
        project_key: str,
        packet_id: str,
        selected_run: Mapping[str, Any] | None,
        artifact_path: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if not selected_run:
            return (
                {"artifacts": [], "truncated": False, "message": "Select a run to inspect artifacts.", "source": "API"},
                None,
            )
        result = await self._access.read(
            project_key,
            f"/api/admin/packet/{packet_id}/runs/{selected_run.get('id')}/artifacts",
            operation="artifacts",
        )
        if result.get("ok"):
            artifacts = _normalize_artifacts(_unwrap(result.get("payload")))
            artifacts["source"] = "API"
        else:
            artifacts = {
                "artifacts": [],
                "truncated": False,
                "error": _capability_message(result),
                "source": "API",
            }
        preview = await self._load_artifact_preview(project_key, packet_id, selected_run, artifact_path)
        return artifacts, preview

    # START_FUNCTION_CONTRACT
    # name: _load_artifact_preview
    # purpose: Read and classify one bounded artifact preview.
    # inputs: project_key, packet_id, selected run and optional relative path.
    # returns: Masked preview DTO or None.
    # side_effects: At most one bounded artifact preview read.
    # emitted_logs: Hub-owned artifact read logs.
    # error_behavior: Failed previews return a typed error DTO.
    # END_FUNCTION_CONTRACT
    async def _load_artifact_preview(
        self,
        project_key: str,
        packet_id: str,
        selected_run: Mapping[str, Any],
        artifact_path: str | None,
    ) -> dict[str, Any] | None:
        if not artifact_path:
            return None
        result = await self._access.read(
            project_key,
            f"/api/admin/packet/{packet_id}/runs/{selected_run.get('id')}/artifacts/preview",
            params={"path": artifact_path, "max_bytes": 512 * 1024},
            operation="artifact_preview",
        )
        if not result.get("ok"):
            return {"path": artifact_path, "error": _capability_message(result), "source": "API"}
        preview = _mask_secrets(_unwrap(result.get("payload")))
        if not isinstance(preview, Mapping):
            return {"path": artifact_path, "error": "Artifact preview is unavailable.", "source": "API"}
        data = dict(preview)
        kind, previewable, category = _artifact_kind(
            artifact_path,
            data.get("mime"),
            bool(data.get("binary")),
            data.get("size"),
        )
        data.update({
            "path": artifact_path,
            "kind": kind,
            "category": category,
            "previewable": previewable,
            "source": "API",
            "json_structured": _json_preview(data.get("content"), kind),
        })
        return data

    # START_FUNCTION_CONTRACT
    # name: _build_packet_model
    # purpose: Normalize the accumulated packet state and assemble the stable
    #          packet tab DTO, including controls and stale-base metadata.
    # inputs: packet selectors, project context and populated PacketPageState.
    # returns: Existing packet drill-down view model.
    # side_effects: One read-only AdminMutationService capability lookup and an
    #               optional Git explorer delegation.
    # emitted_logs: AdminMutationService capability logs.
    # error_behavior: Capability lookup failures yield an empty control catalog.
    # END_FUNCTION_CONTRACT
    async def _build_packet_model(
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
        page_context: _PacketPageState,
    ) -> dict[str, Any]:
        state = page_context
        packet = _normalize_packet(
            state.detail,
            tree_packet,
            state.raw.get("packet"),
            state.runs,
            state.selected_run if run_id else None,
        )
        control_actions = await self._control_actions(project_key, packet_id, packet)
        blocking = _normalize_blocking(state.detail, state.blocking, packet)
        detail_stages = state.detail.get("stages")
        raw_stages = state.raw.get("stages")
        stages = _normalize_stages(
            None if run_id and isinstance(raw_stages, list) else detail_stages,
            raw_stages,
            state.detail.get("pipeline"),
        )
        stages = self._scope_rows_to_run(stages, run_id)
        if state.selected_stage is not None:
            state.selected_stage = _normalize_stage(state.selected_stage)
        if tab == "git":
            state.packet_git = await self._explorer.git_page(
                project_key,
                packet=packet,
                ref=git_ref,
                path=git_path,
            )
        stale_base = _stale_base_view(packet, state.selected_run, project_info)
        diagnostics = _mask_secrets(state.diagnostics)
        if not isinstance(diagnostics, Mapping):
            diagnostics = {}
        bounded_tail = min(max(int(log_tail), 1), 2000)
        return {
            "packet": packet,
            "control_actions": control_actions,
            "detail": state.detail,
            "blocking": blocking,
            "timeline": state.timeline,
            "timeline_total": len(state.timeline),
            "runs": state.runs,
            "selected_run": state.selected_run,
            "stages": stages,
            "selected_stage": state.selected_stage,
            "sessions": state.sessions,
            "diagnostics": diagnostics,
            "leases": _lease_views(diagnostics),
            "evidence": state.evidence,
            "evidence_raw": state.evidence_raw,
            "artifacts": state.artifacts,
            "artifact_preview": state.artifact_preview,
            "logs": state.packet_logs,
            "files": state.packet_files,
            "git": state.packet_git,
            "run_raw": state.run_raw,
            "stage_raw": state.stage_raw,
            "stale_base": stale_base,
            "raw": _mask_secrets(state.raw),
            "tabs": self._packet_tabs,
            "tab": tab if tab in self._packet_tabs else "overview",
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
            "log_tail": bounded_tail,
            "artifact_path": artifact_path or "",
            "file_root": file_root or "",
            "file_path": file_path or "",
            "git_ref": git_ref or "",
            "git_path": git_path or "",
        }

    # START_FUNCTION_CONTRACT
    # name: _control_actions
    # purpose: Read the authoritative packet control catalog without executing
    #          a mutation.
    # inputs: project_key, packet_id and normalized packet state.
    # returns: Action-to-availability mapping.
    # side_effects: One selected-project capability read.
    # emitted_logs: AdminMutationService capability logs.
    # error_behavior: Key/value capability gaps return an empty mapping.
    # END_FUNCTION_CONTRACT
    async def _control_actions(
        self,
        project_key: str,
        packet_id: str,
        packet: Mapping[str, Any],
    ) -> dict[str, bool]:
        try:
            catalog = await self._mutation.available_controls(
                project_key,
                entity_type="packet",
                entity_id=packet_id,
                state_hint=str(packet.get("state") or "unknown"),
            )
            return {
                str(action): bool(available)
                for action, available in (catalog.get("control_actions") or {}).items()
            }
        except (KeyError, ValueError):
            return {}

    # START_FUNCTION_CONTRACT
    # name: _scope_rows_to_run
    # purpose: Keep packet rows associated with the selected run while retaining
    #          packet-wide rows without a run association.
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


# END_BLOCK_SERVICE
