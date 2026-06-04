# ############################################################################
# AI_HEADER: recovery_router
# ROLE: Recovery API endpoints — evaluate, history, feature summary.
# Phase 3 of TZ-017 escalation policy.
# ############################################################################

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class EvaluateRequest(BaseModel):
    apply: bool = False


@router.post("/evaluate/{packet_id}")
async def evaluate_packet(packet_id: str, req: EvaluateRequest) -> dict:
    """
    POST /api/recovery/evaluate/{packet_id}
    Builds FailureSignal -> classify -> decide -> persist -> optionally apply.
    Returns RecoveryDecision with decision_id, action, reason, next_executor_hint.
    """
    from grace_control.core.recovery_controller import RecoveryController

    controller = RecoveryController()
    decision = await controller.evaluate(packet_id, allow_apply=req.apply)

    return {
        "data": {
            "packet_id": packet_id,
            "decision_id": decision.audit_payload.get("decision_id", ""),
            "failure_class": decision.failure_class.value,
            "action": decision.action.value,
            "reason": decision.reason,
            "next_executor_hint": decision.next_executor_hint,
            "max_attempts_reached": decision.max_attempts_reached,
            "status": "applied" if req.apply else "proposed",
        },
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
    }


@router.get("/packets/{packet_id}")
async def get_packet_recovery(packet_id: str) -> dict:
    """
    GET /api/recovery/packets/{packet_id}
    Returns recovery history for a packet.
    """
    from grace_control.db import get_db
    from grace_control.db.schema import PacketRun

    with get_db() as db:
        runs = db.query(PacketRun).filter_by(packet_id=packet_id).order_by(
            PacketRun.run_number.desc()
        ).limit(20).all()

        decisions = []
        for r in runs:
            rj = r.result_json or {}
            rec = rj.get("recovery", {})
            if rec:
                decisions.append(rec)

    return {
        "data": {
            "packet_id": packet_id,
            "decisions": decisions,
            "total": len(decisions),
        },
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
    }


@router.get("/features/{feature_id}")
async def get_feature_recovery(feature_id: str) -> dict:
    """
    GET /api/recovery/features/{feature_id}
    Returns recovery summary for all packets in a feature.
    """
    from grace_control.db import get_db
    from grace_control.db.schema import Packet, PacketRun

    with get_db() as db:
        packets = db.query(Packet).filter_by(feature_id=feature_id).all()
        summary = []
        for p in packets:
            runs = db.query(PacketRun).filter_by(packet_id=p.id).order_by(
                PacketRun.run_number.desc()
            ).limit(5).all()
            for r in runs:
                rj = r.result_json or {}
                rec = rj.get("recovery", {})
                if rec:
                    summary.append({
                        "packet_id": p.id,
                        "run_id": r.id,
                        "decision": rec,
                    })
                    break

    return {
        "data": {
            "feature_id": feature_id,
            "packets_with_recovery": len(summary),
            "decisions": summary,
        },
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
    }
