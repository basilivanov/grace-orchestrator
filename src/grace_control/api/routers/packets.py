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
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from grace_control.core.event_recorder import record_event
from grace_control.core.state_machine import PacketStateMachine
from grace_control.core.structured_logger import GraceLogger, trace_context
from grace_control.core.telegram_notify import notify_event
from grace_control.db import get_db
from grace_control.db.schema import Lease, Packet, PacketRun, PacketState, Worker
from grace_control.api.ws_broadcast import broadcast_event

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
                expires_at=datetime.utcnow() + timedelta(minutes=5),
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
                         {"worker_id": worker_id, "attempt": packet.attempt_count}, db=db)
            await notify_event("packet_claimed", packet.id, worker_id=worker_id)
            await broadcast_event("state_change", {"packet_id": packet.id, "state": "running", "worker_id": worker_id})

            return {
                "data": {
                    "packet_id": packet.id,
                    "spec": packet.spec_json,
                    "lease_id": lease.id,
                    "expires_at": lease.expires_at.isoformat() + "Z",
                },
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        from grace_control.core.wave_gate import check_wave_gates
        check_wave_gates()
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
        elif status == "blocked" or result.get("domain_status") == "blocked":
            target = PacketState.BLOCKED
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
                     {"worker_id": worker_id, "state": target.value}, db=db)
        await notify_event("packet_released", packet.id, worker_id=worker_id, state=target.value)
        await broadcast_event("state_change", {"packet_id": packet.id, "state": target.value})

        return {
            "data": {"packet_id": packet.id, "state": packet.state, "released": True},
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


@router.post("/{packet_id}/cancel")
async def cancel_packet(packet_id: str, request: dict) -> dict:
    """Cancel packet: READY/RUNNING/REJECTED → CANCELLED. Releases lease if present."""
    try:
        reason = request.get("reason", "No reason provided")

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                raise HTTPException(status_code=404, detail="Packet not found")

            current = PacketState(packet.state)
            if current in (PacketState.MERGED, PacketState.FAILED, PacketState.BLOCKED, PacketState.CANCELLED):
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
            record_event("packet_cancelled", "packet", packet.id, {"reason": reason}, db=db)
            await notify_event("packet_cancelled", packet.id, reason=reason)

            return {
                "data": {"packet_id": packet.id, "state": packet.state, "reason": reason},
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
    except HTTPException:
        raise
    except Exception:
        return JSONResponse(
            {"error": {"code": "INTERNAL_ERROR", "message": "Cancel failed"}},
            status_code=500,
        )


@router.post("/{packet_id}/merge")
async def merge_packet(packet_id: str, request: dict) -> dict:
    """Merge accepted packet: ACCEPTED → MERGED. Uses target_repo_root, no stash."""
    commit_sha = request.get("commit_sha", "")
    worktree_path = request.get("worktree_path", "")
    branch_name = request.get("branch_name", "")
    target_repo_root = request.get("target_repo_root") or os.environ.get("GRACE_TARGET_REPO_ROOT") or ""

    if not worktree_path or not branch_name:
        raise HTTPException(status_code=400,
            detail="worktree_path and branch_name are required for merge")

    import subprocess as _sp
    from pathlib import Path

    repo = Path(target_repo_root).resolve() if target_repo_root else Path.cwd().resolve()

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise HTTPException(status_code=404, detail="Packet not found")

        current = PacketState(packet.state)
        if current != PacketState.ACCEPTED:
            raise HTTPException(status_code=400,
                detail=f"Can only merge ACCEPTED packets, got {current.value}")

        # Validate target repo and worktree/branch
        if not repo.exists():
            raise HTTPException(status_code=400, detail=f"target_repo_root does not exist: {repo}")
        try:
            _sp.run(["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
                    capture_output=True, timeout=10, check=True)
        except Exception:
            raise HTTPException(status_code=400, detail=f"target_repo_root is not a git repo: {repo}")

        wt = Path(worktree_path)
        if not wt.exists():
            _log.warn("merge_worktree_not_found", packet_id=packet.id, worktree=worktree_path)
        try:
            rev = _sp.run(["git", "-C", str(repo), "rev-parse", "--verify", branch_name],
                          capture_output=True, timeout=10)
            if rev.returncode != 0:
                raise HTTPException(status_code=400, detail=f"branch does not exist: {branch_name}")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail=f"cannot verify branch: {branch_name}")

        # Check for dirty target repo (no stash)
        allow_dirty = os.environ.get("GRACE_ALLOW_DIRTY_TARGET_MERGE") == "true"
        if not allow_dirty:
            try:
                status = _sp.run(["git", "-C", str(repo), "status", "--porcelain"],
                                 capture_output=True, text=True, timeout=10)
                if status.stdout.strip():
                    _log.warn("dirty_target_repo", packet_id=packet.id, repo=str(repo))
                    record_event("packet_merge_failed", "packet", packet.id,
                                 {"reason": "DIRTY_TARGET_REPO", "repo": str(repo)}, db=db)
                    raise HTTPException(status_code=409,
                        detail={"merge_failed": "DIRTY_TARGET_REPO",
                                "message": "Target repo has uncommitted changes. Commit or stash them manually."})
            except HTTPException:
                raise
            except Exception:
                pass

        # Attempt git merge BEFORE state transition
        merge_ok = True
        merge_stderr = ""
        try:
            mr = _sp.run(["git", "merge", branch_name, "--no-edit", "--no-ff"],
                         cwd=str(repo), capture_output=True, text=True, timeout=30)
            if mr.returncode != 0:
                merge_ok = False
                merge_stderr = mr.stderr[:500]
                _log.warn("merge_failed", packet_id=packet.id, stderr=merge_stderr)
        except Exception as e:
            merge_ok = False
            merge_stderr = str(e)[:200]
            _log.warn("merge_failed", packet_id=packet.id, error=merge_stderr)

        # If git merge failed, do NOT transition to MERGED
        if not merge_ok:
            record_event("packet_merge_failed", "packet", packet.id,
                         {"branch": branch_name, "worktree": worktree_path,
                          "target_repo": str(repo), "stderr": merge_stderr,
                          "commit_sha": commit_sha}, db=db)
            raise HTTPException(status_code=409,
                detail={"merge_failed": f"git merge of {branch_name} failed",
                        "stderr": merge_stderr})

        # State transition only after successful merge
        _state_machine.transition(current, PacketState.MERGED)
        packet.state = PacketState.MERGED.value

        # Clean up worktree (prefer git worktree remove over shutil.rmtree)
        if worktree_path:
            try:
                if wt.exists():
                    import shutil
                    try:
                        _sp.run(["git", "worktree", "remove", str(wt), "--force"],
                                cwd=str(repo), capture_output=True, timeout=10)
                    except Exception:
                        pass
                    if wt.exists():
                        shutil.rmtree(wt)
            except Exception:
                pass

        _log.info("packet_merged", packet_id=packet.id, commit_sha=commit_sha,
                   target_repo=str(repo))
        record_event("packet_merged", "packet", packet.id,
                     {"commit_sha": commit_sha, "target_repo": str(repo), "branch": branch_name,
                      "worktree": worktree_path}, db=db)

        return {
            "data": {"packet_id": packet.id, "state": packet.state, "commit_sha": commit_sha},
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
