# ############################################################################
# AI_HEADER: safe_queue_claim_service — Atomic safe parallel packet claims
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Select and claim one packet from the earliest eligible wave while
#          atomically enforcing capacity, dependencies, scope, and key safety.
# inputs: worker_id, GRACE_MAX_CONCURRENCY, and the initialized SQLAlchemy DB.
# returns: (ClaimResult | None, reason) with a normal packet lease and, when
#          claimed, a parallel resource lease in the same transaction.
# side_effects: Short DB transaction updates feature/packet/worker/lease/event
#               rows and creates a parallel_leases reservation.
# emitted_logs: safe_claim_start, safe_claim_done, safe_claim_wait,
#               safe_claim_retry, safe_claim_locked.
# error_behavior: Returns a wait reason for unavailable work or bounded SQLite
#                 lock contention; propagates non-lock database failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SafeQueueClaimService
#     methods:
#       - claim_next_atomic
# END_MODULE_MAP

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime
from operator import attrgetter

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from grace_control.config.settings import get_max_concurrency
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Event, Feature, Lease, Packet, PacketState, Wave
from grace_control.services.packet_service import ClaimResult, PacketService
from grace_control.services.parallel_conflict_service import ParallelConflictService
from grace_control.services.parallel_lease_service import ParallelLeaseService
from grace_control.services.rework_packet_service import effective_rework_packets, is_rework_spec

_log = GraceLogger("safe_queue_claim")

_TERMINAL_SUCCESS = frozenset({PacketState.MERGED.value, PacketState.CANCELLED.value})
_ACTIVE_PACKET_STATES = frozenset({PacketState.RUNNING.value, PacketState.ACCEPTED.value})


# START_BLOCK_SAFE_QUEUE_CLAIM_SERVICE
class SafeQueueClaimService:
    """Transaction-safe queue selector for compatible parallel work."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure the DB factory and bounded SQLite lock retry policy.
    # inputs: db_factory — transactional session factory; max_retries and
    #         base_backoff_seconds — bounded contention policy.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None for valid retry settings.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        db_factory=None,
        *,
        max_retries: int = 5,
        base_backoff_seconds: float = 0.02,
    ) -> None:
        self._db_factory = db_factory or get_db
        self._max_retries = max(1, max_retries)
        self._base_backoff_seconds = max(0.001, base_backoff_seconds)
        self._conflicts = ParallelConflictService()
        self._parallel_leases = ParallelLeaseService(conflict_service=self._conflicts)
        self._packets = PacketService()
        self._last_wait_reason = ""
        self._last_wait_packet_id: str | None = None

    # START_FUNCTION_CONTRACT
    # name: get_last_wait_reason
    # purpose: Return the typed wait reason from the most recent claim attempt.
    # inputs: None.
    # returns: Typed wait reason or an empty string after a successful claim.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def get_last_wait_reason(self) -> str:
        return self._last_wait_reason

    # START_FUNCTION_CONTRACT
    # name: get_last_wait_packet_id
    # purpose: Return the packet whose claim was blocked by the latest wait.
    # inputs: None.
    # returns: Packet ID or None when the wait was feature/global scoped.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def get_last_wait_packet_id(self) -> str | None:
        return self._last_wait_packet_id

    # START_FUNCTION_CONTRACT
    # name: claim_next_atomic
    # purpose: Atomically select and claim the next safe packet for one worker.
    # inputs: worker_id — worker ownership/fencing identity.
    # returns: (ClaimResult, "ok") on success, or (None, reason) when waiting.
    # side_effects: Performs one short serialized DB transaction per attempt.
    # emitted_logs: safe_claim_start, safe_claim_done, safe_claim_wait,
    #               safe_claim_retry, safe_claim_locked.
    # error_behavior: Bounded retry on SQLite lock contention; returns
    #                 database_locked after retries, propagates other errors.
    # END_FUNCTION_CONTRACT
    def claim_next_atomic(self, worker_id: str) -> tuple[ClaimResult | None, str]:
        self._last_wait_reason = ""
        self._last_wait_packet_id = None
        for attempt in range(self._max_retries):
            try:
                _log.info("safe_claim_start", worker_id=worker_id, attempt=attempt + 1)
                result = self._claim_once(worker_id)
                if result[0] is not None:
                    _log.info(
                        "safe_claim_done",
                        worker_id=worker_id,
                        packet_id=result[0].packet_id,
                    )
                else:
                    _log.info("safe_claim_wait", worker_id=worker_id, reason=result[1])
                return result
            except OperationalError as error:
                if not self._is_lock_contention(error):
                    raise
                if attempt + 1 >= self._max_retries:
                    _log.warn("safe_claim_locked", worker_id=worker_id, reason="retry_exhausted")
                    return None, "database_locked"
                delay = self._base_backoff_seconds * (2**attempt)
                _log.info(
                    "safe_claim_retry",
                    worker_id=worker_id,
                    attempt=attempt + 1,
                    reason="database_locked",
                )
                time.sleep(delay)
        return None, "database_locked"

    # START_FUNCTION_CONTRACT
    # name: _claim_once
    # purpose: Execute one complete candidate-selection and claim transaction.
    # inputs: worker_id — worker ownership identity.
    # returns: Claim result and reason tuple.
    # side_effects: Opens a DB transaction and mutates queue/lease rows.
    # emitted_logs: None beyond delegated service logs.
    # error_behavior: Propagates SQLAlchemy errors to the bounded retry wrapper.
    # END_FUNCTION_CONTRACT
    def _claim_once(self, worker_id: str) -> tuple[ClaimResult | None, str]:
        with self._db_factory() as db:
            self._begin_atomic_transaction(db)
            now = datetime.now(UTC)
            self._parallel_leases.expire(db, now=now)
            max_concurrency = get_max_concurrency()
            feature = self._select_active_feature(db)
            if feature is None:
                self._record_wait(
                    db,
                    entity_id=None,
                    reason="waiting_for_wave_completion",
                    feature_id=None,
                )
                return None, "no_queued_features"
            active_capacity = self._active_capacity(db)
            if max_concurrency == 1 and active_capacity:
                self._record_wait(
                    db,
                    entity_id=None,
                    reason="waiting_for_wave_completion",
                    feature_id=feature.id,
                )
                return None, "running_packet_exists"
            if active_capacity >= max_concurrency:
                self._record_wait(
                    db,
                    entity_id=None,
                    reason="waiting_for_concurrency_slot",
                    feature_id=feature.id,
                )
                return None, "capacity"

            candidate, reason = self._select_candidate(db, feature, now)
            if candidate is None:
                self._record_wait(
                    db,
                    entity_id=self._last_wait_packet_id,
                    reason=self._last_wait_reason or reason,
                    feature_id=feature.id,
                )
                return None, reason

            result = self._packets._claim_in_session(db, candidate.id, worker_id)
            spec = result.spec if isinstance(result.spec, dict) else {}
            parallel = self._parallel_leases.acquire(
                db,
                packet_id=result.packet_id,
                feature_id=result.feature_id,
                wave_id=result.wave_id,
                worker_id=worker_id,
                claimed_attempt=result.claimed_attempt,
                scope=spec.get("scope", []),
                conflict_keys=spec.get("conflict_keys", []),
                base_sha=spec.get("base_sha"),
                now=now,
            )
            return replace(
                result,
                parallel_lease_id=parallel.id,
                parallel_expires_at=parallel.expires_at,
            ), "ok"

    # START_FUNCTION_CONTRACT
    # name: _record_wait
    # purpose: Persist a typed, non-failure wait observation for diagnostics.
    # inputs: db — active claim transaction; entity_id — optional packet;
    #         reason — typed wait reason; feature_id — optional feature.
    # returns: None.
    # side_effects: Inserts one Event row without changing packet state.
    # emitted_logs: None.
    # error_behavior: None for valid event data.
    # END_FUNCTION_CONTRACT
    def _record_wait(
        self,
        db,
        *,
        entity_id: str | None,
        reason: str,
        feature_id: str | None,
    ) -> None:
        self._last_wait_reason = reason
        self._last_wait_packet_id = entity_id
        db.add(Event(
            event_type="packet_wait",
            entity_type="packet" if entity_id else "feature",
            entity_id=entity_id or feature_id or "queue",
            payload_json={
                "reason": reason,
                "feature_id": feature_id,
                "packet_id": entity_id,
                "expected_wait": True,
            },
            timestamp=datetime.now(UTC),
        ))

    # START_FUNCTION_CONTRACT
    # name: _select_active_feature
    # purpose: Resolve the current active feature or promote the oldest queued one.
    # inputs: db — current atomic transaction.
    # returns: Active Feature or None when the queue is empty.
    # side_effects: May update a feature status to active.
    # emitted_logs: safe_feature_activated.
    # error_behavior: None for an empty queue.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _select_active_feature(db) -> Feature | None:
        feature = (
            db.query(Feature)
            .with_for_update()
            .filter(Feature.status == "active")
            .order_by(Feature.created_at.asc(), Feature.id.asc())
            .first()
        )
        if feature is not None:
            return feature

        degraded_features = (
            db.query(Feature)
            .with_for_update()
            .filter(Feature.status == "degraded")
            .order_by(Feature.created_at.asc(), Feature.id.asc())
            .all()
        )
        for degraded in degraded_features:
            packets = db.query(Packet).filter(Packet.feature_id == degraded.id).all()
            effective = effective_rework_packets(packets)
            ready_reworks = [
                packet
                for packet in effective
                if SafeQueueClaimService._packet_state(packet) == PacketState.READY.value
                and is_rework_spec(packet.spec_json)
            ]
            if not ready_reworks:
                continue
            degraded.status = "active"
            degraded.degraded_reason = None
            for packet in ready_reworks:
                wave = db.query(Wave).filter_by(id=packet.wave_id).first()
                if wave is not None:
                    wave.status = "IN_PROGRESS"
            _log.info("safe_rework_reactivated", feature_id=degraded.id)
            return degraded

        queued = (
            db.query(Feature)
            .with_for_update()
            .filter(Feature.status.in_(["queued", "NOT_STARTED"]))
            .order_by(Feature.created_at.asc(), Feature.id.asc())
            .first()
        )
        if queued is None:
            return None
        queued.status = "active"
        queued.updated_at = datetime.now(UTC)
        _log.info("safe_feature_activated", feature_id=queued.id)
        return queued

    # START_FUNCTION_CONTRACT
    # name: _select_candidate
    # purpose: Select the earliest dependency-ready packet that has no active
    #         scope/key conflict, without skipping a blocked earlier wave.
    # inputs: db — current atomic transaction; feature — active feature; now — clock.
    # returns: (Packet, "ok") or (None, wait reason).
    # side_effects: May mark a feature degraded or done according to queue policy.
    # emitted_logs: safe_feature_degraded, safe_feature_done.
    # error_behavior: Invalid candidate scopes are treated as conservative waits.
    # END_FUNCTION_CONTRACT
    def _select_candidate(
        self,
        db,
        feature: Feature,
        now: datetime,
    ) -> tuple[Packet | None, str]:
        waves = (
            db.query(Wave)
            .filter(Wave.feature_id == feature.id)
            .order_by(Wave.order.asc(), Wave.created_at.asc(), Wave.id.asc())
            .all()
        )
        feature_packets = (
            db.query(Packet)
            .with_for_update()
            .filter(Packet.feature_id == feature.id)
            .all()
        )
        effective_feature = effective_rework_packets(feature_packets)
        packets_by_title = self._packets_by_title(feature_packets, effective_feature)
        active_leases = self._parallel_leases.active_leases(db, now=now)

        for wave in waves:
            wave_packets = (
                db.query(Packet)
                .with_for_update()
                .filter(Packet.wave_id == wave.id)
                .all()
            )
            effective_wave = effective_rework_packets(wave_packets)
            if not effective_wave:
                continue
            raw_ready = [packet for packet in effective_wave if self._is_ready(packet)]
            ready = [
                packet
                for packet in raw_ready
                if self._dependencies_satisfied(packet, packets_by_title)
            ]
            if self._has_degrading_packet(effective_wave):
                feature.status = "degraded"
                feature.updated_at = datetime.now(UTC)
                _log.warn("safe_feature_degraded", feature_id=feature.id, wave_id=wave.id)
                return None, "feature_degraded"
            if raw_ready and not ready:
                self._last_wait_reason = "waiting_for_dependency"
                self._last_wait_packet_id = raw_ready[0].id
                return None, "waiting_for_dependencies"
            if not ready:
                if all(self._terminal_success(packet) for packet in effective_wave):
                    continue
                self._last_wait_reason = "waiting_for_wave_completion"
                self._last_wait_packet_id = None
                return None, "waiting_for_wave_completion"

            ready.sort(key=lambda packet: (packet.created_at, packet.id))
            for packet in ready:
                if self._packet_has_live_ordinary_lease(db, packet.id, now):
                    continue
                try:
                    spec = packet.spec_json if isinstance(packet.spec_json, dict) else {}
                    if self._conflicts.can_run_together(
                        spec.get("scope", []),
                        spec.get("conflict_keys", []),
                        active_leases,
                    ):
                        self._last_wait_reason = ""
                        self._last_wait_packet_id = None
                        return packet, "ok"
                except ValueError:
                    continue
            self._last_wait_packet_id = ready[0].id
            self._last_wait_reason = self._candidate_conflict_wait_reason(
                ready,
                active_leases,
            )
            return None, "waiting_for_conflict"

        if effective_feature and all(self._terminal_success(packet) for packet in effective_feature):
            feature.status = "done"
            feature.updated_at = datetime.now(UTC)
            _log.info("safe_feature_done", feature_id=feature.id)
            return None, "feature_done"
        self._last_wait_reason = "waiting_for_wave_completion"
        self._last_wait_packet_id = None
        return None, "waiting_for_wave_completion"

    # START_FUNCTION_CONTRACT
    # name: _candidate_conflict_wait_reason
    # purpose: Classify a blocked READY frontier as scope or semantic-key wait.
    # inputs: ready — deterministic READY candidates; active_leases — snapshots.
    # returns: Typed conflict wait reason.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Returns scope wait conservatively when both checks are
    #                 unavailable or malformed.
    # END_FUNCTION_CONTRACT
    def _candidate_conflict_wait_reason(self, ready, active_leases) -> str:
        saw_scope = False
        saw_key = False
        for packet in ready:
            spec = packet.spec_json if isinstance(packet.spec_json, dict) else {}
            candidate_scope = spec.get("scope", [])
            candidate_keys = spec.get("conflict_keys", [])
            for lease in active_leases:
                try:
                    if self._conflicts.scopes_overlap(
                        candidate_scope,
                        getattr(lease, "scope_json", []),
                    ):
                        saw_scope = True
                    if self._conflicts.conflict_keys_overlap(
                        candidate_keys,
                        getattr(lease, "conflict_keys_json", []),
                    ):
                        saw_key = True
                except ValueError:
                    saw_scope = True
        if saw_scope:
            return "waiting_for_scope_conflict"
        if saw_key:
            return "waiting_for_conflict_key"
        return "waiting_for_scope_conflict"

    # START_FUNCTION_CONTRACT
    # name: _packets_by_title
    # purpose: Resolve dependency titles to effective rework leaves.
    # inputs: packets — feature packets; effective — current rework leaves.
    # returns: Title-to-effective-packet mapping.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None; unresolved rework chains retain their own packet.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _packets_by_title(packets: list[Packet], effective: list[Packet]) -> dict[str, Packet]:
        effective_by_id = {packet.id: packet for packet in effective}
        result: dict[str, Packet] = {}
        for packet in packets:
            target = packet
            seen: set[str] = set()
            while target.id not in effective_by_id and target.id not in seen:
                seen.add(target.id)
                children = [
                    candidate
                    for candidate in packets
                    if is_rework_spec(candidate.spec_json)
                    and candidate.spec_json.get("parent_packet_id") == target.id
                    and SafeQueueClaimService._packet_state(candidate) != PacketState.CANCELLED.value
                ]
                if len(children) != 1:
                    break
                target = children[0]
            result[packet.title] = target
        return result

    # START_FUNCTION_CONTRACT
    # name: _active_capacity
    # purpose: Count currently occupied global execution slots.
    # inputs: db — current atomic transaction.
    # returns: Number of running/accepted packets, including legacy claims.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _active_capacity(db) -> int:
        return db.query(Packet).filter(attrgetter("state")(Packet).in_(_ACTIVE_PACKET_STATES)).count()

    # START_FUNCTION_CONTRACT
    # name: _packet_has_live_ordinary_lease
    # purpose: Keep a READY packet with a still-live legacy lease out of candidates.
    # inputs: db — transaction; packet_id — candidate; now — UTC clock.
    # returns: True when an ordinary packet lease is live.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _packet_has_live_ordinary_lease(db, packet_id: str, now: datetime) -> bool:
        lease = db.query(Lease).filter_by(packet_id=packet_id).first()
        if lease is None:
            return False
        expires = lease.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return expires > now

    # START_FUNCTION_CONTRACT
    # name: _dependencies_satisfied
    # purpose: Apply the canonical MERGED/CANCELLED dependency policy.
    # inputs: packet — candidate; packets_by_title — effective title map.
    # returns: True when every declared dependency is terminal success.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Missing dependencies return False.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _dependencies_satisfied(packet: Packet, packets_by_title: dict[str, Packet]) -> bool:
        spec = packet.spec_json if isinstance(packet.spec_json, dict) else {}
        dependencies = spec.get("depends_on", [])
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        for title in dependencies:
            dependency = packets_by_title.get(title)
            if dependency is None or SafeQueueClaimService._packet_state(dependency) not in _TERMINAL_SUCCESS:
                return False
        return True

    # START_FUNCTION_CONTRACT
    # name: _is_ready
    # purpose: Identify a packet eligible for the claim state transition.
    # inputs: packet — ORM packet row.
    # returns: True for READY state.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _is_ready(packet: Packet) -> bool:
        return attrgetter("state")(packet) == PacketState.READY.value

    # START_FUNCTION_CONTRACT
    # name: _terminal_success
    # purpose: Identify a packet that permits later wave/dependency progress.
    # inputs: packet — ORM packet row.
    # returns: True for MERGED or backward-compatible CANCELLED state.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _terminal_success(packet: Packet) -> bool:
        return SafeQueueClaimService._packet_state(packet) in _TERMINAL_SUCCESS

    # START_FUNCTION_CONTRACT
    # name: _has_degrading_packet
    # purpose: Identify terminal failure states that degrade the feature.
    # inputs: packets — effective wave packets.
    # returns: True for FAILED, BLOCKED_FINAL, or exhausted REJECTED.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _has_degrading_packet(packets: list[Packet]) -> bool:
        for packet in packets:
            if SafeQueueClaimService._packet_state(packet) in {
                PacketState.FAILED.value,
                PacketState.BLOCKED_FINAL.value,
                PacketState.BLOCKED.value,
            }:
                return True
            if (
                SafeQueueClaimService._packet_state(packet) == PacketState.REJECTED.value
                and (packet.attempt_count or 0) >= (packet.max_attempts or 0)
            ):
                return True
        return False

    # START_FUNCTION_CONTRACT
    # name: _packet_state
    # purpose: Read packet state without owning or mutating the state machine.
    # inputs: packet — ORM packet row.
    # returns: Stored state string.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None for a mapped Packet row.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _packet_state(packet: Packet) -> str:
        return attrgetter("state")(packet)

    # START_FUNCTION_CONTRACT
    # name: _begin_atomic_transaction
    # purpose: Serialize SQLite claim selection with BEGIN IMMEDIATE.
    # inputs: db — newly opened SQLAlchemy Session.
    # returns: None.
    # side_effects: Starts a write-reserving database transaction on SQLite.
    # emitted_logs: None.
    # error_behavior: Propagates OperationalError for the caller's retry loop.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _begin_atomic_transaction(db) -> None:
        if db.get_bind().dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))

    # START_FUNCTION_CONTRACT
    # name: _is_lock_contention
    # purpose: Recognize SQLite's bounded lock contention errors.
    # inputs: error — SQLAlchemy OperationalError.
    # returns: True for retryable lock messages.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _is_lock_contention(error: OperationalError) -> bool:
        message = str(error).lower()
        return "database is locked" in message or "database table is locked" in message


# END_BLOCK_SAFE_QUEUE_CLAIM_SERVICE
