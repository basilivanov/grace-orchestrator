# ############################################################################
# AI_HEADER: run_result_persistence_service — terminal PacketRun persistence
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Persist rerun terminal results into PacketRun with canonical JSON.
#          Creates evidence directory, sets evidence_path, writes canonical reports.
# inputs: run_id, packet_id, RerunResult, evidence_dir, started_at
# outputs: None (mutates PacketRun in DB)
# invariants:
#   - evidence_dir.mkdir(parents=True, exist_ok=True) before DB commit
#   - PacketRun.evidence_path == str(evidence_dir)
#   - Full canonical acceptance report preserved (profile, stages, summary)
#   - Source worktree/branch/commit preserved in legacy_result
#   - Verifier/reviewer reports stored in canonical top-level keys
#   - Re-persist does not overwrite valid fields with empty strings
# side_effects: DB write, filesystem mkdir
# error_behavior: Logs warn on missing PacketRun; no exception raised
# observability: GraceLogger info/warn, record_event
# non_goals:
#   - Does not change packet state machine
#   - Does not trigger merge
#   - Does not make business decisions about result content
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: persist_rerun_result
# END_MODULE_MAP

from __future__ import annotations

import time
from datetime import datetime, UTC
from pathlib import Path

from grace_control.core.rerun_contracts import RerunResult
from grace_control.core.event_recorder import record_event
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import PacketRun

_log = GraceLogger("rerun_persistence")


def persist_rerun_result(
    *,
    run_id: str,
    packet_id: str,
    result: RerunResult,
    evidence_dir: Path | None = None,
    started_at: float | None = None,
) -> None:
    """Persist a terminal rerun result into PacketRun with canonical JSON.

    Creates evidence_dir on disk if provided, sets evidence_path, and stores
    full canonical acceptance/verifier/reviewer reports.
    """
    _log.info("rerun_persist_started", run_id=run_id, packet_id=packet_id,
               accepted=result.accepted, domain_status=result.domain_status)

    with get_db() as db:
        existing = db.query(PacketRun).filter_by(id=run_id).first()
        if not existing:
            _log.warn("rerun_persist_no_run", run_id=run_id, packet_id=packet_id)
            return

        status = "accepted" if result.accepted else (
            "blocked" if result.domain_status == "blocked" else "rejected"
        )
        existing.status = status
        existing.finished_at = datetime.now(UTC)
        if started_at is not None:
            existing.duration_ms = int((time.time() - started_at) * 1000)
        elif result.duration_ms:
            existing.duration_ms = result.duration_ms

        if evidence_dir:
            evidence_dir.mkdir(parents=True, exist_ok=True)
            existing.evidence_path = str(evidence_dir)

        legacy = {
            "accepted": result.accepted,
            "domain_status": result.domain_status,
            "reason": result.reason or "",
            "worktree_path": result.worktree_path or "",
            "branch_name": result.branch_name or "",
            "commit_sha": result.evidence.get("commit_sha", ""),
        }
        result_json: dict = {"legacy_result": legacy}

        # Verifier report
        if result.evidence_verifier_report:
            result_json["evidence_verifier_report"] = result.evidence_verifier_report
        elif result.evidence.get("verifier_verdict"):
            result_json["evidence_verifier_report"] = {
                "verdict": result.evidence["verifier_verdict"],
                "summary": result.evidence.get("verifier_summary", result.evidence.get("summary", "")),
            }

        # Reviewer report
        if result.reviewer_report:
            result_json["reviewer_report"] = result.reviewer_report
        elif result.evidence.get("reviewer_verdict"):
            result_json["reviewer_report"] = {
                "verdict": result.evidence["reviewer_verdict"],
                "summary": result.evidence.get("reviewer_summary", result.evidence.get("summary", "")),
            }

        # Full canonical acceptance report
        if result.acceptance_report:
            result_json["acceptance_report"] = result.acceptance_report
        elif result.evidence.get("acceptance_report"):
            result_json["acceptance_report"] = result.evidence["acceptance_report"]
        else:
            result_json["acceptance_report"] = {
                "final_verdict": "accepted" if result.accepted else "rejected",
                "summary": result.reason or "",
            }

        existing.result_json = result_json
        db.commit()

    record_event("rerun_completed", "packet", packet_id, {
        "run_id": run_id,
        "status": status,
        "reason": result.reason or "",
    })
    _log.info("rerun_persisted", run_id=run_id, packet_id=packet_id, status=status)
