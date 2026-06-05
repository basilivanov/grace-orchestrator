# ############################################################################
# AI_HEADER: wave_gate
# ROLE: Wave gate — transitions DRAFT→READY when previous wave is complete.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Check wave completion and gate subsequent waves into READY.
# inputs: None (reads DB).
# returns: Count of packets gated to READY.
# side_effects: DB write (packet state transitions).
# emitted_logs: wave_gate_check_start, wave_gate_opened, wave_gate_degraded, wave_gate_failed.
# error_behavior: Logs errors and re-raises (no silent swallow).
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: check_wave_gates
# END_MODULE_MAP

from __future__ import annotations

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Feature, Packet, PacketState, Wave

_log = GraceLogger("wave_gate")


def check_wave_gates() -> int:
    _log.debug("wave_gate_check_start")
    gated = 0
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

                done_states = {PacketState.MERGED, PacketState.CANCELLED, PacketState.BLOCKED_FINAL}
                degraded_states = {
                    PacketState.FAILED,
                    PacketState.REJECTED,
                    PacketState.BLOCKED,
                    PacketState.BLOCKED_RECOVERABLE,
                }
                all_done = all(
                    PacketState(p.state) in done_states for p in current_packets
                )
                has_degraded = any(
                    PacketState(p.state) in degraded_states for p in current_packets
                )

                if has_degraded and not all_done:
                    feature = db.query(Feature).filter_by(id=fid).first()
                    if feature is not None:
                        reason = (
                            f"wave {current_wave.id} has degraded packets "
                            f"({sum(1 for p in current_packets if PacketState(p.state) in degraded_states)} failed/blocked/rejected)"
                        )
                        feature.degraded_reason = reason
                        _log.warn("wave_gate_degraded", feature_id=fid,
                            wave_id=current_wave.id, reason=reason)
                    current_wave.status = "DEGRADED"

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
                # Note: PacketState transitions (DRAFT→READY) for gating stay inline
                # because they are gated by wave completion, not by PacketService claim.
                # The PacketService.transition() is used for claim/release paths only.

    return gated
