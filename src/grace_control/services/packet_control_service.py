"""Control actions for packets: retry, cancel, delete, rerun-stage, stop-worker, dev-replay."""
from __future__ import annotations

import asyncio
import os
import signal
from datetime import datetime
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketRun, PacketState, Lease, Worker, Event, StageRun

_log = GraceLogger("packet_control")


def retry_packet(packet_id: str, actor: str | None = None, reason: str = "manual_retry") -> dict:
    """BLOCKED_RECOVERABLE or REJECTED -> READY, increments attempt_count."""
    from grace_control.core.state_machine import PacketStateMachine
    from grace_control.core.event_recorder import record_event

    sm = PacketStateMachine()
    with get_db() as db:
        pkt = db.query(Packet).filter_by(id=packet_id).first()
        if not pkt:
            raise ValueError(f"Packet {packet_id} not found")
        current = PacketStateMachine.normalize_state(pkt.state)
        if current not in (PacketState.BLOCKED_RECOVERABLE, PacketState.REJECTED):
            raise ValueError(f"Cannot retry from state {pkt.state}")
        sm.transition(current, PacketState.READY)
        pkt.state = PacketState.READY.value
        pkt.attempt_count = (pkt.attempt_count or 0) + 1
        db.flush()
        record_event("packet_transition", "packet", packet_id, {
            "from": current.value, "to": PacketState.READY.value, "reason": reason, "actor": actor,
        })
        db.commit()
    _log.info("packet_retried", packet_id=packet_id, actor=actor)
    return {"ok": True, "packet_id": packet_id, "state": PacketState.READY.value}


def _try_signal_worker(worker_id: str, sig=signal.SIGTERM):
    """Look up PID in Worker.pid then env-var. No pgrep for safety."""
    pid = None
    with get_db() as db:
        from grace_control.db.schema import Worker as W
        w = db.query(W).filter_by(id=worker_id).first()
        if w and w.pid:
            pid = w.pid
    if not pid:
        pid_str = os.environ.get(f"GRACE_WORKER_PID_{worker_id}")
        if pid_str:
            try:
                pid = int(pid_str)
            except (ValueError, TypeError):
                pid = None
    if pid:
        try:
            os.kill(pid, sig)
            _log.info("worker_signalled", worker_id=worker_id, signal=sig, pid=pid)
        except (ProcessLookupError, PermissionError, OSError) as e:
            _log.warn("worker_signal_failed", worker_id=worker_id, pid=pid, error=str(e)[:100])


def cancel_packet(packet_id: str, actor: str | None = None, reason: str = "manual_cancel") -> dict:
    """RUNNING -> CANCELLED, releases lease. Signals worker first, re-checks state."""
    from grace_control.core.state_machine import PacketStateMachine
    from grace_control.core.event_recorder import record_event
    from grace_control.api.ws_broadcast import broadcast_packet_cancel

    sm = PacketStateMachine()
    worker_id = None
    with get_db() as db:
        pkt = db.query(Packet).filter_by(id=packet_id).first()
        if not pkt:
            raise ValueError(f"Packet {packet_id} not found")
        current = PacketStateMachine.normalize_state(pkt.state)
        if current != PacketState.RUNNING:
            raise ValueError(f"Cannot cancel from state {pkt.state}")
        lease = db.query(Lease).filter_by(packet_id=packet_id).first()
        if lease:
            worker_id = lease.worker_id

    if worker_id:
        _try_signal_worker(worker_id, signal.SIGTERM)
        import time
        time.sleep(1)

    with get_db() as db:
        pkt = db.query(Packet).filter_by(id=packet_id).first()
        if not pkt:
            raise ValueError(f"Packet {packet_id} not found")
        current = PacketStateMachine.normalize_state(pkt.state)
        if current != PacketState.RUNNING:
            _log.warn("cancel_skipped_state_changed",
                       packet_id=packet_id, current_state=pkt.state)
            return {"ok": False, "packet_id": packet_id,
                    "state": pkt.state, "reason": "state changed during cancel"}

        sm.transition(PacketState.RUNNING, PacketState.CANCELLED)
        pkt.state = PacketState.CANCELLED.value
        lease = db.query(Lease).filter_by(packet_id=packet_id).first()
        if lease:
            worker = db.query(Worker).filter_by(id=lease.worker_id).first()
            if worker:
                worker.current_packet_id = None
            db.delete(lease)
        record_event("packet_transition", "packet", packet_id, {
            "from": "running", "to": "cancelled", "reason": reason, "actor": actor,
        })
        db.commit()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast_packet_cancel(packet_id, reason))
        else:
            loop.run_until_complete(broadcast_packet_cancel(packet_id, reason))
    except RuntimeError:
        pass

    _log.info("packet_cancelled", packet_id=packet_id, actor=actor)
    return {"ok": True, "packet_id": packet_id, "state": PacketState.CANCELLED.value}


def delete_packet(packet_id: str, confirm: str, actor: str | None = None) -> dict:
    """Deletes packet, all PacketRun, StageRun, Event records."""
    if confirm != packet_id:
        raise ValueError("confirm must match packet_id")
    from grace_control.core.event_recorder import record_event

    with get_db() as db:
        pkt = db.query(Packet).filter_by(id=packet_id).first()
        if not pkt:
            raise ValueError(f"Packet {packet_id} not found")
        db.query(PacketRun).filter_by(packet_id=packet_id).delete()
        db.query(StageRun).filter_by(packet_id=packet_id).delete()
        db.query(Event).filter_by(entity_id=packet_id, entity_type="packet").delete()
        db.query(Lease).filter_by(packet_id=packet_id).delete()
        db.delete(pkt)
        record_event("admin_action", "packet", packet_id, {
            "action": "delete", "actor": actor, "confirmed": True,
        })
        db.commit()
    _log.info("packet_deleted", packet_id=packet_id, actor=actor)
    return {"ok": True, "packet_id": packet_id}


def rerun_stage(packet_id: str, stage_key: str, actor: str | None = None) -> dict:
    """Creates pending StageRun + sets packet to READY for actual dispatch."""
    from grace_control.core.stage_instrumentation import create_for_return
    from grace_control.core.state_machine import PacketStateMachine

    create_for_return(
        packet_id=packet_id,
        from_stage="manual",
        to_stage=stage_key,
        reason=f"manual rerun by {actor or 'operator'}",
        trace_id=None,
    )

    with get_db() as db:
        pkt = db.query(Packet).filter_by(id=packet_id).first()
        if pkt:
            sm = PacketStateMachine()
            current = PacketStateMachine.normalize_state(pkt.state)
            if current in (PacketState.RUNNING, PacketState.READY,
                           PacketState.BLOCKED_RECOVERABLE, PacketState.REJECTED,
                           PacketState.ACCEPTED, PacketState.DRAFT):
                try:
                    sm.transition(current, PacketState.READY)
                    pkt.state = PacketState.READY.value
                    pkt.attempt_count = (pkt.attempt_count or 0) + 1
                    db.commit()
                except Exception:
                    pass

    _log.info("stage_rerun", packet_id=packet_id, stage_key=stage_key, actor=actor)
    return {"ok": True, "packet_id": packet_id, "stage_key": stage_key}


def stop_worker(worker_id: str, actor: str | None = None) -> dict:
    """SIGTERM to worker process, releases leases. SIGKILL after timeout."""
    from grace_control.core.event_recorder import record_event

    stopped_packets = []
    with get_db() as db:
        worker = db.query(Worker).filter_by(id=worker_id).first()
        if not worker:
            raise ValueError(f"Worker {worker_id} not found")

        leases = db.query(Lease).filter_by(worker_id=worker_id).all()
        for lease in leases:
            pkt = db.query(Packet).filter_by(id=lease.packet_id).first()
            if pkt and pkt.state == "running":
                from grace_control.core.state_machine import PacketStateMachine
                PacketStateMachine().transition(PacketState.RUNNING, PacketState.CANCELLED)
                pkt.state = PacketState.CANCELLED.value
            db.delete(lease)
            stopped_packets.append(lease.packet_id)
            record_event("packet_transition", "packet", lease.packet_id, {
                "from": "running", "to": "cancelled",
                "reason": f"worker {worker_id} stopped by {actor or 'operator'}",
            })

        worker.status = "stopped"
        worker.current_packet_id = None
        record_event("admin_action", "worker", worker_id, {
            "action": "stop_worker", "actor": actor,
        })
        db.commit()

    _try_signal_worker(worker_id, signal.SIGTERM)
    import threading, time
    def _force_kill():
        time.sleep(5)
        _try_signal_worker(worker_id, signal.SIGKILL)
    threading.Thread(target=_force_kill, daemon=True).start()

    _log.info("worker_stopped", worker_id=worker_id, actor=actor, stopped_packets=stopped_packets)
    return {"ok": True, "worker_id": worker_id, "stopped_packets": stopped_packets}


async def dev_replay(packet_id: str, stage_key: str | None = None, actor: str | None = None) -> dict:
    """Invokes dev-replay for a stage by trace_id."""
    from grace_control.api.routers.dev_replay import replay_stage
    from grace_control.core.event_recorder import record_event

    with get_db() as db:
        srun = db.query(StageRun).filter_by(
            packet_id=packet_id, stage_key=stage_key
        ).order_by(StageRun.created_at.desc()).first() if stage_key else None
        trace_id = srun.trace_id if srun else None

    record_event("admin_action", "packet", packet_id, {
        "action": "dev_replay", "trace_id": trace_id, "actor": actor,
    })
    result = await replay_stage(packet_id=packet_id, trace_id=trace_id)
    _log.info("dev_replay", packet_id=packet_id, trace_id=trace_id)
    return {"ok": True, "packet_id": packet_id, "result": result}
