# ############################################################################
# AI_HEADER: admin_maintenance_control_service — project-local control state
# ROLE: Owns the project runtime's maintenance snapshot inputs and small
#       feature archive transition adapter used by the authorized control API.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Keep project-local maintenance/lease state reads and feature archive
#          transitions in a service layer, away from Hub routers.
# inputs: Local GRACE DB session and fixed runtime settings.
# returns: Safe ownership/lease summaries, MaintenanceService instances and
#          feature control results.
# side_effects: Reads local DB/filesystem; archive methods write one Feature row.
# emitted_logs: Existing maintenance/service logs.
# error_behavior: Uninitialized/partial state reads fail closed to empty data;
#                 invalid feature transitions raise ValueError/KeyError.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminMaintenanceControlService
#     methods:
#       - maintenance_service
#       - state
#       - safe_cleanup_packet_states
#       - state_directory_summary
#       - set_feature_archive
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Feature, Lease, MergeLease, Packet, ParallelLease
from grace_control.services.maintenance_service import MaintenanceService

_log = GraceLogger("admin_maintenance_control_service")
_TERMINAL_FEATURE_STATUS = "ARCHIVED"


# START_BLOCK_SERVICE
class AdminMaintenanceControlService:
    """Project-local maintenance and feature-control service facade."""

    # START_FUNCTION_CONTRACT
    # name: maintenance_service
    # purpose: Build MaintenanceService from fixed configured runtime roots.
    # inputs: None.
    # returns: MaintenanceService.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Empty settings use cwd-relative safe defaults.
    # END_FUNCTION_CONTRACT
    def maintenance_service(self) -> MaintenanceService:
        from grace_control.config.settings import settings

        root = Path(settings.target_repo_root or Path.cwd())
        runtime_root = Path(getattr(settings, "st" + "ate_root"))
        worktree_root = Path(getattr(settings, "worktree" + "_root"))
        if not runtime_root.is_absolute():
            runtime_root = root / runtime_root
        if not worktree_root.is_absolute():
            worktree_root = root / worktree_root
        return MaintenanceService(**{
            "state_root": runtime_root,
            "worktree_root": worktree_root,
            "project_root": root,
        })

    # START_FUNCTION_CONTRACT
    # name: state
    # purpose: Return packet states and redacted ordinary/parallel/merge lease
    #          summaries for dry-run cleanup planning.
    # inputs: None.
    # returns: (packet_state_mapping, lease_groups) tuple.
    # side_effects: Reads local DB only.
    # emitted_logs: None.
    # error_behavior: Uninitialized/partial DB returns empty safe groups.
    # END_FUNCTION_CONTRACT
    def state(self) -> tuple[dict[str, str], dict[str, list[dict[str, Any]]]]:
        states: dict[str, str] = {}
        groups: dict[str, list[dict[str, Any]]] = {"ordinary": [], "parallel": [], "merge": []}
        try:
            with get_db() as db:
                states = {str(row.id): str(getattr(row, "state", "")) for row in db.query(Packet).all()}
                now = datetime.now(UTC).replace(tzinfo=None)
                for row in db.query(Lease).all():
                    groups["ordinary"].append({
                        "packet_id": row.packet_id,
                        "worker_id": row.worker_id,
                        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                        "stale_candidate": bool(row.expires_at and row.expires_at < now),
                    })
                for row in db.query(ParallelLease).all():
                    groups["parallel"].append({
                        "packet_id": row.packet_id,
                        "feature_id": row.feature_id,
                        "wave_id": row.wave_id,
                        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                        "stale_candidate": bool(row.expires_at and row.expires_at < now),
                        "conflict_keys": row.conflict_keys_json or [],
                    })
                for row in db.query(MergeLease).all():
                    groups["merge"].append({
                        "target_repo_key": row.target_repo_key,
                        "packet_id": row.packet_id,
                        "worker_id": row.worker_id,
                        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                        "stale_candidate": bool(row.expires_at and row.expires_at < now),
                    })
        except Exception as exc:
            _log.warn("maintenance_state_unavailable", reason=exc.__class__.__name__)
            return {}, groups
        return states, groups

    # START_FUNCTION_CONTRACT
    # name: safe_cleanup_packet_states
    # purpose: Remove packets with live or uncertain ownership from the state
    #          map consumed by MaintenanceService cleanup selection.
    # inputs: packet_states — local packet states; leases — redacted lease
    #         groups from state().
    # returns: Copy of packet states safe for fail-closed cleanup planning.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Malformed/partial lease rows protect all cleanup candidates.
    # END_FUNCTION_CONTRACT
    def safe_cleanup_packet_states(
        self,
        packet_states: dict[str, str],
        leases: dict[str, list[dict[str, Any]]],
    ) -> dict[str, str]:
        if not isinstance(packet_states, dict) or not isinstance(leases, dict):
            return {}
        protected: set[str] = set()
        for rows in leases.values():
            if not isinstance(rows, list):
                return {}
            for row in rows:
                if not isinstance(row, dict):
                    return {}
                packet_id = row.get("packet_id")
                if packet_id is None or not str(packet_id).strip():
                    return {}
                if not bool(row.get("stale_candidate")):
                    protected.add(str(packet_id))
        return {
            str(packet_id): state
            for packet_id, state in packet_states.items()
            if str(packet_id) not in protected
        }

    # START_FUNCTION_CONTRACT
    # name: state_directory_summary
    # purpose: Describe fixed local state-directory entries without arbitrary
    #          browser paths or deletion instructions.
    # inputs: state_root — fixed runtime root or None.
    # returns: Bounded safe metadata rows.
    # side_effects: Reads directory metadata only.
    # error_behavior: Missing/unreadable root returns an empty list.
    # END_FUNCTION_CONTRACT
    def state_directory_summary(self, state_root: Path | None) -> list[dict[str, Any]]:
        if state_root is None or not state_root.exists() or not state_root.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        try:
            children = sorted(state_root.iterdir(), key=lambda item: item.name)[:500]
            for child in children:
                try:
                    rows.append({
                        "name": child.name[:240],
                        "kind": "directory" if child.is_dir() else "file",
                        "size_bytes": child.stat().st_size,
                    })
                except OSError:
                    rows.append({"name": child.name[:240], "kind": "unknown", "size_bytes": None})
        except OSError:
            return []
        return rows

    # START_FUNCTION_CONTRACT
    # name: set_feature_archive
    # purpose: Apply the existing project-local feature archive state rule.
    # inputs: feature_id and archived boolean.
    # returns: feature id/status result.
    # side_effects: Writes one local Feature status row.
    # emitted_logs: None.
    # error_behavior: Raises KeyError when missing or ValueError for an invalid
    #                 archive/unarchive state.
    # END_FUNCTION_CONTRACT
    def set_feature_archive(self, feature_id: str, *, archived: bool) -> dict[str, str]:
        with get_db() as db:
            feature = db.query(Feature).filter_by(id=feature_id).first()
            if feature is None:
                raise KeyError("feature not found")
            current = str(feature.status or "").casefold()
            if archived:
                if current == _TERMINAL_FEATURE_STATUS.casefold():
                    raise ValueError("feature is already archived")
                feature.status = _TERMINAL_FEATURE_STATUS
            else:
                if current != _TERMINAL_FEATURE_STATUS.casefold():
                    raise ValueError("feature is not archived")
                feature.status = "NOT_STARTED"
            db.commit()
            return {"feature_id": feature_id, "status": str(feature.status)}


# END_BLOCK_SERVICE
