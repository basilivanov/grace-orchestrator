# ############################################################################
# AI_HEADER: recovery_router
# ROLE: Recovery API endpoints — evaluate, history, feature summary.
# Phase 3 of TZ-017 escalation policy.
# ############################################################################

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()


class EvaluateRequest(BaseModel):
    apply: bool = False


class ArchitectRepackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=2000)
    verification: dict[str, list[str]]
    coder_instructions: list[str] = Field(default_factory=list, max_length=20)
    scope: list[str] | None = Field(default=None, max_length=100)
    frozen_scope: list[str] | None = Field(default=None, max_length=100)
    expected_evidence: list[dict[str, object]] | None = Field(
        default=None,
        max_length=100,
    )


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


# START_FUNCTION_CONTRACT
# name: repack_packet
# purpose: Create an audited replacement packet for an inconsistent terminal contract.
# inputs: packet_id and ArchitectRepackRequest containing complete replacement verification and optional architect-approved scope paths.
# returns: Replacement packet identity/state and whether a new row was created.
# side_effects: Inserts Packet/Event rows through create_architect_repack_packet.
# emitted_logs: architect_repack_created or architect_repack_reused in the service.
# error_behavior: HTTP 404 for missing packet, 409 for competing lineage, 422 for unsafe replacement.
# END_FUNCTION_CONTRACT
@router.post("/repack/{packet_id}")
async def repack_packet(packet_id: str, req: ArchitectRepackRequest) -> dict:
    from fastapi import HTTPException

    from grace_control.db import get_db
    from grace_control.services.rework_packet_service import (
        ArchitectRepackConflictError,
        ArchitectRepackValidationError,
        create_architect_repack_packet,
    )

    try:
        with get_db() as db:
            replacement, created = create_architect_repack_packet(
                db,
                original_packet_id=packet_id,
                verification=req.verification,
                reason=req.reason,
                coder_instructions=req.coder_instructions,
                scope=req.scope,
                frozen_scope=req.frozen_scope,
                expected_evidence=req.expected_evidence,
            )
            data = {
                "packet_id": replacement.id,
                "parent_packet_id": packet_id,
                "feature_id": replacement.feature_id,
                "wave_id": replacement.wave_id,
                "state": replacement.state,
                "acceptance_profile": replacement.acceptance_profile,
                "created": created,
            }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ArchitectRepackConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ArchitectRepackValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "data": data,
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
