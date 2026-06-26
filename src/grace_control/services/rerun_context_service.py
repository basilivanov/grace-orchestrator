# ############################################################################
# AI_HEADER: rerun_context_service — contextualize rerun from previous terminal run
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Find and validate the previous terminal PacketRun, return RerunContext.
# inputs: packet_id, current_run_id
# outputs: RerunContext | None
# invariants:
#   - Selects terminal run with maximum run_number (accepted/rejected/failed/blocked)
#   - Excludes current_run_id
#   - Requires acceptance_report with final_verdict
#   - Requires worktree_path that exists on disk
#   - Requires evidence_path (source_run_dir) that exists on disk
# side_effects: DB reads only
# error_behavior: Returns None when any invariant fails; logs structured reason
# observability: GraceLogger debug/info/warn per failure mode
# non_goals:
#   - Does not execute any stage
#   - Does not persist anything
#   - Does not decide what stage to run
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: load_previous_terminal_context
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from grace_control.core.rerun_contracts import RerunContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import PacketRun as PacketRunModel

_log = GraceLogger("rerun_context")


def load_previous_terminal_context(
    *,
    packet_id: str,
    current_run_id: str,
) -> RerunContext | None:
    """Find the latest terminal PacketRun and return validated RerunContext.

    Returns None when any required element is missing or invalid.
    """
    with get_db() as db:
        prev_run = db.query(PacketRunModel).filter(
            PacketRunModel.packet_id == packet_id,
            PacketRunModel.id != current_run_id,
            PacketRunModel.status.in_(["accepted", "rejected", "failed", "blocked"]),
        ).order_by(PacketRunModel.run_number.desc()).first()

        if not prev_run:
            _log.warn("rerun_context_missing", packet_id=packet_id,
                       reason="no previous terminal run")
            return None

        rj = prev_run.result_json or {}

        # Validate acceptance report
        acc = rj.get("acceptance_report") or {}
        if not acc or not isinstance(acc, dict) or not acc.get("final_verdict"):
            _log.warn("rerun_context_missing", packet_id=packet_id,
                       source_run_id=prev_run.id,
                       reason="acceptance_report missing or incomplete")
            return None

        # Validate worktree path
        legacy = rj.get("legacy_result") or {}
        if not isinstance(legacy, dict):
            _log.warn("rerun_context_missing", packet_id=packet_id,
                       source_run_id=prev_run.id,
                       reason="legacy_result missing")
            return None

        wt_path_str = legacy.get("worktree_path", "")
        if not wt_path_str:
            _log.warn("rerun_context_missing", packet_id=packet_id,
                       source_run_id=prev_run.id,
                       reason="worktree_path empty in legacy_result")
            return None

        wt_path = Path(wt_path_str)
        if not wt_path.exists():
            _log.warn("rerun_context_missing", packet_id=packet_id,
                       source_run_id=prev_run.id,
                       reason=f"worktree_path does not exist: {wt_path_str}")
            return None

        # Validate evidence path
        if not prev_run.evidence_path:
            _log.warn("rerun_context_missing", packet_id=packet_id,
                       source_run_id=prev_run.id,
                       reason="evidence_path is empty")
            return None

        run_dir = Path(prev_run.evidence_path)
        if not run_dir.exists():
            _log.warn("rerun_context_missing", packet_id=packet_id,
                       source_run_id=prev_run.id,
                       reason=f"evidence_path does not exist: {prev_run.evidence_path}")
            return None

        branch_name = legacy.get("branch_name", "")
        commit_sha = legacy.get("commit_sha", "")

        evr_data = rj.get("evidence_verifier_report") or {}
        rvr_data = rj.get("reviewer_report") or {}

        _log.info("rerun_context_loaded", packet_id=packet_id,
                   source_run_id=prev_run.id,
                   status=prev_run.status)

        return RerunContext(
            packet_id=packet_id,
            current_run_id=current_run_id,
            source_run_id=prev_run.id,
            source_run_number=prev_run.run_number,
            source_worktree_path=str(wt_path),
            source_run_dir=prev_run.evidence_path,
            branch_name=branch_name,
            commit_sha=commit_sha,
            acceptance_report=acc,
            evidence_verifier_report=evr_data if isinstance(evr_data, dict) and evr_data.get("verdict") else None,
            reviewer_report=rvr_data if isinstance(rvr_data, dict) and rvr_data.get("verdict") else None,
        )
