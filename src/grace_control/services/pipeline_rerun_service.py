# ############################################################################
# AI_HEADER: pipeline_rerun_service — compatibility facade → real rerun services
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Thin compatibility facade for existing callers. Delegates to
#          rerun_context_service + rerun_pipeline_service + run_result_persistence_service.
#          No mock business logic.
# inputs: packet_id, stage_key, attempt
# outputs: dict with result/error
# side_effects: Delegates to real rerun services; DB reads and writes
# error_behavior: Returns error dict on any failure
# non_goals:
#   - Does not contain mock rerun logic
#   - Does not duplicate rerun pipeline rules
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: execute_rerun
# END_MODULE_MAP

from __future__ import annotations

from grace_control.services.packet_control_service import consume_rerun_stage
from grace_control.core.rerun_contracts import RerunStage
from grace_control.services.rerun_context_service import load_previous_terminal_context
from grace_control.services.rerun_pipeline_service import execute_rerun as _run_pipeline
from grace_control.services.run_result_persistence_service import persist_rerun_result
from grace_control.db import get_db
from grace_control.db.schema import Packet
from pathlib import Path
import time


def execute_rerun(packet_id: str, stage_key: str, attempt: int) -> dict | None:
    """Execute a rerun for verifier/reviewer with full context loading.

    Returns result dict or error dict. Compatible with legacy test callers.
    """
    marker = consume_rerun_stage(packet_id, stage_key, attempt)
    if not marker:
        return {"error": "RERUN_MARKER_MISSING", "reason": f"no marker for {stage_key}"}

    with get_db() as db:
        pkt = db.query(Packet).filter_by(id=packet_id).first()
        if not pkt:
            return {"error": "PACKET_NOT_FOUND", "reason": "packet not found"}

    run_id = f"{packet_id}-R{attempt:02d}"
    ctx = load_previous_terminal_context(
        packet_id=packet_id, current_run_id=run_id,
    )
    if not ctx:
        return {"error": "RERUN_CONTEXT_MISSING",
                "reason": "no previous terminal run found"}

    from grace_control.core.contracts import build_packet_contract
    pkt_data = {
        "id": pkt.id, "feature_id": pkt.feature_id, "wave_id": pkt.wave_id,
        "slug": pkt.slug, "title": pkt.title, "description": pkt.description,
        "spec_json": pkt.spec_json or {}, "state": pkt.state,
        "acceptance_profile": pkt.acceptance_profile or "NORMAL",
        "attempt_count": attempt, "max_attempts": pkt.max_attempts or 3,
    }
    pkt_contract = build_packet_contract(pkt_data)
    stage = RerunStage(stage_key)
    start = time.time()
    evidence_dir = Path("/tmp") / "rerun_evidence" / run_id

    import asyncio
    rr = asyncio.run(_run_pipeline(
        stage=stage, packet_contract=pkt_contract,
        context=ctx, current_evidence_dir=evidence_dir,
        started_at=start,
    ))

    persist_rerun_result(
        run_id=run_id, packet_id=packet_id,
        result=rr, evidence_dir=evidence_dir,
        started_at=start,
    )

    return {
        "result": "rerun_executed",
        "stage": stage_key,
        "accepted": rr.accepted,
        "domain_status": rr.domain_status,
        "reason": rr.reason,
    }
