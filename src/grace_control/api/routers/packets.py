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

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from grace_control.core.event_recorder import record_event
from grace_control.core.state_machine import PacketStateMachine
from grace_control.core.structured_logger import GraceLogger, trace_context
from grace_control.core.telegram_notify import notify_event
from grace_control.db import get_db
from grace_control.db.schema import Lease, Packet, PacketRun, PacketState, Worker

router = APIRouter()
_state_machine = PacketStateMachine()
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
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


@router.get("/{packet_id}")
async def get_packet(packet_id: str) -> dict:
    with get_db() as db:
        p = db.query(Packet).filter_by(id=packet_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Packet not found")
        runs = db.query(PacketRun).filter_by(packet_id=packet_id).all()
        return {
            "data": {
                "id": p.id, "feature_id": p.feature_id, "wave_id": p.wave_id,
                "slug": p.slug, "title": p.title,
                "description": p.description or "", "state": p.state,
                "acceptance_profile": p.acceptance_profile,
                "attempt_count": p.attempt_count, "max_attempts": p.max_attempts,
                "spec_json": p.spec_json,
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
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


@router.post("/claim")
async def claim_packet(request: dict) -> dict:
    """Claim next READY packet. SOLE owner of READY→RUNNING transition.
    Multi-worker safe: unique constraint on lease(packet_id) prevents duplicate claims."""
    worker_id = request["worker_id"]

    with get_db() as db:
        ready = db.query(Packet).filter_by(state=PacketState.READY.value).all()

        for packet in ready:
            existing = db.query(Lease).filter_by(packet_id=packet.id).first()
            if existing:
                if existing.expires_at > datetime.utcnow():
                    continue
                db.delete(existing)

            lease = Lease(
                packet_id=packet.id,
                worker_id=worker_id,
                expires_at=datetime.utcnow() + timedelta(minutes=30),
            )
            db.add(lease)
            db.flush()  # populate lease.id before return

            _state_machine.transition(PacketState(packet.state), PacketState.RUNNING)
            packet.state = PacketState.RUNNING.value
            packet.attempt_count += 1

            worker = db.query(Worker).filter_by(id=worker_id).first()
            if worker:
                worker.current_packet_id = packet.id

            _log.info("packet_claimed", packet_id=packet.id, worker_id=worker_id,
                       attempt=packet.attempt_count)
            record_event("packet_claimed", "packet", packet.id,
                         {"worker_id": worker_id, "attempt": packet.attempt_count})
            await notify_event("packet_claimed", packet.id, worker_id=worker_id)

            return {
                "data": {
                    "packet_id": packet.id,
                    "spec": packet.spec_json,
                    "lease_id": lease.id,
                    "expires_at": lease.expires_at.isoformat() + "Z",
                },
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        raise HTTPException(status_code=404, detail="No packets available")


@router.post("/{packet_id}/release")
async def release_packet(packet_id: str, request: dict) -> dict:
    """Release packet after execution. RUNNING→ACCEPTED/REJECTED/FAILED."""
    worker_id = request["worker_id"]
    status = request["status"]
    result = request.get("result", {})

    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id=packet_id).first()
        if lease:
            db.delete(lease)

        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise HTTPException(status_code=404, detail="Packet not found")

        if status == "accepted" and result.get("accepted"):
            target = PacketState.ACCEPTED
        elif status == "rejected":
            target = PacketState.REJECTED
        else:
            target = PacketState.FAILED

        _state_machine.transition(PacketState(packet.state), target)
        packet.state = target.value

        worker = db.query(Worker).filter_by(id=worker_id).first()
        if worker:
            worker.current_packet_id = None
            worker.status = "idle"

        _log.info("packet_released", packet_id=packet.id, state=target.value,
                   worker_id=worker_id)
        record_event("packet_released", "packet", packet.id,
                     {"worker_id": worker_id, "state": target.value})
        await notify_event("packet_released", packet.id, worker_id=worker_id, state=target.value)

        return {
            "data": {"packet_id": packet.id, "state": packet.state, "released": True},
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


@router.post("/{packet_id}/cancel")
async def cancel_packet(packet_id: str, request: dict) -> dict:
    """Cancel packet: READY/RUNNING/REJECTED → CANCELLED. Releases lease if present."""
    reason = request.get("reason", "No reason provided")

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise HTTPException(status_code=404, detail="Packet not found")

        current = PacketState(packet.state)
        if current in (PacketState.MERGED, PacketState.FAILED, PacketState.CANCELLED):
            raise HTTPException(status_code=400, detail=f"Cannot cancel terminal packet: {current.value}")

        lease = db.query(Lease).filter_by(packet_id=packet_id).first()
        if lease:
            db.delete(lease)
            worker = db.query(Worker).filter_by(id=lease.worker_id).first()
            if worker:
                worker.current_packet_id = None

        _state_machine.transition(current, PacketState.CANCELLED)
        packet.state = PacketState.CANCELLED.value

        _log.info("packet_cancelled", packet_id=packet.id, reason=reason)
        record_event("packet_cancelled", "packet", packet.id, {"reason": reason})
        await notify_event("packet_cancelled", packet.id, reason=reason)

        return {
            "data": {"packet_id": packet.id, "state": packet.state, "reason": reason},
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


@router.post("/{packet_id}/merge")
async def merge_packet(packet_id: str, request: dict) -> dict:
    """Merge accepted packet: ACCEPTED → MERGED. Attempts git merge + push if worktree_path provided."""
    commit_sha = request.get("commit_sha", "")
    worktree_path = request.get("worktree_path", "")
    branch_name = request.get("branch_name", "")

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise HTTPException(status_code=404, detail="Packet not found")

        current = PacketState(packet.state)
        if current != PacketState.ACCEPTED:
            raise HTTPException(status_code=400,
                detail=f"Can only merge ACCEPTED packets, got {current.value}")

        _state_machine.transition(current, PacketState.MERGED)
        packet.state = PacketState.MERGED.value

        if worktree_path and branch_name:
            try:
                from pathlib import Path
                from prefect_grace.platform.git_mutation_gate import run_git_mutation_gate
                wt = Path(worktree_path)
                if wt.exists():
                    result = run_git_mutation_gate(
                        packet=wt / "EXECUTION_PACKET.md",
                        repo_root=Path.cwd(),
                        worktree_root=wt.parent,
                        worktree_path=wt,
                        project_key=packet.feature_id.split("-", 1)[0].lower() if "-" in packet.feature_id else "grace",
                        packet_id=packet.id,
                        attempt=packet.attempt_count,
                        base_ref="HEAD",
                        target_branch="main",
                        remote="origin",
                        apply=not request.get("dry_run", False),
                        commit=True,
                        push=True,
                        merge=True,
                        understand_merge=True,
                    )
                    commit_sha = result.commit_sha or commit_sha
                    # Clean up worktree after successful merge
                    try:
                        import shutil
                        if wt.exists():
                            shutil.rmtree(wt)
                    except Exception:
                        pass
            except Exception:
                pass

        _log.info("packet_merged", packet_id=packet.id, commit_sha=commit_sha)
        record_event("packet_merged", "packet", packet.id, {"commit_sha": commit_sha})

        return {
            "data": {"packet_id": packet.id, "state": packet.state, "commit_sha": commit_sha},
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
