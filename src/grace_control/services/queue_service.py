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
#          - REJECTED with attempts remaining is retryable — does NOT degrade
#            feature; waits for the retry path (worker or admin).
#          - FAILED is terminal/exhausted ONLY. FAILED → FAILED only via
#            BLOCKED_FINAL or exhausted attempt. No FAILED → READY transition.
#          - Only REJECTED-at-max and BLOCKED_FINAL degrade feature.
# inputs: worker_id, GRACE_MAX_CONCURRENCY env (default "1").
# returns: packet_id for claiming, or None with reason.
# side_effects: Updates Feature.status (queued→active→done/degraded).
# emitted_logs: queue_candidate, queue_activated, queue_degraded, queue_done,
#                queue_noop, queue_retryable_failure_wait,
#                queue_terminal_failure_degraded, queue_blocked_recoverable_wait,
#                queue_waiting_for_retry, queue_ready_claimable.
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

# Legacy broad set kept for read-only diagnostic / wave-gate use.
# Use is_terminal_failure / is_retryable_failure / is_feature_degrading_packet
# in queue logic to avoid premature feature degradation.
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


# ── Packet failure classification (TZ §6.1) ──────────────────────────────────

def is_retryable_failure(p: Packet) -> bool:
    """True if packet is in REJECTED state with attempts remaining.

    Retryable failures must NOT trigger feature degradation — they wait
    for the worker retry path or admin retry endpoint.

    NOTE: FAILED is NEVER retryable. FAILED is terminal-only (see state
    machine: FAILED -> CANCELLED is the only transition out). Runtime
    errors with attempts remaining must release as REJECTED, not FAILED.
    """
    if p.state != PacketState.REJECTED.value:
        return False
    return (p.attempt_count or 0) < (p.max_attempts or 0)


def is_terminal_failure(p: Packet) -> bool:
    """True if packet is in REJECTED-exhausted or FAILED state.

    Terminal failures DO trigger feature degradation. FAILED is always
    terminal. REJECTED becomes terminal only when attempt_count >= max_attempts.
    """
    if p.state == PacketState.FAILED.value:
        return True
    if p.state == PacketState.REJECTED.value:
        return (p.attempt_count or 0) >= (p.max_attempts or 0)
    return False


def is_feature_degrading_packet(p: Packet) -> bool:
    """True if packet failure should set feature to degraded.

    Conservative rule: only terminal failures and BLOCKED_FINAL degrade.
    BLOCKED_RECOVERABLE / BLOCKED keep feature alive to allow recovery.
    """
    if p.state == PacketState.BLOCKED_FINAL.value:
        return True
    return is_terminal_failure(p)


def _attempts_remaining(p: Packet) -> int:
    return max(0, (p.max_attempts or 0) - (p.attempt_count or 0))


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

        # 5. Find earliest claimable wave with READY packets.
        #    Waves must be processed in order: later waves are not claimable
        #    until all packets in earlier waves are MERGED, CANCELLED, or in
        #    a state waiting for retry/recovery.
        waves = (
            db.query(Wave)
            .filter(Wave.feature_id == feat.id)
            .order_by(Wave.order.asc(), Wave.created_at.asc(), Wave.id.asc())
            .all()
        )

        claimable_packet = None
        wave_complete = True  # tracks whether all preceding waves are done

        for wave in waves:
            wave_packets = (
                db.query(Packet)
                .filter(Packet.wave_id == wave.id)
                .all()
            )

            if not wave_packets:
                continue

            # Classify packets
            ready = [p for p in wave_packets if p.state == PacketState.READY.value]
            retryable = [p for p in wave_packets if is_retryable_failure(p)]
            degrading = [p for p in wave_packets if is_feature_degrading_packet(p)]
            all_done = all(p.state in TERMINAL_SUCCESS for p in wave_packets)

            # 5a. Degrading packets: feature must become degraded.
            if degrading:
                feat.status = "degraded"
                feat.updated_at = datetime.now(UTC)
                db.commit()
                _log.warn(
                    "queue_terminal_failure_degraded",
                    feature_id=feat.id,
                    wave_id=wave.id,
                    packet_ids=[p.id for p in degrading],
                    reason="terminal_exhausted_or_blocked_final",
                )
                return None, "feature_degraded"

            # 5b. Retryable failures: feature stays active, no claim of later
            # wave packets, but do NOT claim this packet again (worker has
            # already released it as rejected; waiting for retry path).
            if retryable and not ready:
                _log.info(
                    "queue_retryable_failure_wait",
                    feature_id=feat.id,
                    wave_id=wave.id,
                    packet_ids=[p.id for p in retryable],
                    attempts_used=[p.attempt_count for p in retryable],
                    max_attempts=[p.max_attempts for p in retryable],
                )
                return None, "waiting_for_retry"

            # 5c. Non-wave-complete: do not skip ahead.
            if not wave_complete and ready:
                return None, "waiting_for_wave_completion"

            # 5d. Wave has READY packet and is claimable.
            if ready:
                wave_complete = False
                ready.sort(key=lambda p: (p.created_at, p.id))
                claimable_packet = ready[0]
                _log.info(
                    "queue_ready_claimable",
                    feature_id=feat.id,
                    wave_id=wave.id,
                    packet_id=claimable_packet.id,
                )
                break

            # 5e. No READY, no retryable, no degrading — wave has blocked_recoverable
            # or similar. Wait for recovery controller.
            if not all_done and not retryable and not degrading:
                # If every remaining packet is BLOCKED_RECOVERABLE / BLOCKED
                # we still don't degrade — wait for recovery.
                if any(
                    p.state in (
                        PacketState.BLOCKED.value,
                        PacketState.BLOCKED_RECOVERABLE.value,
                    )
                    for p in wave_packets
                ):
                    _log.info(
                        "queue_blocked_recoverable_wait",
                        feature_id=feat.id,
                        wave_id=wave.id,
                    )
                    return None, "waiting_for_recovery"

            # 5f. Wave not fully done but no actionable state.
            if not all_done:
                return None, "waiting_for_wave_completion"
            # else all_done: wave is complete, proceed to next wave

        if claimable_packet:
            return claimable_packet.id, "ok"

        # All waves processed — check if feature is fully done
        all_feature_packets = (
            db.query(Packet).filter(Packet.feature_id == feat.id).all()
        )
        remaining = len(all_feature_packets)
        if remaining == 0:
            return None, "no_packets"

        # Retryable / blocked still pending: keep feature active.
        if any(is_retryable_failure(p) for p in all_feature_packets):
            return None, "waiting_for_retry"
        if any(
            p.state in (PacketState.BLOCKED.value, PacketState.BLOCKED_RECOVERABLE.value)
            for p in all_feature_packets
        ):
            return None, "waiting_for_recovery"

        done_count = sum(1 for p in all_feature_packets if p.state in TERMINAL_SUCCESS)
        non_terminal = sum(
            1 for p in all_feature_packets
            if p.state in (PacketState.DRAFT.value, PacketState.READY.value, PacketState.RUNNING.value)
        )

        if non_terminal > 0:
            # wave_gate should promote DRAFT→READY; wait for it.
            return None, "waiting_for_wave_completion"

        if done_count == remaining:
            feat.status = "done"
            feat.updated_at = datetime.now(UTC)
            db.commit()
            _log.info("queue_done", feature_id=feat.id)
            return None, "feature_done"

        return None, "waiting_for_wave_completion"

    return None, "no_queued_features"
