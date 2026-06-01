# ############################################################################
# AI_HEADER: feature_gate
# ROLE: Check feature completion — all packets MERGED → feature COMPLETED.
# ############################################################################

from __future__ import annotations

from grace_control.db import get_db
from grace_control.db.schema import Feature, Packet, PacketState


def check_feature_completion() -> int:
    completed = 0
    try:
        with get_db() as db:
            features = db.query(Feature).filter(Feature.status != "COMPLETED").all()
            for f in features:
                packets = db.query(Packet).filter_by(feature_id=f.id).all()
                if not packets:
                    continue
                all_done = all(
                    PacketState(p.state) in (PacketState.MERGED, PacketState.CANCELLED)
                    for p in packets
                )
                if all_done:
                    f.status = "COMPLETED"
                    completed += 1
        return completed
    except Exception:
        return 0
