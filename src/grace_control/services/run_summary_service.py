# ############################################################################
# AI_HEADER: run_summary_service
# ROLE: Per-packet last-failure and acceptance summary used by TraceService
#       and /api/diagnostics/state.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Produce a compact per-packet summary: latest run, acceptance
#          verdict, stages, and flattened blocking_issues.
# inputs: Session + packet_id.
# returns: dict | None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns None when the packet does not exist.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: RunSummaryService
#     methods:
#       - get_packet_summary
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from grace_control.db.schema import Packet, PacketRun


class RunSummaryService:
    """Per-packet last-failure and acceptance summary."""

    # START_FUNCTION_CONTRACT
    # name: get_packet_summary
    # purpose: Build a flat per-packet summary: state, attempts, latest run,
    #          acceptance verdict/summary, per-stage status, blocking issues.
    # inputs: db (Session), packet_id (str).
    # returns: dict | None — None when the packet does not exist.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def get_packet_summary(self, db: Session, packet_id: str) -> dict[str, Any] | None:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return None
        runs = (
            db.query(PacketRun)
            .filter_by(packet_id=packet_id)
            .order_by(PacketRun.run_number.desc())
            .all()
        )
        latest = runs[0] if runs else None
        rj = (latest.result_json or {}) if latest else {}
        acc = rj.get("acceptance_report", {}) or {}
        stages = acc.get("stages", []) or []
        return {
            "packet_id": packet_id,
            "current_state": packet.state,
            "attempt_count": packet.attempt_count,
            "max_attempts": packet.max_attempts,
            "last_run": self._run_dict(latest) if latest else None,
            "acceptance_verdict": acc.get("final_verdict", ""),
            "acceptance_summary": acc.get("summary", ""),
            "stages": [
                {"name": s.get("name", ""), "status": s.get("status", "")}
                for s in stages
            ],
            "blocking_issues": [
                issue
                for s in stages
                for issue in (s.get("blocking_issues", []) or [])
            ],
        }

    def _run_dict(self, r: PacketRun) -> dict[str, Any]:
        return {
            "run_id": r.id,
            "run_number": r.run_number,
            "status": r.status,
            "executor_id": r.executor_id,
            "started_at": r.started_at.isoformat() + "Z" if r.started_at else "",
            "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else "",
            "duration_ms": r.duration_ms or 0,
        }
