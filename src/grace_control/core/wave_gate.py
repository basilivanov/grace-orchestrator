# ############################################################################
# AI_HEADER: wave_gate
# ROLE: Wave gate — transitions DRAFT→READY when previous wave is complete.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Check wave completion and gate subsequent waves into READY.
# inputs: None (reads DB).
# returns: Count of packets gated to READY.
# side_effects: DB write (packet state transitions).
# emitted_logs: None.
# error_behavior: Catches errors silently.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: check_wave_gates
# END_MODULE_MAP

from __future__ import annotations

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketState, Wave

_log = GraceLogger("wave_gate")


def check_wave_gates() -> int:
    gated = 0
    try:
        _log.debug("wave_gate_check_start")
        with get_db() as db:
            features = db.execute(
                db.query(Wave.feature_id).distinct()
            ).fetchall()
            feature_ids = [r[0] for r in features]

            for fid in feature_ids:
                waves = db.query(Wave).filter_by(feature_id=fid).order_by(Wave.order).all()
                for i in range(len(waves) - 1):
                    current_wave = waves[i]
                    next_wave = waves[i + 1]

                    current_packets = db.query(Packet).filter_by(
                        feature_id=fid, wave_id=current_wave.id
                    ).all()

                    if not current_packets:
                        continue

                    terminal_states = {PacketState.MERGED, PacketState.FAILED, PacketState.CANCELLED, PacketState.REJECTED, PacketState.BLOCKED}
                    all_done = all(
                        PacketState(p.state) in terminal_states
                        for p in current_packets
                    )

                    if all_done:
                        current_wave.status = "COMPLETED"
                        drafts = db.query(Packet).filter_by(
                            feature_id=fid, wave_id=next_wave.id,
                            state=PacketState.DRAFT.value,
                        ).all()
                        for p in drafts:
                            p.state = PacketState.READY.value
                            gated += 1
                        if gated > 0:
                            _log.info("wave_gate_opened", feature_id=fid,
                                from_wave=current_wave.id, to_wave=next_wave.id,
                                packets_gated=gated)
                        next_wave.status = "IN_PROGRESS"

        return gated
    except Exception:
        return 0
