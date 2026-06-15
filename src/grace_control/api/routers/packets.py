# ############################################################################
# AI_HEADER: packets_router
# ROLE: FastAPI router for /api/packets/ — list, get, claim, release, cancel, merge.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose packet CRUD + lifecycle operations via REST API.
# inputs: HTTP requests with JSON bodies.
# returns: JSON responses with data/timestamp envelope.
# side_effects: DB reads/writes, state transitions, lease management.
# emitted_logs: None.
# error_behavior: Returns 404/400/422 on invalid requests.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: list_packets
#   - function: get_packet
#   - function: claim_packet
#   - function: release_packet
#   - function: cancel_packet
#   - function: merge_packet
# END_MODULE_MAP

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from grace_control.api.ws_broadcast import broadcast_event
from grace_control.core.event_recorder import record_event
from grace_control.core.structured_logger import GraceLogger
from grace_control.core.telegram_notify import notify_event
from grace_control.db import get_db
from grace_control.db.schema import Lease, Packet, PacketRun, PacketState, Worker

router = APIRouter()
_log = GraceLogger("packets")


@router.get("/")
async def list_packets(state: str | None = None, feature_id: str | None = None) -> dict:
    with get_db() as db:
        query = db.query(Packet)
        if state:
            query = query.filter_by(state=state)
        if feature_id:
            query = query.filter_by(feature_id=feature_id)
        packets = query.all()
        return {
            "data": [
                {
                    "id": p.id, "feature_id": p.feature_id, "wave_id": p.wave_id,
                    "slug": p.slug, "title": p.title, "state": p.state,
                    "acceptance_profile": p.acceptance_profile,
                    "attempt_count": p.attempt_count, "max_attempts": p.max_attempts,
                    "created_at": p.created_at.isoformat() + "Z",
                    "updated_at": p.updated_at.isoformat() + "Z",
                }
                for p in packets
            ],
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }


@router.get("/{packet_id}")
async def get_packet(packet_id: str) -> dict:
    with get_db() as db:
        p = db.query(Packet).filter_by(id=packet_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Packet not found")
        runs = db.query(PacketRun).filter_by(packet_id=packet_id).all()
        recovery_data = None
        for r in runs:
            rj = r.result_json or {}
            rec = rj.get("recovery", {})
            if rec:
                recovery_data = {
                    "failure_class": rec.get("failure_class", ""),
                    "action": rec.get("action", ""),
                    "reason": rec.get("reason", ""),
                    "current_executor_id": rec.get("current_executor_id", ""),
                    "next_executor_hint": rec.get("next_executor_hint", ""),
                    "decision_id": rec.get("decision_id", ""),
                }
                break
        return {
            "data": {
                "id": p.id, "feature_id": p.feature_id, "wave_id": p.wave_id,
                "slug": p.slug, "title": p.title,
                "description": p.description or "", "state": p.state,
                "acceptance_profile": p.acceptance_profile,
                "attempt_count": p.attempt_count, "max_attempts": p.max_attempts,
                "spec_json": p.spec_json,
                "recovery": recovery_data,
                "runs": [
                    {
                        "id": r.id, "run_number": r.run_number, "status": r.status,
                        "evidence_path": r.evidence_path,
                        "started_at": r.started_at.isoformat() + "Z" if r.started_at else None,
                        "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else None,
                        "duration_ms": r.duration_ms,
                    }
                    for r in runs
                ],
                "created_at": p.created_at.isoformat() + "Z",
                "updated_at": p.updated_at.isoformat() + "Z",
            },
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }


@router.post("/claim")
async def claim_packet(request: dict) -> dict:
    """Claim next READY packet per FIFO queue discipline.

    Delegates to QueueService for deterministic feature/wave/packet ordering.
    Then delegates to PacketService.claim for the actual state transition.
    """
    worker_id = request["worker_id"]

    from grace_control.services.queue_service import claim_next
    packet_id, reason = claim_next(worker_id)

    if packet_id is None:
        from grace_control.core.wave_gate import check_wave_gates
        check_wave_gates()
        detail = reason or "No packets available"
        raise HTTPException(status_code=404, detail=detail)

    from grace_control.services.packet_service import PacketService, PacketNotFoundError, StateTransitionError
    svc = PacketService()

    try:
        result = await svc.claim(packet_id, worker_id)
    except (StateTransitionError, PacketNotFoundError) as e:
        from grace_control.core.wave_gate import check_wave_gates
        check_wave_gates()
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "data": {
            "packet_id": result.packet_id,
            "spec": result.spec,
            "lease_id": result.lease_id,
            "claimed_attempt": result.claimed_attempt,
            "expires_at": result.expires_at.isoformat() + "Z",
            "attempt": result.attempt,
            "feature_id": result.feature_id,
            "wave_id": result.wave_id,
            "slug": result.slug,
            "title": result.title,
            "description": result.description,
            "acceptance_profile": result.acceptance_profile,
            "max_attempts": result.max_attempts,
        },
        "timestamp": datetime.now(UTC).isoformat() + "Z",
    }


@router.post("/{packet_id}/release")
async def release_packet(packet_id: str, request: dict) -> dict:
    """Release packet after execution. Delegates state transition to PacketService.

    W01: Release now requires worker_id, lease_id, and claimed_attempt for
    lease fencing. If any check fails, returns 409 with stale_lease detail.
    """
    # W01: Fencing tokens are REQUIRED for release of leased packets.
    # The service layer will reject missing tokens when a lease exists.
    # API-level validation: reject clearly malformed requests early.
    worker_id = request.get("worker_id", "")
    status = request["status"]
    result = request.get("result", {})
    lease_id = request.get("lease_id")
    claimed_attempt = request.get("claimed_attempt")

    if status == "accepted" and not result.get("accepted"):
        status = "rejected"

    from grace_control.services.packet_service import PacketService, PacketNotFoundError, StaleLeaseError
    svc = PacketService()
    try:
        await svc.release(
            packet_id, status, result,
            worker_id=worker_id,
            lease_id=lease_id,
            claimed_attempt=claimed_attempt,
        )
    except StaleLeaseError as e:
        raise HTTPException(status_code=409, detail={
            "stale_lease": True,
            "reason": str(e),
            "packet_id": packet_id,
        })
    except PacketNotFoundError:
        raise HTTPException(status_code=404, detail="Packet not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    with get_db() as db:
        worker = db.query(Worker).filter_by(id=worker_id).first()
        if worker:
            worker.current_packet_id = None
            worker.status = "idle"
        packet = db.query(Packet).filter_by(id=packet_id).first()
        new_state = packet.state if packet else status

    _log.info("packet_released", packet_id=packet_id, state=new_state, worker_id=worker_id)
    return {
        "data": {"packet_id": packet_id, "state": new_state, "released": True},
        "timestamp": datetime.now(UTC).isoformat() + "Z",
    }


@router.post("/{packet_id}/renew-lease")
async def renew_lease(packet_id: str, request: dict) -> dict:
    """W01: Renew active lease for a packet. Only matching worker+lease can renew.

    Extends the lease TTL. Returns new expires_at on success.
    Returns 409 on stale/expired lease or ownership mismatch.
    """
    worker_id = request.get("worker_id", "")
    lease_id = request.get("lease_id")

    if not worker_id or lease_id is None:
        raise HTTPException(status_code=422,
            detail="worker_id and lease_id are required for lease renewal")

    from grace_control.services.packet_service import PacketService, StaleLeaseError, PacketNotFoundError
    svc = PacketService()
    try:
        new_expires = await svc.renew_lease(packet_id, worker_id, lease_id)
    except StaleLeaseError as e:
        raise HTTPException(status_code=409, detail={
            "stale_lease": True,
            "reason": str(e),
            "packet_id": packet_id,
        })
    except PacketNotFoundError:
        raise HTTPException(status_code=404, detail="Packet not found")

    return {
        "data": {
            "packet_id": packet_id,
            "lease_id": lease_id,
            "expires_at": new_expires.isoformat() + "Z",
            "renewed": True,
        },
        "timestamp": datetime.now(UTC).isoformat() + "Z",
    }


@router.post("/{packet_id}/cancel")
async def cancel_packet(packet_id: str, request: dict) -> dict:
    """Cancel packet: any non-terminal state → CANCELLED. Delegates to PacketService.

    The router only translates service exceptions to HTTP responses. All DB
    state work (transition + lease release + worker cleanup) is owned by
    `PacketService.cancel` (P1#4 from post-refactor audit).
    """
    from grace_control.services.packet_service import (
        PacketNotFoundError,
        PacketService,
        StateTransitionError,
    )

    reason = request.get("reason", "No reason provided")

    try:
        svc = PacketService()
        result = await svc.cancel(packet_id, reason)
    except PacketNotFoundError:
        raise HTTPException(status_code=404, detail="Packet not found")
    except StateTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Best-effort observability; never fail cancel on these.
    try:
        record_event("packet_cancelled", "packet", result.packet_id, {"reason": reason})
    except Exception:
        pass
    try:
        await notify_event("packet_cancelled", result.packet_id, reason=reason)
    except Exception:
        pass
    try:
        await broadcast_event("state_change", {"packet_id": result.packet_id, "state": "cancelled"})
    except Exception:
        pass

    return {
        "data": {"packet_id": result.packet_id, "state": result.state, "reason": reason},
        "timestamp": datetime.now(UTC).isoformat() + "Z",
    }

@router.post("/{packet_id}/retry")
async def retry_packet(packet_id: str, request: dict) -> dict:
    """Retry a REJECTED packet: REJECTED → READY via API (no DB race)."""
    from grace_control.services.packet_service import PacketService, MaxRetriesReachedError
    from grace_control.core.state_machine import StateTransitionError
    try:
        await PacketService().retry(packet_id)
    except MaxRetriesReachedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except StateTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "data": {"packet_id": packet_id, "state": "ready"},
        "timestamp": datetime.now(UTC).isoformat() + "Z",
    }


@router.post("/{packet_id}/merge")
async def merge_packet(packet_id: str, request: dict) -> dict:
    """Merge accepted packet: ACCEPTED → MERGED. Delegates to MergeService."""
    from grace_control.config.settings import settings as _settings
    from grace_control.services.merge_service import MergeService
    from grace_control.db.schema import PacketState as _PS

    worktree_path = request.get("worktree_path", "")
    branch_name = request.get("branch_name", "")
    target_branch = request.get("target_branch") or _settings.target_branch
    target_repo_root = (
        request.get("target_repo_root")
        or os.environ.get("GRACE_TARGET_REPO_ROOT")
        or _settings.target_repo_root
    )

    if not worktree_path or not branch_name:
        raise HTTPException(status_code=400,
            detail="worktree_path and branch_name are required for merge")

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise HTTPException(status_code=404, detail="Packet not found")
        current = _PS(packet.state)
        if current != _PS.ACCEPTED:
            raise HTTPException(status_code=400,
                detail=f"Can only merge ACCEPTED packets, got {current.value}")

    if not target_repo_root:
        raise HTTPException(status_code=400, detail="target_repo_root is required")

    svc = MergeService()
    result = await svc.merge_packet(
        packet_id=packet_id,
        target_repo_root=target_repo_root,
        branch_name=branch_name,
        target_branch=target_branch,
    )

    if not result.success:
        _log.warn("merge_failed", packet_id=packet_id, error=result.error[:200])
        try:
            with get_db() as db:
                from grace_control.api.ws_events import record_event as _rec
                _rec("packet_merge_failed", "packet", packet_id, {
                    "branch": branch_name, "error": result.error,
                }, db=db)
        except Exception as _evt_err:
            _log.warn("merge_event_record_failed",
                packet_id=packet_id, error=str(_evt_err)[:200])
        raise HTTPException(status_code=409,
            detail={"merge_failed": result.error, "packet_id": packet_id})

    try:
        with get_db() as db:
            from grace_control.api.ws_events import record_event as _rec
            _rec("packet_merged", "packet", packet_id, {
                "commit_sha": result.commit_sha, "target_repo": result.target_repo,
                "branch": branch_name,
            }, db=db)
    except Exception as _evt_err:
        _log.warn("merged_event_record_failed",
            packet_id=packet_id, error=str(_evt_err)[:200])

    if worktree_path:
        from pathlib import Path as _P
        await svc.cleanup_worktree(
            _P(worktree_path), branch_name,
            target_repo_root=_P(target_repo_root) if target_repo_root else None,
        )

    _log.info("packet_merged", packet_id=packet_id,
        commit_sha=result.commit_sha, target_repo=result.target_repo)
    return {
        "data": {"packet_id": packet_id, "state": "merged", "commit_sha": result.commit_sha},
        "timestamp": datetime.now(UTC).isoformat() + "Z",
    }


@router.get("/{packet_id}/runtime-diagnostics")
async def get_packet_runtime_diagnostics(packet_id: str) -> dict:
    """Return runtime diagnostics for a packet — scope enforcement, diff,
    failure code, changed files. Built from the latest run's result_json."""
    with get_db() as db:
        p = db.query(Packet).filter_by(id=packet_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Packet not found")
        run = db.query(PacketRun).filter_by(packet_id=packet_id).order_by(
            PacketRun.run_number.desc()
        ).first()

    if not run:
        return {"data": {"packet_id": packet_id, "status": "no_runs",
                         "failure_code": None, "message": "No runs for this packet"},
                "timestamp": datetime.now(UTC).isoformat() + "Z"}

    rj = run.result_json or {}
    diagnostics = rj.get("diagnostics") or {}
    diagnostics_evidence = diagnostics.get("evidence") or rj.get("evidence", {})
    # Prefer evidence-embedded failure_code, fall back to top-level diagnostics key
    failure_code = diagnostics_evidence.get("failure_code") or diagnostics.get("failure_code")
    status = "failed" if failure_code else (p.state if p else "unknown")

    title = _FATAL_SCOPE_TITLES.get(failure_code or "", "Runtime error") if failure_code else "Success"
    details = ""
    changed = diagnostics_evidence.get("changed_files", [])
    scope = diagnostics_evidence.get("scope_enforcement", {})
    if isinstance(scope, dict):
        if scope.get("out_of_scope_files"):
            details = f"Files outside scope: {scope['out_of_scope_files']}"
        elif scope.get("frozen_touched_files"):
            details = f"Frozen scope changes: {scope['frozen_touched_files']}"
        if scope.get("summary"):
            details = details or scope["summary"]

    artifact_refs = diagnostics_evidence.get("artifact_refs", [])
    read_model = {
        "packet_id": packet_id,
        "status": status,
        "failure_code": failure_code,
        "title": title,
        "details": details,
        "changed_files": changed,
        "artifact_refs": artifact_refs,
        "run_id": run.id,
    }
    return {"data": read_model, "timestamp": datetime.now(UTC).isoformat() + "Z"}


_FATAL_SCOPE_TITLES = {
    "AGENT_CHANGED_OUT_OF_SCOPE": "Agent changed files outside allowed scope",
    "AGENT_TOUCHED_FROZEN_SCOPE": "Agent modified frozen scope files",
    "AGENT_SCOPE_ENFORCEMENT_FAILED": "Scope enforcement check failed",
    "AGENT_DIFF_INSPECTION_FAILED": "Diff inspection failed",
    "AGENT_NO_CHANGES_PRODUCED": "Agent produced no changes",
    "AGENT_WORKTREE_NOT_GIT": "Worktree is not a git repository",
}
