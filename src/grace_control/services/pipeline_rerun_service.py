"""Thin wrapper around _rerun_stage for testability."""
from __future__ import annotations

from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketRun


def execute_rerun(packet_id: str, stage_key: str, attempt: int) -> dict | None:
    """Execute a rerun for verifier/reviewer with full context loading.
    Returns result dict or None if context missing."""
    from grace_control.services.packet_control_service import consume_rerun_stage
    marker = consume_rerun_stage(packet_id, stage_key, attempt)
    if not marker:
        return {"error": "RERUN_MARKER_MISSING", "reason": f"no marker for {stage_key}"}

    with get_db() as db:
        pkt = db.query(Packet).filter_by(id=packet_id).first()
        if not pkt:
            return {"error": "PACKET_NOT_FOUND", "reason": "packet not found"}
        prev_run = db.query(PacketRun).filter(
            PacketRun.packet_id == packet_id,
            PacketRun.id != f"{packet_id}-R{attempt:02d}",
            PacketRun.status.in_(["accepted", "rejected", "failed", "blocked"]),
        ).order_by(PacketRun.run_number.desc()).first()
        if not prev_run:
            return {"error": "RERUN_CONTEXT_MISSING",
                    "reason": "no previous terminal run found"}

        rj = prev_run.result_json or {}
        acc = rj.get("acceptance_report") or {}
        evr = rj.get("evidence_verifier_report") or {}
        if not acc:
            return {"error": "RERUN_CONTEXT_MISSING",
                    "reason": "no acceptance report available"}

        if stage_key == "verifier":
            return _rerun_mock_verifier(acc, evr, prev_run)
        elif stage_key == "reviewer":
            ev_verdict = evr.get("verdict", "") if isinstance(evr, dict) else ""
            if ev_verdict != "PASS":
                return {"error": "RERUN_VERIFIER_CONTEXT_MISSING",
                        "reason": f"previous verifier verdict is {ev_verdict}, not PASS"}
            return _rerun_mock_reviewer(acc, evr, prev_run)
    return None


def _rerun_mock_verifier(acc: dict, evr: dict, prev_run: PacketRun) -> dict:
    """Placeholder: real execution uses _rerun_stage with LLM."""
    return {
        "result": "rerun_executed",
        "stage": "verifier",
        "acceptance_present": bool(acc),
        "prev_run_status": prev_run.status,
    }


def _rerun_mock_reviewer(acc: dict, evr: dict, prev_run: PacketRun) -> dict:
    return {
        "result": "rerun_executed",
        "stage": "reviewer",
        "verifier_report_present": bool(evr),
        "prev_run_status": prev_run.status,
    }
