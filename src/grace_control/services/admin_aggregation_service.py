# ############################################################################
# AI_HEADER: admin_aggregation_service — stable admin read facade
# ROLE: Preserves the public AdminAggregationService API and DTO contracts for
#       admin routers and raw-read callers while delegating coherent read
#       responsibilities to focused overview, packet, pipeline, artifact,
#       feature and log services. This facade is read-only.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose the stable admin aggregation service surface while keeping
#          each read responsibility in a focused collaborator.
# inputs: SQLAlchemy Session, entity IDs/selectors and existing filter args.
# returns: Existing admin dictionaries, binary tuples or None on misses.
# side_effects: Delegates only read-only database/filesystem operations.
# emitted_logs: Collaborators retain existing filesystem/session logs.
# error_behavior: Preserves each legacy method's None/empty/fallback behavior.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminAggregationService
#     methods:
#       - get_overview
#       - get_packet_detail
#       - get_packet_blocking_decision
#       - get_packet_timeline
#       - get_packet_runs
#       - get_packet_run
#       - get_packet_evidence
#       - get_packet_artifacts
#       - get_artifact_file
#       - get_artifact_preview
#       - get_packet_logs
#       - get_packet_sessions
#       - get_feature_summary
#       - get_features_tree
#       - get_wave_detail
#       - search
#       - get_system_health
#       - get_workers
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_artifact_read_service import (
    AdminArtifactReadService,
    _build_artifact_tree,  # noqa: F401
    _classify_artifact,  # noqa: F401
)
from grace_control.services.admin_feature_read_service import AdminFeatureReadService
from grace_control.services.admin_logs_read_service import AdminLogsReadService
from grace_control.services.admin_overview_read_service import (
    _PACKET_STATES,  # noqa: F401
    AdminOverviewReadService,
    _elapsed_seconds,  # noqa: F401
    _is_running,  # noqa: F401
    _iso,  # noqa: F401
    _now,  # noqa: F401
)
from grace_control.services.admin_packet_read_service import (
    _BLOCKING_STATES,  # noqa: F401
    AdminPacketReadService,
    _packet_spec_value,  # noqa: F401
)
from grace_control.services.admin_pipeline_read_service import AdminPipelineReadService

_log = GraceLogger("admin_aggregation")


# START_BLOCK_SERVICE
class AdminAggregationService:
    """Compatibility facade for all read-only admin aggregation endpoints."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Wire focused read services behind the stable facade.
    # inputs: state_root and worktree_root — optional SizeCalculator roots.
    # returns: None.
    # side_effects: Resolves configured size-calculation roots only.
    # emitted_logs: None.
    # error_behavior: Preserves SizeCalculator constructor behavior.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        state_root: Path | str | None = None,
        worktree_root: Path | str | None = None,
    ) -> None:
        from grace_control.services.size_calculator import SizeCalculator

        self._size_calc = SizeCalculator(state_root=state_root, worktree_root=worktree_root)
        self._overview = AdminOverviewReadService()
        self._pipeline = AdminPipelineReadService()
        self._packet = AdminPacketReadService(self._size_calc, self._pipeline)
        self._artifacts = AdminArtifactReadService(self._packet.resolve_run)
        self._logs = AdminLogsReadService(self._packet.resolve_run)
        self._packet._artifact_service = self._artifacts
        self._packet._session_service = self._logs
        self._pipeline._artifact_service = self._artifacts
        self._features = AdminFeatureReadService(self._size_calc, self._pipeline)

    # START_FUNCTION_CONTRACT
    # name: get_overview
    # purpose: Return the admin overview DTO.
    # inputs: db — active SQLAlchemy Session.
    # returns: Existing overview dictionary.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves overview fallback behavior.
    # END_FUNCTION_CONTRACT
    def get_overview(self, db: Session) -> dict[str, Any]:
        return self._overview.get_overview(db)

    # START_FUNCTION_CONTRACT
    # name: get_packet_detail
    # purpose: Return complete packet detail DTO.
    # inputs: db and packet_id.
    # returns: Packet detail dictionary or None.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves missing-packet behavior.
    # END_FUNCTION_CONTRACT
    def get_packet_detail(self, db: Session, packet_id: str) -> dict[str, Any] | None:
        return self._packet.get_packet_detail(db, packet_id)

    # START_FUNCTION_CONTRACT
    # name: get_packet_blocking_decision
    # purpose: Return a packet's blocking decision DTO.
    # inputs: db and packet_id.
    # returns: Blocking decision dictionary or None.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves non-blocking/missing behavior.
    # END_FUNCTION_CONTRACT
    def get_packet_blocking_decision(self, db: Session, packet_id: str) -> dict[str, Any] | None:
        return self._packet.get_packet_blocking_decision(db, packet_id)

    # START_FUNCTION_CONTRACT
    # name: get_packet_timeline
    # purpose: Return a paginated packet event timeline.
    # inputs: db, packet_id, limit and offset.
    # returns: Existing timeline dictionary.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves empty timeline behavior.
    # END_FUNCTION_CONTRACT
    def get_packet_timeline(
        self, db: Session, packet_id: str, limit: int = 200, offset: int = 0
    ) -> dict[str, Any]:
        return self._packet.get_packet_timeline(db, packet_id, limit, offset)

    # START_FUNCTION_CONTRACT
    # name: get_packet_runs
    # purpose: Return all packet run summaries.
    # inputs: db and packet_id.
    # returns: Existing runs dictionary.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves empty runs behavior.
    # END_FUNCTION_CONTRACT
    def get_packet_runs(self, db: Session, packet_id: str) -> dict[str, Any]:
        return self._packet.get_packet_runs(db, packet_id)

    # START_FUNCTION_CONTRACT
    # name: get_packet_run
    # purpose: Return one packet run with result/prompt/artifact summary.
    # inputs: db, packet_id and run_id selector.
    # returns: Existing run dictionary or None.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves unknown-selector behavior.
    # END_FUNCTION_CONTRACT
    def get_packet_run(self, db: Session, packet_id: str, run_id: str) -> dict[str, Any] | None:
        return self._artifacts.get_packet_run(db, packet_id, run_id)

    # START_FUNCTION_CONTRACT
    # name: get_packet_evidence
    # purpose: Return the selected run's acceptance evidence DTO.
    # inputs: db, packet_id and optional run_id selector.
    # returns: Existing evidence dictionary.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves empty evidence behavior.
    # END_FUNCTION_CONTRACT
    def get_packet_evidence(
        self, db: Session, packet_id: str, run_id: str | None = None
    ) -> dict[str, Any]:
        return self._artifacts.get_packet_evidence(db, packet_id, run_id)

    # START_FUNCTION_CONTRACT
    # name: get_packet_artifacts
    # purpose: Return a bounded artifact metadata tree for one run.
    # inputs: db, packet_id and run_id selector.
    # returns: Existing artifacts tree dictionary.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves missing evidence behavior.
    # END_FUNCTION_CONTRACT
    def get_packet_artifacts(self, db: Session, packet_id: str, run_id: str) -> dict[str, Any]:
        return self._artifacts.get_packet_artifacts(db, packet_id, run_id)

    # START_FUNCTION_CONTRACT
    # name: get_artifact_file
    # purpose: Read an artifact file or bounded tail through safe filesystem
    #          validation.
    # inputs: db, packet_id, run_id, relative path and tail line count.
    # returns: (bytes, mime) tuple or None.
    # side_effects: Bounded safe local file read.
    # emitted_logs: SafeFilesystemService read events.
    # error_behavior: Preserves unsafe/missing path behavior.
    # END_FUNCTION_CONTRACT
    def get_artifact_file(
        self,
        db: Session,
        packet_id: str,
        run_id: str,
        path: str,
        tail: int = 0,
    ) -> tuple[bytes, str] | None:
        return self._artifacts.get_artifact_file(db, packet_id, run_id, path, tail)

    # START_FUNCTION_CONTRACT
    # name: get_artifact_preview
    # purpose: Return a bounded JSON-safe artifact preview.
    # inputs: db, packet_id, run_id, relative path and max_bytes.
    # returns: Preview dictionary without physical root or None.
    # side_effects: Bounded safe local file read.
    # emitted_logs: SafeFilesystemService read events.
    # error_behavior: Preserves unsafe/missing path behavior.
    # END_FUNCTION_CONTRACT
    def get_artifact_preview(
        self,
        db: Session,
        packet_id: str,
        run_id: str,
        path: str,
        max_bytes: int = 512 * 1024,
    ) -> dict[str, Any] | None:
        return self._artifacts.get_artifact_preview(db, packet_id, run_id, path, max_bytes)

    # START_FUNCTION_CONTRACT
    # name: get_packet_logs
    # purpose: Return bounded packet log lines with optional regex filtering.
    # inputs: db, packet_id, run_id, stream, tail and filter_regex.
    # returns: Existing logs dictionary.
    # side_effects: Read-only local log file read.
    # error_behavior: Preserves empty/malformed-regex behavior.
    # END_FUNCTION_CONTRACT
    def get_packet_logs(
        self,
        db: Session,
        packet_id: str,
        run_id: str,
        stream: str = "stderr",
        tail: int = 200,
        filter_regex: str = "",
    ) -> dict[str, Any]:
        return self._logs.get_packet_logs(db, packet_id, run_id, stream, tail, filter_regex)

    # START_FUNCTION_CONTRACT
    # name: get_packet_sessions
    # purpose: Return the session summary for a packet.
    # inputs: db and packet_id.
    # returns: Existing session dictionary.
    # side_effects: Read-only optional session-table query.
    # emitted_logs: SessionStore's existing logs.
    # error_behavior: Preserves table_missing/empty behavior.
    # END_FUNCTION_CONTRACT
    def get_packet_sessions(self, db: Session, packet_id: str) -> dict[str, Any]:
        return self._logs.get_packet_sessions(db, packet_id)

    # START_FUNCTION_CONTRACT
    # name: get_feature_summary
    # purpose: Return feature summary grouped by wave.
    # inputs: db and feature_id.
    # returns: Feature summary dictionary or None.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves missing-feature behavior.
    # END_FUNCTION_CONTRACT
    def get_feature_summary(self, db: Session, feature_id: str) -> dict[str, Any] | None:
        return self._features.get_feature_summary(db, feature_id)

    # START_FUNCTION_CONTRACT
    # name: get_features_tree
    # purpose: Return the nested feature/wave/packet tree.
    # inputs: db and include_archived flag.
    # returns: Existing feature tree dictionary.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves empty tree behavior.
    # END_FUNCTION_CONTRACT
    def get_features_tree(self, db: Session, include_archived: bool = False) -> dict[str, Any]:
        return self._features.get_features_tree(db, include_archived)

    # START_FUNCTION_CONTRACT
    # name: get_wave_detail
    # purpose: Return wave context, packet rows, counts and stage progress.
    # inputs: db, feature_id and wave_id.
    # returns: Wave detail dictionary or None.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves missing/cross-feature behavior.
    # END_FUNCTION_CONTRACT
    def get_wave_detail(
        self, db: Session, feature_id: str, wave_id: str
    ) -> dict[str, Any] | None:
        return self._features.get_wave_detail(db, feature_id, wave_id)

    # START_FUNCTION_CONTRACT
    # name: search
    # purpose: Search packet, feature and run entities by substring.
    # inputs: db, query string and result limit.
    # returns: Existing results dictionary.
    # side_effects: Read-only collaborator calls.
    # error_behavior: Preserves empty-query behavior.
    # END_FUNCTION_CONTRACT
    def search(self, db: Session, q: str, limit: int = 50) -> dict[str, Any]:
        return self._features.search(db, q, limit)

    # START_FUNCTION_CONTRACT
    # name: get_system_health
    # purpose: Return runtime supervisor/API/database/code health DTO.
    # inputs: None.
    # returns: Existing system health dictionary.
    # side_effects: Read-only runtime metadata reads.
    # error_behavior: Preserves safe default behavior.
    # END_FUNCTION_CONTRACT
    def get_system_health(self) -> dict[str, Any]:
        return self._overview.get_system_health()

    # START_FUNCTION_CONTRACT
    # name: get_workers
    # purpose: Return current worker rows.
    # inputs: db — active SQLAlchemy Session.
    # returns: Existing workers dictionary.
    # side_effects: Read-only Worker query.
    # error_behavior: Preserves SQLAlchemy behavior.
    # END_FUNCTION_CONTRACT
    def get_workers(self, db: Session) -> dict[str, Any]:
        return self._overview.get_workers(db)

    # END_BLOCK_SERVICE

    # START_BLOCK_COMPATIBILITY
    def _run_for_selector(self, db: Session, packet_id: str, run_id: str) -> Any:
        return self._packet.resolve_run(db, packet_id, run_id)

    def _derive_stages(self, db: Session, packet: Any) -> list[dict[str, Any]]:
        return self._pipeline.derive_stages(db, packet)

    def _derive_recovery_chain(self, db: Session, packet: Any) -> list[dict[str, Any]]:
        return self._pipeline.derive_recovery_chain(db, packet)

    def _derive_totals(self, db: Session, packet: Any) -> dict[str, Any]:
        return self._pipeline.derive_totals(db, packet)

    def _derive_pipeline(self, db: Session, packet: Any, runs: list[Any]) -> dict[str, Any]:
        return self._pipeline.derive_pipeline(db, packet, runs)

    def _derive_simple_pipeline(
        self,
        packet: Any,
        last_run: Any,
        feature_status: str = "",
        db: Session | None = None,
    ) -> dict[str, Any]:
        return self._pipeline.derive_simple_pipeline(packet, last_run, feature_status, db)

    def _derive_packet_stage(self, packet: Any, last_run: Any) -> dict[str, str]:
        return self._pipeline.derive_packet_stage(packet, last_run)

    def _derive_state_machine(
        self, db: Session, packet: Any, runs: list[Any]
    ) -> dict[str, Any]:
        return self._pipeline.derive_state_machine(db, packet, runs)

    def _recovery_dict(self, run: Any) -> dict[str, Any] | None:
        return self._packet._recovery_dict(run)

    def _recommend(self, packet: Any, last_run: Any) -> str:
        return self._packet._recommend(packet, last_run)

    def _detect_decision_component(self, db: Session, packet_id: str, state: str) -> str | None:
        return self._packet._detect_decision_component(db, packet_id, state)

    def _last_failure_from_run(self, run: Any) -> dict[str, Any] | None:
        return self._packet._last_failure_from_run(run)

    @staticmethod
    def _tail_text(value: str, lines: int) -> str:
        return AdminPacketReadService._tail_text(value, lines)

    # END_BLOCK_COMPATIBILITY
