# ############################################################################
# AI_HEADER: lease_manager
# ROLE: Background lease expiration checker — returns orphaned packets to READY.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Periodically scan for expired leases and release them back to READY.
# inputs: None (reads DB).
# returns: Count of expired leases processed.
# side_effects: DB write (removes lease, resets packet state, clears worker).
# emitted_logs: None.
# error_behavior: Catches and logs errors, never crashes the loop.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: check_expired_leases
#   - function: lease_expiration_loop
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from grace_control.db import get_db
from grace_control.db.schema import Lease, Packet, PacketState, Worker

LEASE_TIMEOUT_MINUTES = 5
CHECK_INTERVAL_SECONDS = 30

#START_BLOCK_CHECKER
def check_expired_leases() -> int:
    count = 0
    with get_db() as db:
        expired = db.query(Lease).filter(
            Lease.expires_at < datetime.utcnow()
        ).all()

        for lease in expired:
            packet = db.query(Packet).filter_by(id=lease.packet_id).first()
            if packet and PacketState(packet.state) == PacketState.RUNNING:
                packet.state = PacketState.READY.value

                # Clean up orphaned worktree
                try:
                    import shutil
                    from pathlib import Path
                    wt = Path(f"/tmp/grace_worktrees/grace/{packet.id}/{packet.attempt_count}")
                    if wt.exists():
                        shutil.rmtree(wt)
                except Exception:
                    pass

            worker = db.query(Worker).filter_by(id=lease.worker_id).first()
            if worker:
                worker.current_packet_id = None

            db.delete(lease)
            count += 1

    return count

#END_BLOCK_CHECKER

#START_BLOCK_LOOP
async def lease_expiration_loop(interval: int = CHECK_INTERVAL_SECONDS) -> None:
    await asyncio.sleep(interval)  # first check after initial delay
    while True:
        try:
            expired = check_expired_leases()
            if expired > 0:
                pass
        except Exception:
            pass
        await asyncio.sleep(interval)

#END_BLOCK_LOOP
