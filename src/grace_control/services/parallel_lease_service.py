# ############################################################################
# AI_HEADER: parallel_lease_service — Fenced parallel resource leases
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Persist and lifecycle-manage scope/key reservations independently
#          from the ordinary packet ownership lease.
# inputs: SQLAlchemy Session and packet/worker lease identity plus snapshots.
# returns: ParallelLease rows, expiry timestamps, or lifecycle counts.
# side_effects: Inserts, updates, and deletes rows in parallel_leases.
# emitted_logs: parallel_lease_acquired, parallel_lease_renewed,
#               parallel_lease_released, parallel_lease_expired,
#               parallel_lease_fenced.
# error_behavior: Raises ParallelLeaseConflictError for an active packet lease
#                 and ParallelLeaseFencedError for stale identity operations.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ParallelLeaseConflictError
#   - class: ParallelLeaseFencedError
#   - class: ParallelLeaseService
#     methods:
#       - acquire
#       - renew
#       - assert_current
#       - release
#       - expire
#       - active_leases
#       - release_for_terminal_state
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from operator import attrgetter
from uuid import uuid4

from grace_control.config.settings import settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import Packet, PacketState, ParallelLease
from grace_control.services.parallel_conflict_service import ParallelConflictService

_log = GraceLogger("parallel_lease")

_CONFLICT_ACTIVE_PACKET_STATES = frozenset({
    PacketState.RUNNING.value,
    PacketState.ACCEPTED.value,
})


class ParallelLeaseConflictError(RuntimeError):
    """Raised when a packet already owns a live parallel lease."""


class ParallelLeaseFencedError(RuntimeError):
    """Raised when a stale worker attempts to renew or release a lease."""


# START_BLOCK_PARALLEL_LEASE_SERVICE
class ParallelLeaseService:
    """Manage durable parallel leases without owning packet state."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure lease TTL and the canonical conflict normalizer.
    # inputs: ttl_seconds — optional lease lifetime; conflict_service — optional
    #         shared scope/key policy instance.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None for a positive TTL or configured default.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        ttl_seconds: int | None = None,
        conflict_service: ParallelConflictService | None = None,
    ) -> None:
        configured_ttl = getattr(settings, "parallel_lease_ttl_seconds", None)
        if configured_ttl is None:
            configured_ttl = getattr(settings, "lease_ttl_seconds", 300)
        self._ttl_seconds = max(1, int(ttl_seconds or configured_ttl))
        self._conflicts = conflict_service or ParallelConflictService()

    # START_FUNCTION_CONTRACT
    # name: acquire
    # purpose: Acquire or reclaim one packet's parallel scope/key reservation.
    # inputs: db — active transaction; packet_id, feature_id, wave_id, worker_id,
    #         claimed_attempt — fencing identity; scope, conflict_keys — snapshots;
    #         base_sha — optional target-head snapshot; now — optional clock.
    # returns: Newly flushed ParallelLease ORM row.
    # side_effects: Deletes an expired same-packet lease and inserts a new row.
    # emitted_logs: parallel_lease_acquired.
    # error_behavior: Raises ParallelLeaseConflictError for a live same-packet lease.
    # END_FUNCTION_CONTRACT
    def acquire(
        self,
        db,
        *,
        packet_id: str,
        feature_id: str,
        wave_id: str,
        worker_id: str,
        claimed_attempt: int,
        scope,
        conflict_keys,
        base_sha: str | None = None,
        now: datetime | None = None,
    ) -> ParallelLease:
        current_time = _utc(now or datetime.now(UTC))
        normalized_scope = self._conflicts.normalize_scopes(scope)
        normalized_keys = self._conflicts.normalize_conflict_keys(conflict_keys)
        existing = db.query(ParallelLease).filter_by(packet_id=packet_id).first()
        if existing is not None:
            if _utc(existing.expires_at) > current_time:
                raise ParallelLeaseConflictError(
                    f"Packet {packet_id} already has an active parallel lease"
                )
            db.delete(existing)
            db.flush()

        lease = ParallelLease(
            id=f"pleas_{uuid4().hex}",
            packet_id=packet_id,
            feature_id=feature_id,
            wave_id=wave_id,
            worker_id=worker_id,
            claimed_attempt=claimed_attempt,
            scope_json=normalized_scope,
            conflict_keys_json=normalized_keys,
            base_sha=base_sha,
            acquired_at=current_time,
            expires_at=current_time + timedelta(seconds=self._ttl_seconds),
            heartbeat_at=current_time,
        )
        db.add(lease)
        db.flush()
        _log.info(
            "parallel_lease_acquired",
            packet_id=packet_id,
            worker_id=worker_id,
            lease_id=lease.id,
            claimed_attempt=claimed_attempt,
        )
        return lease

    # START_FUNCTION_CONTRACT
    # name: renew
    # purpose: Extend a live parallel lease using worker/token/attempt fencing.
    # inputs: db — active transaction; packet_id, worker_id, lease_id,
    #         claimed_attempt — exact lease identity; now — optional clock.
    # returns: New UTC expiry timestamp.
    # side_effects: Updates expires_at and heartbeat_at.
    # emitted_logs: parallel_lease_renewed, parallel_lease_fenced.
    # error_behavior: Raises ParallelLeaseFencedError for missing, mismatched,
    #                 or expired identity.
    # END_FUNCTION_CONTRACT
    def renew(
        self,
        db,
        *,
        packet_id: str,
        worker_id: str,
        lease_id: str,
        claimed_attempt: int,
        now: datetime | None = None,
    ) -> datetime:
        current_time = _utc(now or datetime.now(UTC))
        lease = db.query(ParallelLease).filter_by(packet_id=packet_id).first()
        self._assert_fenced(lease, worker_id, lease_id, claimed_attempt, current_time)
        lease.heartbeat_at = current_time
        lease.expires_at = current_time + timedelta(seconds=self._ttl_seconds)
        db.flush()
        _log.info(
            "parallel_lease_renewed",
            packet_id=packet_id,
            worker_id=worker_id,
            lease_id=lease_id,
            claimed_attempt=claimed_attempt,
        )
        return lease.expires_at

    # START_FUNCTION_CONTRACT
    # name: assert_current
    # purpose: Validate parallel lease ownership without extending its TTL.
    # inputs: db — active transaction; packet_id, worker_id, lease_id,
    #         claimed_attempt — exact fencing identity; now — optional clock.
    # returns: None when the identity is current and unexpired.
    # side_effects: None beyond a read-only lease query.
    # emitted_logs: parallel_lease_fenced on rejection.
    # error_behavior: Raises ParallelLeaseFencedError for missing, mismatched,
    #                 or expired identity.
    # END_FUNCTION_CONTRACT
    def assert_current(
        self,
        db,
        *,
        packet_id: str,
        worker_id: str,
        lease_id: str,
        claimed_attempt: int,
        now: datetime | None = None,
    ) -> None:
        current_time = _utc(now or datetime.now(UTC))
        lease = db.query(ParallelLease).filter_by(packet_id=packet_id).first()
        self._assert_fenced(lease, worker_id, lease_id, claimed_attempt, current_time)

    # START_FUNCTION_CONTRACT
    # name: release
    # purpose: Release a parallel lease only when its fencing identity matches.
    # inputs: db — active transaction; packet_id, worker_id, lease_id,
    #         claimed_attempt — exact lease identity; now — optional clock.
    # returns: True after deleting the matching lease.
    # side_effects: Deletes one parallel_leases row.
    # emitted_logs: parallel_lease_released, parallel_lease_fenced.
    # error_behavior: Raises ParallelLeaseFencedError for missing or stale identity.
    # END_FUNCTION_CONTRACT
    def release(
        self,
        db,
        *,
        packet_id: str,
        worker_id: str,
        lease_id: str,
        claimed_attempt: int,
        now: datetime | None = None,
    ) -> bool:
        current_time = _utc(now or datetime.now(UTC))
        lease = db.query(ParallelLease).filter_by(packet_id=packet_id).first()
        self._assert_fenced(lease, worker_id, lease_id, claimed_attempt, current_time)
        db.delete(lease)
        db.flush()
        _log.info(
            "parallel_lease_released",
            packet_id=packet_id,
            worker_id=worker_id,
            lease_id=lease_id,
            claimed_attempt=claimed_attempt,
        )
        return True

    # START_FUNCTION_CONTRACT
    # name: expire
    # purpose: Remove elapsed parallel leases unless their packet state still
    #          protects the reservation through execution or merge.
    # inputs: db — active transaction; now — optional UTC clock.
    # returns: Number of removed leases.
    # side_effects: Deletes expired parallel_leases rows.
    # emitted_logs: parallel_lease_expired.
    # error_behavior: Propagates database errors.
    # END_FUNCTION_CONTRACT
    def expire(self, db, *, now: datetime | None = None) -> int:
        current_time = _utc(now or datetime.now(UTC))
        leases = db.query(ParallelLease).all()
        expired = []
        for lease in leases:
            if _utc(lease.expires_at) > current_time:
                continue
            packet = db.query(Packet).filter_by(id=lease.packet_id).first()
            if packet and attrgetter("state")(packet) in {
                PacketState.RUNNING.value,
                PacketState.ACCEPTED.value,
            }:
                # The ordinary lease scanner must reclaim a stale RUNNING
                # packet first; ACCEPTED retains its resource until merge.
                continue
            expired.append(lease)
        for lease in expired:
            db.delete(lease)
            _log.info(
                "parallel_lease_expired",
                packet_id=lease.packet_id,
                worker_id=lease.worker_id,
                lease_id=lease.id,
                reason="ttl_elapsed",
            )
        if expired:
            db.flush()
        return len(expired)

    # START_FUNCTION_CONTRACT
    # name: active_leases
    # purpose: Return conflict-active parallel leases, including expired rows
    #          whose packet is still RUNNING or ACCEPTED.
    # inputs: db — active transaction; feature_id/wave_id — optional filters;
    #         now — optional UTC clock.
    # returns: Live ParallelLease ORM rows.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates database errors.
    # END_FUNCTION_CONTRACT
    def active_leases(
        self,
        db,
        *,
        feature_id: str | None = None,
        wave_id: str | None = None,
        now: datetime | None = None,
    ) -> list[ParallelLease]:
        current_time = _utc(now or datetime.now(UTC))
        query = db.query(ParallelLease)
        if feature_id is not None:
            query = query.filter(ParallelLease.feature_id == feature_id)
        if wave_id is not None:
            query = query.filter(ParallelLease.wave_id == wave_id)
        leases = query.all()
        expired_packet_ids = {
            lease.packet_id
            for lease in leases
            if _utc(lease.expires_at) <= current_time
        }
        protected_states: dict[str, str] = {}
        if expired_packet_ids:
            protected_states = {
                packet.id: attrgetter("state")(packet)
                for packet in db.query(Packet)
                .filter(Packet.id.in_(expired_packet_ids))
                .all()
            }
        return [
            lease
            for lease in leases
            if _utc(lease.expires_at) > current_time
            or protected_states.get(lease.packet_id) in _CONFLICT_ACTIVE_PACKET_STATES
        ]

    # START_FUNCTION_CONTRACT
    # name: release_for_terminal_state
    # purpose: Release a packet's parallel resource after terminal/recovery state.
    # inputs: db — active transaction; packet_id — packet owner; state — target state.
    # returns: True when a row was removed, otherwise False.
    # side_effects: Deletes one parallel_leases row without worker fencing.
    # emitted_logs: parallel_lease_released.
    # error_behavior: Propagates database errors; ACCEPTED is intentionally a no-op.
    # END_FUNCTION_CONTRACT
    def release_for_terminal_state(self, db, packet_id: str, state: str) -> bool:
        releasable = {
            "merged",
            "rejected",
            "failed",
            "blocked",
            "blocked_recoverable",
            "blocked_final",
            "cancelled",
        }
        if state not in releasable:
            return False
        lease = db.query(ParallelLease).filter_by(packet_id=packet_id).first()
        if lease is None:
            return False
        db.delete(lease)
        db.flush()
        _log.info(
            "parallel_lease_released",
            packet_id=packet_id,
            worker_id=lease.worker_id,
            lease_id=lease.id,
            reason=f"packet_state:{state}",
        )
        return True

    # START_FUNCTION_CONTRACT
    # name: _assert_fenced
    # purpose: Validate worker, token, attempt, and expiry for lease mutation.
    # inputs: lease — row or None; worker_id, lease_id, claimed_attempt — identity;
    #         now — current UTC time.
    # returns: None when identity is current.
    # side_effects: None.
    # emitted_logs: parallel_lease_fenced on rejection.
    # error_behavior: Raises ParallelLeaseFencedError on any mismatch or expiry.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _assert_fenced(
        lease: ParallelLease | None,
        worker_id: str,
        lease_id: str,
        claimed_attempt: int,
        now: datetime,
    ) -> None:
        reason = ""
        if lease is None:
            reason = "parallel lease not found"
        elif lease.worker_id != worker_id:
            reason = "worker_id mismatch"
        elif lease.id != lease_id:
            reason = "lease_id mismatch"
        elif lease.claimed_attempt != claimed_attempt:
            reason = "claimed_attempt mismatch"
        elif _utc(lease.expires_at) <= now:
            reason = "parallel lease expired"
        if reason:
            _log.warn("parallel_lease_fenced", reason=reason)
            raise ParallelLeaseFencedError(reason)


# END_BLOCK_PARALLEL_LEASE_SERVICE


# START_FUNCTION_CONTRACT
# name: _utc
# purpose: Make SQLite-naive datetimes comparable with UTC-aware values.
# inputs: value — datetime from SQLAlchemy or caller.
# returns: UTC-aware datetime.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None for datetime input.
# END_FUNCTION_CONTRACT
def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
