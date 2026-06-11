# ############################################################################
# AI_HEADER: queue_service
# ROLE: Deterministic FIFO queue discipline — single active feature, wave/packet ordering.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Implement deterministic feature queue discipline:
#          - Features are processed FIFO by created_at, id.
#          - Only one feature active at a time under GRACE_MAX_CONCURRENCY=1.
#          - Inside a feature, waves are processed by Wave.order.
#          - Inside a wave, packets are processed by Packet.created_at, id.
#          - Failed/rejected/blocked packets set feature to degraded, blocking later features.
# inputs: worker_id, GRACE_MAX_CONCURRENCY env (default "1").
# returns: packet_id for claiming, or None with reason.
# side_effects: Updates Feature.status (queued→active→done/degraded).
# emitted_logs: queue_candidate, queue_activated, queue_degraded, queue_done, queue_noop.
# error_behavior: Never raises — returns (packet_id, reason) tuple.
# END_MODULE_CONTRACT

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Feature, Packet, PacketState, Wave

_log = GraceLogger("queue_service")

DEGRADED_STATES = {
    PacketState.REJECTED.value,
    PacketState.FAILED.value,
    PacketState.BLOCKED.value,
    PacketState.BLOCKED_RECOVERABLE.value,
    PacketState.BLOCKED_FINAL.value,
}
NON_TERMINAL_DONE = {
    PacketState.DRAFT.value,
    PacketState.READY.value,
    PacketState.RUNNING.value,
}
TERMINAL_SUCCESS = {
    PacketState.MERGED.value,
    PacketState.CANCELLED.value,
    PacketState.ACCEPTED.value,
}

# Legacy statuses that mean "queued, not yet started"
LEGACY_QUEUED_STATUSES = frozenset({"NOT_STARTED", "queued"})


def _max_concurrency() -> int:
    return int(os.environ.get("GRACE_MAX_CONCURRENCY", "1"))


def _run_running_packets(db) -> list[Packet]:
    return db.query(Packet).filter(Packet.state == PacketState.RUNNING.value).all()


def _oldest_queued_feature(db) -> Feature | None:
    """Find the oldest feature that is in queued or NOT_STARTED status."""
    return (
        db.query(Feature)
        .filter(Feature.status.in_(["queued", "NOT_STARTED"]))
        .order_by(Feature.created_at.asc(), Feature.id.asc())
        .first()
    )


def _active_feature(db) -> Feature | None:
    """Find the currently active feature."""
    return db.query(Feature).filter(Feature.status == "active").first()


def _run_wave_gate():
    from grace_control.core.wave_gate import check_wave_gates
    try:
        return check_wave_gates()
    except Exception:
        return 0


def claim_next(worker_id: str) -> tuple[str | None, str]:
    """Determine the next claimable packet per FIFO queue discipline.

    Returns (packet_id, reason). When packet_id is None, the worker
    should not retry immediately (no work available). When packet_id is
    set, the caller must still attempt the actual claim via PacketService.
    """
    max_conc = _max_concurrency()

    with get_db() as db:
        # 1. Concurrency guard
        if max_conc == 1:
            running = _run_running_packets(db)
            if running:
                return None, "running_packet_exists"

        # 2. Find active feature, or promote oldest queued to active
        feat = _active_feature(db)
        if feat is None:
            feat = _oldest_queued_feature(db)
            if feat is None:
                _log.debug("queue_noop", reason="no_queued_features")
                return None, "no_queued_features"
            feat.status = "active"
            feat.updated_at = datetime.now(UTC)
            db.commit()
            _log.info("queue_activated", feature_id=feat.id)

        # 3. Run wave gate (promotes DRAFT→READY for completed waves)
        _run_wave_gate()

        # 4. Check for degraded packets in the feature
        degraded = (
            db.query(Packet)
            .filter(
                Packet.feature_id == feat.id,
                Packet.state.in_(DEGRADED_STATES),
            )
            .count()
        )
        if degraded > 0:
            feat.status = "degraded"
            feat.updated_at = datetime.now(UTC)
            db.commit()
            _log.warn("queue_degraded", feature_id=feat.id,
                      degraded_count=degraded)
            return None, "feature_degraded"

        # 5. Find earliest wave with READY packets
        waves = (
            db.query(Wave)
            .filter(Wave.feature_id == feat.id)
            .order_by(Wave.order.asc(), Wave.created_at.asc(), Wave.id.asc())
            .all()
        )

        for wave in waves:
            packet = (
                db.query(Packet)
                .filter(
                    Packet.wave_id == wave.id,
                    Packet.state == PacketState.READY.value,
                )
                .order_by(Packet.created_at.asc(), Packet.id.asc())
                .first()
            )
            if packet:
                return packet.id, "ok"

        # 6. Check if feature is fully done
        remaining = (
            db.query(Packet)
            .filter(Packet.feature_id == feat.id)
            .count()
        )
        done_count = (
            db.query(Packet)
            .filter(
                Packet.feature_id == feat.id,
                Packet.state.in_(TERMINAL_SUCCESS),
            )
            .count()
        )

        if remaining > 0 and done_count == remaining:
            feat.status = "done"
            feat.updated_at = datetime.now(UTC)
            db.commit()
            _log.info("queue_done", feature_id=feat.id)
            return None, "feature_done"

        # 7. Check if remaining packets are all blocked (not simply none)
        # If there are remaining non-terminal, non-READY packets, the feature
        # has non-degraded non-done packets (e.g. DRAFT packets in later waves
        # that wave_gate hasn't promoted). Return no-op, the wave_gate timer
        # will promote them when the current wave completes.
        return None, "waiting_for_wave_completion"

    return None, "no_queued_features"
