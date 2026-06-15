# ############################################################################
# AI_HEADER: stuck_scanner
# ROLE: W08 — Proactive stuck scanner for expired leases, stale workers,
#       stuck RUNNING packets, orphan leases, and recoverable blocks.
#       Runs as a background task alongside the lease_expiration_loop.
# ############################################################################

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.core.event_recorder import record_event
from grace_control.db import get_db
from grace_control.db.schema import Event, Feature, Lease, Packet, PacketState, Worker

_log = GraceLogger("stuck_scanner")

# ── Configuration ──────────────────────────────────────────────────────────

# How long without heartbeat before a worker is considered stale.
_STALE_WORKER_THRESHOLD_MINUTES = 5

# How old a RUNNING packet must be before we check it for stuckness.
_RUNNING_AGE_THRESHOLD_MINUTES = 10

# Interval between scanner sweeps.
_CHECK_INTERVAL_SECONDS = 60

# Whether LLM-based repair is allowed (must be explicitly enabled).
_LLM_REPAIR_ENABLED_DEFAULT = False


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime.

    The DB schema uses datetime.utcnow() (naive). Comparing aware vs naive
    datetimes raises TypeError in Python 3.12+. This helper ensures
    consistent naive datetime comparisons throughout the scanner.
    """
    return datetime.now(UTC).replace(tzinfo=None)


# ── Scanner entry point ────────────────────────────────────────────────────

def run_stuck_scan() -> dict[str, int]:
    """W08: Execute a single stuck-scanner sweep.

    Checks for and handles:
    1. RUNNING packets with expired leases
    2. Workers with stale heartbeats
    3. Workers with current_packet but no active lease
    4. Leases for packets that are not RUNNING
    5. Features with no progress (all packets stuck)
    6. Recoverable blocked packets (BLOCKED_RECOVERABLE)
    7. PLAN_FAILED with repairable compiler errors

    Returns a summary dict with counts of each action taken.
    """
    counts = {
        "stuck_running_recovered": 0,
        "stale_workers_deactivated": 0,
        "orphan_leases_cleaned": 0,
        "worker_packet_mismatch_cleaned": 0,
        "blocked_recoverable_events": 0,
        "plan_failed_repairable_events": 0,
        "feature_no_progress_events": 0,
    }

    try:
        _scan_stuck_running_with_expired_leases(counts)
    except Exception as e:
        _log.error("scan_stuck_running_error", error=str(e)[:500])

    try:
        _scan_stale_workers(counts)
    except Exception as e:
        _log.error("scan_stale_workers_error", error=str(e)[:500])

    try:
        _scan_worker_packet_mismatches(counts)
    except Exception as e:
        _log.error("scan_worker_packet_mismatch_error", error=str(e)[:500])

    try:
        _scan_orphan_leases(counts)
    except Exception as e:
        _log.error("scan_orphan_leases_error", error=str(e)[:500])

    try:
        _scan_blocked_recoverable(counts)
    except Exception as e:
        _log.error("scan_blocked_recoverable_error", error=str(e)[:500])

    try:
        _scan_plan_failed_repairable(counts)
    except Exception as e:
        _log.error("scan_plan_failed_repairable_error", error=str(e)[:500])

    try:
        _scan_features_no_progress(counts)
    except Exception as e:
        _log.error("scan_features_no_progress_error", error=str(e)[:500])

    total = sum(counts.values())
    if total > 0:
        _log.info("stuck_scan_summary", **counts, total=total)
    return counts


# ── Individual scanners ────────────────────────────────────────────────────

def _scan_stuck_running_with_expired_leases(counts: dict[str, int]) -> None:
    """W08: Detect RUNNING packets whose lease has expired.

    These packets are stuck because the worker lost the lease (or crashed)
    but the packet state was never updated. Recovery: set packet to READY
    so it can be reclaimed.
    """
    with get_db() as db:
        from grace_control.config.settings import settings as _settings
        grace_seconds = getattr(_settings, "lease_expiration_grace_seconds", 30)
        cutoff = _utcnow() - timedelta(seconds=grace_seconds)

        # Find all RUNNING packets
        running_packets = db.query(Packet).filter(
            Packet.state == PacketState.RUNNING.value
        ).all()

        for packet in running_packets:
            lease = db.query(Lease).filter_by(packet_id=packet.id).first()
            if lease is None or lease.expires_at < cutoff:
                # Stale: no lease or expired lease for a RUNNING packet
                packet.state = PacketState.READY.value

                worker_id = lease.worker_id if lease else None
                if lease:
                    # Clear worker reference
                    worker = db.query(Worker).filter_by(id=lease.worker_id).first()
                    if worker:
                        worker.current_packet_id = None
                    db.delete(lease)

                record_event("stuck_running_recovered", "packet", packet.id, {
                    "action": "packet_returned_to_ready",
                    "reason": "running_packet_with_expired_lease",
                    "previous_state": "running",
                    "lease_id": lease.id if lease else None,
                    "worker_id": worker_id,
                })

                _log.warn("stuck_running_recovered",
                    packet_id=packet.id,
                    worker_id=worker_id,
                    lease_id=lease.id if lease else None,
                    action="packet_returned_to_ready")

                counts["stuck_running_recovered"] += 1
        db.flush()


def _scan_stale_workers(counts: dict[str, int]) -> None:
    """W08: Detect workers whose heartbeat is stale.

    A worker with a stale heartbeat is likely dead. Mark it as inactive.
    This is a deterministic safe action — it does not affect the packet state.
    """
    with get_db() as db:
        threshold = _utcnow() - timedelta(minutes=_STALE_WORKER_THRESHOLD_MINUTES)

        stale_workers = db.query(Worker).filter(
            Worker.status == "active",
            Worker.last_heartbeat < threshold,
        ).all()

        for worker in stale_workers:
            worker.status = "inactive"

            record_event("worker_stale_heartbeat_deactivated", "worker", worker.id, {
                "action": "worker_marked_inactive",
                "reason": "stale_heartbeat",
                "last_heartbeat": worker.last_heartbeat.isoformat() if worker.last_heartbeat else None,
                "current_packet_id": worker.current_packet_id,
            })

            _log.warn("worker_stale_heartbeat_deactivated",
                worker_id=worker.id,
                last_heartbeat=str(worker.last_heartbeat),
                current_packet_id=worker.current_packet_id)

            counts["stale_workers_deactivated"] += 1
        db.flush()


def _scan_worker_packet_mismatches(counts: dict[str, int]) -> None:
    """W08: Detect workers with current_packet_id but no active lease.

    This means the worker thinks it's working on a packet, but the lease
    was already cleaned up. Clear the stale reference.
    """
    with get_db() as db:
        active_workers = db.query(Worker).filter(
            Worker.status == "active",
            Worker.current_packet_id.isnot(None),
        ).all()

        for worker in active_workers:
            lease = db.query(Lease).filter_by(
                packet_id=worker.current_packet_id,
                worker_id=worker.id,
            ).first()

            if lease is None:
                # Worker has packet but no lease — clear reference
                packet_id = worker.current_packet_id
                worker.current_packet_id = None

                record_event("worker_packet_mismatch_cleaned", "worker", worker.id, {
                    "action": "cleared_current_packet_id",
                    "reason": "worker_has_packet_but_no_lease",
                    "packet_id": packet_id,
                })

                _log.info("worker_packet_mismatch_cleaned",
                    worker_id=worker.id,
                    packet_id=packet_id)

                counts["worker_packet_mismatch_cleaned"] += 1
        db.flush()


def _scan_orphan_leases(counts: dict[str, int]) -> None:
    """W08: Detect leases for packets that are not RUNNING.

    An orphan lease is one where the packet is in a terminal or different
    state (READY, ACCEPTED, MERGED, FAILED, etc.) but the lease still exists.
    These are safe to clean up.
    """
    with get_db() as db:
        non_running_states = [
            PacketState.READY.value,
            PacketState.ACCEPTED.value,
            PacketState.MERGED.value,
            PacketState.REJECTED.value,
            PacketState.FAILED.value,
            PacketState.BLOCKED_FINAL.value,
            PacketState.BLOCKED_RECOVERABLE.value,
        ]

        # Get all active leases
        all_leases = db.query(Lease).all()

        for lease in all_leases:
            packet = db.query(Packet).filter_by(id=lease.packet_id).first()
            if packet and packet.state in non_running_states:
                # Lease exists but packet is not RUNNING — clean up
                record_event("orphan_lease_cleaned", "packet", packet.id, {
                    "action": "orphan_lease_removed",
                    "reason": "lease_exists_but_packet_not_running",
                    "packet_state": packet.state,
                    "lease_id": lease.id,
                    "worker_id": lease.worker_id,
                })

                _log.info("orphan_lease_cleaned",
                    packet_id=packet.id,
                    packet_state=packet.state,
                    lease_id=lease.id,
                    worker_id=lease.worker_id)

                # Clear worker reference
                worker = db.query(Worker).filter_by(id=lease.worker_id).first()
                if worker:
                    worker.current_packet_id = None

                db.delete(lease)
                counts["orphan_leases_cleaned"] += 1
        db.flush()


def _scan_blocked_recoverable(counts: dict[str, int]) -> None:
    """W08: Emit diagnostics for BLOCKED_RECOVERABLE packets.

    These packets need architect intervention. The scanner does NOT
    auto-apply recovery — it only emits an event so humans can act.
    RecoveryController handles the actual recovery when enabled.
    """
    with get_db() as db:
        blocked = db.query(Packet).filter(
            Packet.state == PacketState.BLOCKED_RECOVERABLE.value,
        ).all()

        for packet in blocked:
            record_event("blocked_recoverable_waiting", "packet", packet.id, {
                "action": "diagnostics_emitted",
                "reason": "blocked_recoverable_needs_architect_intervention",
                "packet_state": packet.state,
                "attempt_count": packet.attempt_count,
                "feature_id": packet.feature_id,
            })

            _log.info("blocked_recoverable_waiting",
                packet_id=packet.id,
                feature_id=packet.feature_id,
                attempt_count=packet.attempt_count)

            counts["blocked_recoverable_events"] += 1


def _scan_plan_failed_repairable(counts: dict[str, int]) -> None:
    """W08: Detect PLAN_FAILED features with repairable compiler errors.

    The plan repair path is fixed (see try_approve_or_repair_plan) but
    some PLAN_FAILED features may have been left in that state before
    the fix. The scanner detects them and emits events.
    It does NOT auto-repair — that requires LLM which is guarded by config.
    """
    with get_db() as db:
        plan_failed_features = db.query(Feature).filter(
            Feature.status == "PLAN_FAILED",
        ).all()

        for feature in plan_failed_features:
            spec = feature.spec_json or {}
            compiler_data = spec.get("_plan_compiler", {})
            errors = compiler_data.get("errors", [])

            if not errors:
                continue

            # Check if any error is repairable
            from grace_control.services.planning_recovery_service import (
                is_repairable_error,
                classify_compiler_result,
            )
            error_class = classify_compiler_result(errors)

            if error_class == "repairable":
                llm_allowed = _is_llm_repair_allowed()

                record_event("plan_failed_repairable_detected", "feature", feature.id, {
                    "action": "diagnostics_emitted",
                    "reason": "plan_failed_with_repairable_compiler_errors",
                    "error_class": error_class,
                    "error_count": len(errors),
                    "llm_repair_allowed": llm_allowed,
                    "error_codes": [e.get("code", "") for e in errors],
                })

                _log.info("plan_failed_repairable_detected",
                    feature_id=feature.id,
                    error_class=error_class,
                    error_count=len(errors),
                    llm_repair_allowed=llm_allowed)

                counts["plan_failed_repairable_events"] += 1


def _scan_features_no_progress(counts: dict[str, int]) -> None:
    """W08: Detect features that have packets but none in a progressing state.

    A feature with all packets in BLOCKED_FINAL, FAILED, or similar
    terminal states and none in READY/RUNNING/ACCEPTED/MERGED is
    effectively stuck and needs human attention.
    """
    with get_db() as db:
        active_features = db.query(Feature).filter(
            Feature.status.in_(["IN_PROGRESS", "PLAN_READY"]),
        ).all()

        progressing_states = {
            PacketState.READY.value,
            PacketState.RUNNING.value,
            PacketState.ACCEPTED.value,
            PacketState.MERGED.value,
            PacketState.DRAFT.value,
        }

        for feature in active_features:
            packets = db.query(Packet).filter_by(feature_id=feature.id).all()
            if not packets:
                continue

            has_progress = any(p.state in progressing_states for p in packets)
            if not has_progress:
                blocked_count = sum(1 for p in packets if p.state == PacketState.BLOCKED_FINAL.value)
                failed_count = sum(1 for p in packets if p.state == PacketState.FAILED.value)

                record_event("feature_no_progress_detected", "feature", feature.id, {
                    "action": "diagnostics_emitted",
                    "reason": "feature_has_packets_but_none_progressing",
                    "total_packets": len(packets),
                    "blocked_count": blocked_count,
                    "failed_count": failed_count,
                    "packet_states": list(set(p.state for p in packets)),
                })

                _log.warn("feature_no_progress_detected",
                    feature_id=feature.id,
                    total_packets=len(packets),
                    blocked_count=blocked_count,
                    failed_count=failed_count)

                counts["feature_no_progress_events"] += 1


# ── LLM repair guard ───────────────────────────────────────────────────────

def _is_llm_repair_allowed() -> bool:
    """W08: Check if LLM-based repair is explicitly allowed.

    LLM repair is disabled by default. It must be enabled via
    GRACE_LLM_REPAIR_ENABLED=true environment variable.
    This prevents unsafe auto-repair by the scanner.
    """
    return os.environ.get("GRACE_LLM_REPAIR_ENABLED", "false").lower() == "true"


# ── Background loop ────────────────────────────────────────────────────────

async def stuck_scan_loop(interval: int = _CHECK_INTERVAL_SECONDS) -> None:
    """W08: Background loop that runs the stuck scanner periodically."""
    await asyncio.sleep(interval)  # initial delay
    while True:
        try:
            counts = run_stuck_scan()
            total = sum(counts.values())
            if total > 0:
                _log.info("stuck_scan_loop_processed", **counts)
        except Exception as e:
            _log.error("stuck_scan_loop_error", error=str(e)[:500])
        await asyncio.sleep(interval)
