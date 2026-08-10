# ############################################################################
# AI_HEADER: packet_service
# ROLE: Sole owner of packet state transitions, claim/release, retry, block.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Centralize all packet state mutations. No other module in grace_control
#          should write to packet.state directly. All transitions go through
#          PacketService which validates via PacketStateMachine, records Event,
#          and broadcasts via WebSocket.
# inputs: DB sessions, packet_id, target state, optional reason.
# returns: Updated Packet, Lease, or None.
# side_effects: Writes to packets/leases/events tables, broadcasts WebSocket events.
# emitted_logs: packet_transition, packet_claimed, packet_released, packet_blocked.
# error_behavior: Raises PacketNotFoundError or StateTransitionError.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketNotFoundError
#   - class: MaxRetriesReachedError
#   - class: PacketService
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from grace_control.core.stage_instrumentation import stage

from grace_control.core.state_machine import PacketStateMachine, StateTransitionError
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Event, Lease, Packet, PacketRun, PacketState, ParallelLease, Worker

_log = GraceLogger("packet_service")


class PacketNotFoundError(Exception):
    """Raised when packet_id does not exist in DB."""


class MaxRetriesReachedError(StateTransitionError):
    """Raised when a packet has reached its max_attempts and cannot retry."""


class StaleLeaseError(Exception):
    """W01: Raised when a release uses a stale or mismatched lease.

    This means the worker's lease has expired and been reclaimed by another
    worker, or the worker_id / lease_id / claimed_attempt don't match.
    The release must be rejected and the worker must abandon the result.
    """


@dataclass(frozen=True)
class ClaimResult:
    """Session-safe DTO returned by PacketService.claim().

    ORM `Lease` cannot survive session close under the default
    `expire_on_commit=True`; using a frozen dataclass here means callers
    (e.g. packets router) can serialize fields without triggering
    `DetachedInstanceError`.

    W01: Added claimed_attempt for lease fencing. The worker must echo
    this back on release to prove it still owns the current lease.
    """
    packet_id: str
    lease_id: int
    worker_id: str
    expires_at: datetime
    spec: dict[str, Any]
    attempt: int
    claimed_attempt: int = 0  # W01: fencing token — attempt count at claim time
    # Full packet fields so executor doesn't re-query DB (avoids WAL visibility races)
    feature_id: str = ""
    wave_id: str = ""
    slug: str = ""
    title: str = ""
    description: str = ""
    acceptance_profile: str = ""
    max_attempts: int = 0
    parallel_lease_id: str | None = None
    parallel_expires_at: datetime | None = None


@dataclass(frozen=True)
class CancelResult:
    """Session-safe DTO returned by PacketService.cancel().

    Same reasoning as ClaimResult: callers (router, tests) may read fields
    after the underlying session is closed.
    """
    packet_id: str
    state: str
    reason: str
    previous_state: str


def _record_event(db, event_type: str, entity_id: str, payload: dict) -> None:
    """Insert into Event table (sync, caller passes session)."""
    db.add(Event(
        event_type=event_type,
        entity_type="packet",
        entity_id=entity_id,
        payload_json=payload,
        timestamp=datetime.now(UTC),
    ))


async def _broadcast_state_change(packet_id: str, state: str, reason: str) -> None:
    """Best-effort WebSocket broadcast. Failures are logged but never raise."""
    try:
        from grace_control.api.ws_broadcast import broadcast_event
        await broadcast_event("state_change", {
            "packet_id": packet_id,
            "state": state,
            "reason": reason,
        })
    except Exception as e:
        _log.warn("ws_broadcast_failed", packet_id=packet_id, error=str(e)[:200])


class PacketService:
    """Sole owner of packet state transitions.

    Usage:
        svc = PacketService()
        await svc.transition("pkt_xxx", PacketState.RUNNING, reason="claim")
        await svc.claim("pkt_xxx", "worker-1")
        await svc.release("pkt_xxx", "accepted", {"result": "ok"})
        await svc.retry("pkt_xxx")  # raises MaxRetriesReachedError if max_attempts
        await svc.mark_failed("pkt_xxx", "agent timeout")
        await svc.block("pkt_xxx", recoverable=True, reason="scope_blocked")
    """

    def __init__(self, db_factory=None, broadcaster=None):
        self._db_factory = db_factory or get_db
        self._sm = PacketStateMachine()
        self._broadcast = broadcaster or _broadcast_state_change

    async def transition(
        self,
        packet_id: str,
        to_state: PacketState,
        *,
        reason: str = "",
        db=None,
    ) -> Packet:
        """Apply a state transition with full validation and observability.

        If db session is provided, uses it directly. Otherwise opens new session.
        """
        if db is not None:
            return await self._transition_in_session(db, packet_id, to_state, reason)
        with self._db_factory() as session:
            result = await self._transition_in_session(session, packet_id, to_state, reason)
            session.commit()
            return result

    async def _transition_in_session(self, db, packet_id: str, to_state: PacketState, reason: str) -> Packet:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise PacketNotFoundError(packet_id)
        from_state = PacketStateMachine.normalize_state(packet.state)
        self._sm.transition(from_state, to_state)
        packet.state = PacketStateMachine.write_normalize(to_state)
        _record_event(db, "packet_transition", packet_id, {
            "from": from_state.value,
            "to": to_state.value,
            "reason": reason,
        })
        _log.info("packet_transition", packet_id=packet_id,
            from_state=from_state.value, to_state=to_state.value, reason=reason)
        asyncio.create_task(self._broadcast(packet_id, to_state.value, reason))
        from grace_control.services.parallel_lease_service import ParallelLeaseService
        ParallelLeaseService().release_for_terminal_state(db, packet_id, to_state.value)
        if to_state == PacketState.MERGED:
            self._supersede_rework_ancestors(db, packet)
        return packet

    def _supersede_rework_ancestors(self, db, merged_packet: Packet) -> None:
        """Cancel failed/rejected ancestors replaced by a merged rework leaf."""
        from grace_control.services.rework_packet_service import is_rework_spec

        spec = merged_packet.spec_json if isinstance(merged_packet.spec_json, dict) else {}
        parent_id = spec.get("parent_packet_id", "") if is_rework_spec(spec) else ""
        seen: set[str] = set()
        while isinstance(parent_id, str) and parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = db.query(Packet).filter_by(id=parent_id).first()
            if parent is None:
                _log.warn(
                    "rework_parent_not_found",
                    packet_id=merged_packet.id,
                    parent_packet_id=parent_id,
                )
                return
            parent_spec = parent.spec_json if isinstance(parent.spec_json, dict) else {}
            next_parent_id = parent_spec.get("parent_packet_id", "")
            current = PacketStateMachine.normalize_state(parent.state)
            if self._sm.can_transition(current, PacketState.CANCELLED):
                parent.state = PacketState.CANCELLED.value
                supersede_reason = f"superseded_by_rework:{merged_packet.id}"
                _record_event(db, "packet_transition", parent.id, {
                    "from": current.value,
                    "to": PacketState.CANCELLED.value,
                    "reason": supersede_reason,
                })
                _log.info(
                    "rework_parent_superseded",
                    packet_id=parent.id,
                    merged_rework_packet_id=merged_packet.id,
                )
                asyncio.create_task(
                    self._broadcast(parent.id, PacketState.CANCELLED.value, supersede_reason)
                )
            elif current not in (PacketState.CANCELLED, PacketState.MERGED):
                _log.warn(
                    "rework_parent_not_superseded",
                    packet_id=parent.id,
                    state=current.value,
                    merged_rework_packet_id=merged_packet.id,
                )
            parent_id = next_parent_id

    @stage("executor")
    async def claim(self, packet_id: str, worker_id: str) -> ClaimResult:
        """Claim a packet: DRAFT/REJECTED/BLOCKED_RECOVERABLE→READY→RUNNING, creates lease.

        Returns a `ClaimResult` DTO (frozen dataclass) — never the live ORM
        `Lease` — so callers can serialize fields after the session closes
        without `DetachedInstanceError` (P0#3 from post-refactor audit).
        """
        with self._db_factory() as db:
            result = self._claim_in_session(db, packet_id, worker_id)
            db.commit()
            asyncio.create_task(self._broadcast(packet_id, "running", f"claim:{worker_id}"))
            return result

    # START_FUNCTION_CONTRACT
    # name: _claim_in_session
    # purpose: Claim a packet and create its ordinary ownership lease without
    #         committing, so SafeQueueClaimService can add a parallel lease in
    #         the same short transaction.
    # inputs: db — caller-owned transaction; packet_id, worker_id — claim identity.
    # returns: Session-safe ClaimResult DTO.
    # side_effects: Mutates packet/worker/lease/event rows and flushes changes.
    # emitted_logs: packet_claimed, rework_spec_hydrated.
    # error_behavior: Raises PacketNotFoundError or StateTransitionError.
    # END_FUNCTION_CONTRACT
    def _claim_in_session(self, db, packet_id: str, worker_id: str) -> ClaimResult:
        packet = db.query(Packet).filter_by(id=packet_id).with_for_update().first()
        if not packet:
            raise PacketNotFoundError(packet_id)
        current = PacketStateMachine.normalize_state(packet.state)
        if current != PacketState.READY:
            if current in (PacketState.DRAFT, PacketState.REJECTED, PacketState.BLOCKED_RECOVERABLE):
                self._sm.transition(current, PacketState.READY)
                packet.state = PacketState.READY.value
            else:
                raise StateTransitionError(f"Cannot claim from state {current.value}")
        self._sm.transition(PacketState.READY, PacketState.RUNNING)
        packet.state = PacketState.RUNNING.value
        packet.attempt_count = (packet.attempt_count or 0) + 1

        existing = db.query(Lease).filter_by(packet_id=packet_id).first()
        if existing:
            existing_expiry = existing.expires_at
            if existing_expiry.tzinfo is None:
                existing_expiry = existing_expiry.replace(tzinfo=UTC)
            if existing_expiry > datetime.now(UTC):
                raise StateTransitionError(f"Packet {packet_id} already leased to {existing.worker_id}")
            _record_event(db, "lease_expired_before_reclaim", packet_id, {
                "old_worker_id": existing.worker_id,
                "old_lease_id": existing.id,
                "old_claimed_attempt": existing.claimed_attempt,
                "new_worker_id": worker_id,
            })
            db.delete(existing)

        from grace_control.config.settings import settings as _settings
        lease_ttl_seconds = getattr(_settings, "lease_ttl_seconds", 300)
        expires_at = datetime.now(UTC) + timedelta(seconds=lease_ttl_seconds)
        claimed_attempt = packet.attempt_count
        lease = Lease(
            packet_id=packet_id,
            worker_id=worker_id,
            claimed_attempt=claimed_attempt,
            expires_at=expires_at,
        )
        db.add(lease)
        worker = db.query(Worker).filter_by(id=worker_id).first()
        if worker:
            worker.current_packet_id = packet_id

        from grace_control.services.rework_packet_service import resolve_rework_spec
        resolved_spec = resolve_rework_spec(db, packet)
        if resolved_spec != (packet.spec_json or {}):
            packet.spec_json = resolved_spec
            _log.info("rework_spec_hydrated", packet_id=packet_id)

        _record_event(db, "packet_claimed", packet_id, {
            "worker_id": worker_id,
            "attempt": packet.attempt_count,
            "claimed_attempt": claimed_attempt,
        })
        db.flush()
        result = ClaimResult(
            packet_id=packet_id,
            lease_id=lease.id,
            worker_id=worker_id,
            expires_at=expires_at,
            spec=dict(resolved_spec),
            attempt=packet.attempt_count,
            claimed_attempt=claimed_attempt,
            feature_id=packet.feature_id or "",
            wave_id=packet.wave_id or "",
            slug=packet.slug or "",
            title=packet.title or "",
            description=packet.description or "",
            acceptance_profile=packet.acceptance_profile or "",
            max_attempts=packet.max_attempts or 0,
        )
        _log.info(
            "packet_claimed",
            packet_id=packet_id,
            worker_id=worker_id,
            attempt=packet.attempt_count,
        )
        return result

    async def release(
        self,
        packet_id: str,
        status: str,
        result: dict[str, Any],
        *,
        worker_id: str = "",
        lease_id: int | None = None,
        claimed_attempt: int | None = None,
    ) -> None:
        """Release a packet from RUNNING to terminal/next state based on status.

        W01: Lease fencing — release must prove ownership via worker_id,
        lease_id, and claimed_attempt. If any check fails, StaleLeaseError
        is raised and the packet state is NOT mutated.
        """
        status_to_state = {
            "accepted": PacketState.ACCEPTED,
            "rejected": PacketState.REJECTED,
            "blocked": PacketState.BLOCKED_FINAL,
            "blocked_recoverable": PacketState.BLOCKED_RECOVERABLE,
            "failed": PacketState.FAILED,
        }
        target = status_to_state.get(status)
        if not target:
            raise ValueError(f"Unknown release status: {status}")
        with self._db_factory() as db:
            # W01: Lease fencing — verify the caller owns the current lease.
            # FAIL-CLOSED: if a lease exists, ALL three fencing tokens are
            # required. Missing any token is treated as a stale lease attempt.
            lease = db.query(Lease).filter_by(packet_id=packet_id).first()
            if lease is not None:
                # W01: Fail-closed — missing tokens are rejected, not skipped
                if not worker_id:
                    _record_event(db, "packet_release_rejected_missing_token", packet_id, {
                        "reason": "worker_id is required when lease exists",
                        "lease_id": lease_id,
                        "claimed_attempt": claimed_attempt,
                    })
                    db.commit()
                    raise StaleLeaseError(
                        "worker_id is required for release of leased packet"
                    )
                if lease_id is None:
                    _record_event(db, "packet_release_rejected_missing_token", packet_id, {
                        "reason": "lease_id is required when lease exists",
                        "worker_id": worker_id,
                        "claimed_attempt": claimed_attempt,
                    })
                    db.commit()
                    raise StaleLeaseError(
                        "lease_id is required for release of leased packet"
                    )
                if claimed_attempt is None:
                    _record_event(db, "packet_release_rejected_missing_token", packet_id, {
                        "reason": "claimed_attempt is required when lease exists",
                        "worker_id": worker_id,
                        "lease_id": lease_id,
                    })
                    db.commit()
                    raise StaleLeaseError(
                        "claimed_attempt is required for release of leased packet"
                    )

                # All three tokens present — now verify they match
                if lease.worker_id != worker_id:
                    fencing_reason = f"worker_id mismatch: lease={lease.worker_id}, release={worker_id}"
                elif lease.id != lease_id:
                    fencing_reason = f"lease_id mismatch: lease={lease.id}, release={lease_id}"
                elif lease.claimed_attempt != claimed_attempt:
                    fencing_reason = (
                        f"claimed_attempt mismatch: lease={lease.claimed_attempt}, "
                        f"release={claimed_attempt}"
                    )
                else:
                    fencing_reason = ""

                if fencing_reason:
                    _record_event(db, "packet_release_rejected_stale_lease", packet_id, {
                        "worker_id": worker_id,
                        "lease_id": lease_id,
                        "claimed_attempt": claimed_attempt,
                        "actual_worker_id": lease.worker_id,
                        "actual_lease_id": lease.id,
                        "actual_claimed_attempt": lease.claimed_attempt,
                        "reason": fencing_reason,
                    })
                    _log.warn("packet_release_rejected_stale_lease",
                        packet_id=packet_id, reason=fencing_reason)
                    # W01: commit the event before raising, so it's observable
                    db.commit()
                    raise StaleLeaseError(fencing_reason)

            # Verify packet is in RUNNING state
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if packet and PacketStateMachine.normalize_state(packet.state) != PacketState.RUNNING:
                _record_event(db, "packet_release_rejected_not_running", packet_id, {
                    "worker_id": worker_id,
                    "current_state": packet.state,
                    "status": status,
                })
                raise StaleLeaseError(
                    f"Packet {packet_id} is not RUNNING (state={packet.state})"
                )

            latest_run = (
                db.query(PacketRun)
                .filter_by(packet_id=packet_id)
                .order_by(PacketRun.run_number.desc())
                .first()
            )
            if latest_run and latest_run.status == "running":
                latest_run.status = status
                latest_run.finished_at = datetime.now(UTC)
                if latest_run.started_at:
                    started_at = latest_run.started_at
                    if started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=UTC)
                    latest_run.duration_ms = int(
                        (latest_run.finished_at - started_at).total_seconds() * 1000
                    )
                persisted_result = dict(latest_run.result_json or {})
                persisted_result.update(result)
                latest_run.result_json = persisted_result

            await self._transition_in_session(db, packet_id, target, reason=f"release:{status}")
            if lease:
                db.delete(lease)
            db.commit()

    async def retry(self, packet_id: str) -> Packet:
        """REJECTED/BLOCKED_RECOVERABLE → READY for retry. Raises if max_attempts reached."""
        packet = None
        for attempt in range(5):
            with self._db_factory() as db:
                packet = db.query(Packet).filter_by(id=packet_id).with_for_update().first()
                if packet: break
            if packet: break
            import time
            time.sleep(0.1 * (attempt + 1))
        if not packet:
            raise PacketNotFoundError(packet_id)
        with self._db_factory() as db:
            packet = db.merge(packet)  # re-attach to fresh session
            current = PacketStateMachine.normalize_state(packet.state)
            if current not in (PacketState.REJECTED, PacketState.BLOCKED_RECOVERABLE):
                raise StateTransitionError(
                    f"Cannot retry from state {current.value}"
                )
            if packet.max_attempts and packet.attempt_count >= packet.max_attempts:
                await self._transition_in_session(
                    db, packet_id, PacketState.FAILED,
                    reason=f"max_attempts:{packet.max_attempts}"
                )
                db.commit()
                raise MaxRetriesReachedError(
                    f"Max attempts ({packet.max_attempts}) reached for {packet_id}"
                )
            await self._transition_in_session(db, packet_id, PacketState.READY, reason="retry")
            db.commit()
            return packet

    async def mark_failed(self, packet_id: str, reason: str) -> Packet:
        """Mark packet as FAILED (terminal)."""
        return await self.transition(packet_id, PacketState.FAILED, reason=reason)

    async def block(
        self,
        packet_id: str,
        *,
        recoverable: bool,
        reason: str,
    ) -> Packet:
        """Move packet to BLOCKED_RECOVERABLE (retryable) or BLOCKED_FINAL (terminal)."""
        target = PacketState.BLOCKED_RECOVERABLE if recoverable else PacketState.BLOCKED_FINAL
        return await self.transition(packet_id, target, reason=reason)

    async def renew_lease(
        self,
        packet_id: str,
        worker_id: str,
        lease_id: int,
    ) -> datetime:
        """W01: Renew an active lease — extends expires_at by lease_ttl_seconds.

        Only the matching worker_id + lease_id can renew. Renewal fails if:
        - packet is not RUNNING
        - lease is missing or stale (different worker/lease)
        - lease already expired

        Returns the new expires_at datetime on success.
        Raises StaleLeaseError on fencing failure.
        """
        from grace_control.config.settings import settings as _settings
        lease_ttl_seconds = getattr(_settings, "lease_ttl_seconds", 300)

        with self._db_factory() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                raise PacketNotFoundError(packet_id)

            if PacketStateMachine.normalize_state(packet.state) != PacketState.RUNNING:
                raise StaleLeaseError(
                    f"Cannot renew lease for packet {packet_id} in state {packet.state}"
                )

            lease = db.query(Lease).filter_by(packet_id=packet_id).first()
            if lease is None:
                raise StaleLeaseError(f"No lease found for packet {packet_id}")

            if lease.worker_id != worker_id:
                _record_event(db, "lease_renewal_rejected_worker_mismatch", packet_id, {
                    "requesting_worker_id": worker_id,
                    "lease_worker_id": lease.worker_id,
                })
                raise StaleLeaseError(
                    f"Worker mismatch: lease={lease.worker_id}, request={worker_id}"
                )

            if lease.id != lease_id:
                _record_event(db, "lease_renewal_rejected_lease_mismatch", packet_id, {
                    "request_lease_id": lease_id,
                    "actual_lease_id": lease.id,
                })
                raise StaleLeaseError(
                    f"Lease ID mismatch: lease={lease.id}, request={lease_id}"
                )

            # W01: handle offset-naive datetimes from SQLite
            lease_expiry = lease.expires_at
            if lease_expiry.tzinfo is None:
                lease_expiry = lease_expiry.replace(tzinfo=UTC)
            now_utc = datetime.now(UTC)

            if lease_expiry < now_utc:
                _record_event(db, "lease_renewal_rejected_expired", packet_id, {
                    "worker_id": worker_id,
                    "lease_id": lease_id,
                    "expired_at": lease.expires_at.isoformat(),
                })
                raise StaleLeaseError(
                    f"Lease already expired at {lease_expiry.isoformat()}"
                )

            new_expires = datetime.now(UTC) + timedelta(seconds=lease_ttl_seconds)
            lease.expires_at = new_expires
            lease.heartbeat_at = datetime.now(UTC)

            from grace_control.services.parallel_lease_service import ParallelLeaseService
            parallel_lease = db.query(ParallelLease).filter_by(packet_id=packet_id).first()
            if parallel_lease is not None:
                ParallelLeaseService().renew(
                    db,
                    packet_id=packet_id,
                    worker_id=worker_id,
                    lease_id=parallel_lease.id,
                    claimed_attempt=lease.claimed_attempt,
                )

            _record_event(db, "lease_renewed", packet_id, {
                "worker_id": worker_id,
                "lease_id": lease.id,
                "new_expires_at": new_expires.isoformat(),
                "claimed_attempt": lease.claimed_attempt,
            })
            _log.info("lease_renewed", packet_id=packet_id,
                worker_id=worker_id, new_expires_at=new_expires.isoformat())

            db.commit()
            return new_expires

    TERMINAL_STATES: frozenset[PacketState] = frozenset({
        PacketState.MERGED,
        PacketState.FAILED,
        PacketState.BLOCKED_FINAL,
        PacketState.CANCELLED,
    })

    async def cancel(self, packet_id: str, reason: str = "") -> CancelResult:
        """Cancel a packet: any non-terminal state → CANCELLED. Releases lease.

        Returns a `CancelResult` DTO (frozen dataclass) so callers can read
        fields after the session closes without `DetachedInstanceError`.

        Raises:
            PacketNotFoundError: packet_id not in DB.
            StateTransitionError: packet is already in a terminal state.
        """
        with self._db_factory() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                raise PacketNotFoundError(packet_id)
            current = PacketStateMachine.normalize_state(packet.state)
            if current in self.TERMINAL_STATES:
                raise StateTransitionError(
                    f"Cannot cancel terminal packet: {current.value}"
                )
            await self._transition_in_session(
                db, packet_id, PacketState.CANCELLED, reason=f"cancel:{reason}",
            )
            lease = db.query(Lease).filter_by(packet_id=packet_id).first()
            released_worker_id: str | None = None
            if lease:
                released_worker_id = lease.worker_id
                db.delete(lease)
            if released_worker_id:
                worker = db.query(Worker).filter_by(id=released_worker_id).first()
                if worker:
                    worker.current_packet_id = None

            result = CancelResult(
                packet_id=packet_id,
                state=PacketState.CANCELLED.value,
                reason=reason,
                previous_state=current.value,
            )
            db.commit()
            _log.info("packet_cancelled", packet_id=packet_id, reason=reason)
            asyncio.create_task(self._broadcast(packet_id, "cancelled", f"cancel:{reason}"))
            return result
