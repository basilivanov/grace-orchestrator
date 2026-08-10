# ############################################################################
# AI_HEADER: lease_manager
# ROLE: Background lease expiration checker — returns orphaned packets to READY.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Periodically scan for expired leases and release them back to READY.
#          W01: All operations are observable (events recorded), no silent
#          failures, no destructive hardcoded cleanup paths.
# inputs: None (reads DB).
# returns: Count of expired leases processed.
# side_effects: DB write (removes lease, resets packet state, clears worker,
#               records events).
# emitted_logs: lease_expired, lease_scanner_error.
# error_behavior: Logs errors with detail, never crashes the loop.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: check_expired_leases
#   - function: lease_expiration_loop
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Event, Lease, Packet, PacketState, Worker

_log = GraceLogger("lease_manager")

# W01: Removed misleading LEASE_TIMEOUT_MINUTES — actual TTL is in
# PacketService.claim() via settings.lease_ttl_seconds (default 300s).
CHECK_INTERVAL_SECONDS = 30


def _record_lease_event(db, event_type: str, lease: Lease, **extra) -> None:
    """Record an event for lease lifecycle observability (W01)."""
    payload = {
        "lease_id": lease.id,
        "packet_id": lease.packet_id,
        "worker_id": lease.worker_id,
        "claimed_attempt": lease.claimed_attempt,
        "acquired_at": lease.acquired_at.isoformat() if lease.acquired_at else None,
        "expired_at": lease.expires_at.isoformat() if lease.expires_at else None,
    }
    payload.update(extra)
    db.add(Event(
        event_type=event_type,
        entity_type="packet",
        entity_id=lease.packet_id,
        payload_json=payload,
        timestamp=datetime.now(UTC),
    ))


#START_BLOCK_CHECKER
def check_expired_leases() -> int:
    count = 0
    with get_db() as db:
        # W01: Use grace period from settings — don't reclaim a lease
        # immediately on expiry, give the worker a short window for
        # in-flight renewal to land.
        from grace_control.config.settings import settings as _settings
        grace_seconds = getattr(_settings, "lease_expiration_grace_seconds", 30)
        cutoff = datetime.now(UTC) - timedelta(seconds=grace_seconds)

        expired = db.query(Lease).filter(
            Lease.expires_at < cutoff
        ).all()

        for lease in expired:
            packet = db.query(Packet).filter_by(id=lease.packet_id).first()
            if packet and PacketState(packet.state) == PacketState.RUNNING:
                packet.state = PacketState.READY.value
                # W01: Observable event instead of silent log
                _record_lease_event(db, "lease_expired_reclaimed", lease,
                    action="packet_returned_to_ready",
                )
                _log.warn("lease_expired_reclaimed",
                    packet_id=packet.id,
                    worker_id=lease.worker_id,
                    claimed_attempt=lease.claimed_attempt,
                    lease_id=lease.id,
                )
            elif packet:
                # Packet not RUNNING but has stale lease — just clean up
                _record_lease_event(db, "lease_expired_cleanup", lease,
                    packet_state=packet.state,
                    action="stale_lease_removed",
                )
                _log.info("lease_expired_cleanup",
                    packet_id=lease.packet_id,
                    packet_state=packet.state,
                    lease_id=lease.id,
                )

            # W01: Removed hardcoded /tmp/grace_worktrees/ destructive cleanup.
            # Worktree cleanup is handled by worktree_cleanup_service and
            # packet_executor, not by the lease scanner. Deleting worktrees
            # here can race against active workers and corrupt state.
            # See EV-W01-RISK-NOTES for remaining limitations.

            worker = db.query(Worker).filter_by(id=lease.worker_id).first()
            if worker:
                worker.current_packet_id = None

            db.delete(lease)
            count += 1

        from grace_control.services.parallel_lease_service import ParallelLeaseService
        count += ParallelLeaseService().expire(db)

    return count

#END_BLOCK_CHECKER

#START_BLOCK_LOOP
async def lease_expiration_loop(interval: int = CHECK_INTERVAL_SECONDS) -> None:
    await asyncio.sleep(interval)  # first check after initial delay
    while True:
        try:
            expired = check_expired_leases()
            if expired > 0:
                _log.info("lease_scanner_processed", expired_count=expired)
        except Exception as e:
            # W01: No more silent except/pass — log the error with detail
            _log.error("lease_scanner_error", error=str(e)[:500])
        await asyncio.sleep(interval)

#END_BLOCK_LOOP
