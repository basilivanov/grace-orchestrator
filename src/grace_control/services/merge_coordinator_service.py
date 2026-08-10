# ############################################################################
# AI_HEADER: merge_coordinator_service — Fenced serialized target-repo merges
# ROLE: Coordinates DB-backed merge leases and the mutation guard used by
#       MergeService. It serializes one logical target repository across
#       processes and provides deterministic ordering for accepted packets.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Own target-repository merge leases, fencing, repo sanity checks,
#          mutation guards, and accepted-packet merge ordering.
# inputs: SQLAlchemy sessions, target repository paths, packet identities, and
#         GitService operations.
# returns: MergeLease rows, sanity/order results, or guarded git results.
# side_effects: Inserts, updates, and deletes merge_leases; reads git state;
#               renews active leases during caller-provided guarded target
#               mutations.
# emitted_logs: merge_lease_acquired, merge_lease_busy, merge_lease_fenced,
#               merge_lease_renewed, merge_lease_released, merge_repo_sanity,
#               merge_lease_heartbeat_failed, merge_mutation_start,
#               merge_mutation_done.
# error_behavior: Raises typed busy/fencing/takeover errors; sanity failures
#                 are returned as RepoSanity with ok=False.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: MergeLeaseBusyError
#   - class: MergeLeaseFencedError
#   - class: MergeLeaseTakeoverError
#   - class: RepoSanity
#   - class: MergeCoordinatorService
#     methods:
#       - normalize_target_repo_key
#       - check_repo_sanity
#       - acquire
#       - try_acquire
#       - renew
#       - release
#       - assert_current
#       - run_mutation
#       - _heartbeat_loop
#       - accepted_merge_order
#       - can_merge_now
# END_MODULE_MAP

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from grace_control.config.settings import settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import MergeLease, Packet, PacketState, Wave
from grace_control.services.git_service import GitResult, GitService

_log = GraceLogger("merge_coordinator")
_T = TypeVar("_T")


class MergeLeaseBusyError(RuntimeError):
    """Raised when another holder owns the target repository merge lease."""


class MergeLeaseFencedError(RuntimeError):
    """Raised when a stale holder attempts to read or mutate under a lease."""


class MergeLeaseTakeoverError(RuntimeError):
    """Raised when an expired lease cannot be safely reclaimed."""


@dataclass(frozen=True)
class RepoSanity:
    """Non-destructive target-repository safety result."""

    ok: bool
    target_repo_key: str
    repo_root: str
    is_git: bool
    is_clean: bool
    merge_in_progress: bool
    error: str = ""


# START_BLOCK_MERGE_COORDINATOR_SERVICE
class MergeCoordinatorService:
    """Serialize target-repository mutations with a durable fencing lease."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure DB, GitService, lease lifetime, and lock retry policy.
    # inputs: db_factory — session context factory; git — git adapter;
    #         ttl_seconds — optional merge lease lifetime.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None for positive TTL and retry values.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        db_factory=None,
        git: GitService | None = None,
        *,
        ttl_seconds: int | None = None,
        max_retries: int = 5,
    ) -> None:
        self._db_factory = db_factory or get_db
        self._git = git or GitService()
        configured_ttl = getattr(settings, "merge_lease_ttl_seconds", 300)
        self._ttl_seconds = max(1, int(ttl_seconds or configured_ttl))
        self._max_retries = max(1, int(max_retries))

    # START_FUNCTION_CONTRACT
    # name: normalize_target_repo_key
    # purpose: Canonicalize path aliases into one deterministic logical-repo key.
    # inputs: target_repo_root — path spelling or symlink to a target repository.
    # returns: Absolute normalized target_repo_key string.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises ValueError for an empty path.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def normalize_target_repo_key(target_repo_root: str | Path) -> str:
        raw = str(target_repo_root).strip()
        if not raw:
            raise ValueError("target_repo_root is required")
        return str(Path(raw).expanduser().resolve(strict=False))

    # START_FUNCTION_CONTRACT
    # name: check_repo_sanity
    # purpose: Verify expected repository root, clean working state, and absence
    #          of an in-progress merge before initial use or takeover.
    # inputs: target_repo_root — candidate repository path; expected_target_repo_key
    #         — optional key already stored in the expired lease.
    # returns: RepoSanity with ok=False instead of mutating or repairing the repo.
    # side_effects: Read-only git commands only.
    # emitted_logs: merge_repo_sanity.
    # error_behavior: Git failures are represented as an unsuccessful result.
    # END_FUNCTION_CONTRACT
    def check_repo_sanity(
        self,
        target_repo_root: str | Path,
        *,
        expected_target_repo_key: str | None = None,
    ) -> RepoSanity:
        requested = Path(target_repo_root).expanduser().resolve(strict=False)
        target_repo_key = expected_target_repo_key or self.normalize_target_repo_key(requested)
        info = self._git.validate_repo(requested)
        if not getattr(info, "is_git", False):
            return self._sanity_failure(
                target_repo_key,
                requested,
                is_git=False,
                error=f"target repo is not a git repository: {requested}",
            )

        actual_root = requested
        show_root = self._run_git(["rev-parse", "--show-toplevel"], requested)
        if show_root is not None:
            if not show_root.success or not show_root.stdout.strip():
                return self._sanity_failure(
                    target_repo_key,
                    requested,
                    is_git=True,
                    error=f"target repo root check failed: {show_root.stderr}",
                )
            actual_root = Path(show_root.stdout.strip()).expanduser().resolve(strict=False)
        if str(actual_root) != target_repo_key:
            return self._sanity_failure(
                target_repo_key,
                actual_root,
                is_git=True,
                error=(
                    f"target repo root mismatch: expected {target_repo_key}, "
                    f"got {actual_root}"
                ),
            )

        status = self._run_git(["status", "--porcelain"], requested)
        if status is not None:
            if not status.success:
                return self._sanity_failure(
                    target_repo_key,
                    actual_root,
                    is_git=True,
                    error=f"target repo status failed: {status.stderr}",
                )
            is_clean = not status.stdout.strip()
        else:
            is_clean = bool(getattr(info, "is_clean", False))
        if not is_clean:
            return self._sanity_failure(
                target_repo_key,
                actual_root,
                is_git=True,
                is_clean=False,
                error=f"target repo is dirty: {requested}",
            )

        merge_in_progress = any(
            self._git_ref_exists(ref, requested)
            for ref in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_HEAD")
        )
        if merge_in_progress:
            return self._sanity_failure(
                target_repo_key,
                actual_root,
                is_git=True,
                is_clean=is_clean,
                merge_in_progress=True,
                error="target repo has an in-progress git operation",
            )

        result = RepoSanity(
            ok=True,
            target_repo_key=target_repo_key,
            repo_root=str(actual_root),
            is_git=True,
            is_clean=is_clean,
            merge_in_progress=False,
        )
        _log.info("merge_repo_sanity", target_repo_key=target_repo_key, ok=True)
        return result

    # START_FUNCTION_CONTRACT
    # name: acquire
    # purpose: Atomically create or safely reclaim one target repository merge
    #          lease with a fresh fencing token.
    # inputs: db — optional caller transaction; target_repo_key or
    #         target_repo_root — logical target; packet_id, worker_id — holder;
    #         now — optional UTC clock.
    # returns: Newly acquired MergeLease ORM row.
    # side_effects: Inserts a merge_leases row; expired takeover deletes only
    #               after repo sanity passes.
    # emitted_logs: merge_lease_acquired, merge_lease_busy.
    # error_behavior: Raises MergeLeaseBusyError or MergeLeaseTakeoverError.
    # END_FUNCTION_CONTRACT
    def acquire(
        self,
        db=None,
        *,
        target_repo_key: str | None = None,
        target_repo_root: str | Path | None = None,
        packet_id: str,
        worker_id: str | None = None,
        now: datetime | None = None,
    ) -> MergeLease:
        key = self._resolve_repo_key(target_repo_key, target_repo_root)
        current_time = _utc(now or datetime.now(UTC))
        if db is not None:
            self._begin_atomic_transaction(db)
            return self._acquire_in_session(
                db,
                key=key,
                target_repo_root=target_repo_root,
                packet_id=packet_id,
                worker_id=worker_id,
                now=current_time,
            )

        last_error: OperationalError | None = None
        for attempt in range(self._max_retries):
            try:
                with self._db_factory() as session:
                    self._begin_atomic_transaction(session)
                    return self._acquire_in_session(
                        session,
                        key=key,
                        target_repo_root=target_repo_root,
                        packet_id=packet_id,
                        worker_id=worker_id,
                        now=current_time,
                    )
            except OperationalError as error:
                if not self._is_lock_contention(error) or attempt + 1 >= self._max_retries:
                    raise
                last_error = error
                time.sleep(0.02 * (2**attempt))
        raise last_error or RuntimeError("merge lease acquisition failed")

    # START_FUNCTION_CONTRACT
    # name: try_acquire
    # purpose: Attempt merge lease acquisition and convert an occupied slot into
    #          a non-exceptional wait result.
    # inputs: Same keyword inputs as acquire.
    # returns: MergeLease or None when another holder owns the slot.
    # side_effects: Same as acquire.
    # emitted_logs: merge_lease_busy.
    # error_behavior: Propagates fencing, sanity, and database failures.
    # END_FUNCTION_CONTRACT
    def try_acquire(self, *args, **kwargs) -> MergeLease | None:
        try:
            return self.acquire(*args, **kwargs)
        except MergeLeaseBusyError:
            return None

    # START_FUNCTION_CONTRACT
    # name: renew
    # purpose: Extend a current merge lease without changing its fencing token.
    # inputs: target_repo_key, lease_token, packet_id, worker_id — exact holder
    #         identity; now — optional UTC clock.
    # returns: New expiry timestamp.
    # side_effects: Updates expires_at and heartbeat_at.
    # emitted_logs: merge_lease_renewed, merge_lease_fenced.
    # error_behavior: Raises MergeLeaseFencedError for missing, stale, or expired identity.
    # END_FUNCTION_CONTRACT
    def renew(
        self,
        *,
        target_repo_key: str,
        lease_token: str,
        packet_id: str,
        worker_id: str | None = None,
        now: datetime | None = None,
    ) -> datetime:
        current_time = _utc(now or datetime.now(UTC))
        with self._db_factory() as db:
            lease = self._assert_current_in_session(
                db,
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                now=current_time,
            )
            lease.heartbeat_at = current_time
            lease.expires_at = current_time + timedelta(seconds=self._ttl_seconds)
            db.flush()
            _log.info("merge_lease_renewed", target_repo_key=target_repo_key, packet_id=packet_id)
            return lease.expires_at

    # START_FUNCTION_CONTRACT
    # name: release
    # purpose: Delete a merge lease only when its fencing identity is current.
    # inputs: target_repo_key, lease_token, packet_id, worker_id — exact holder identity.
    # returns: True after deleting the matching row.
    # side_effects: Deletes one merge_leases row.
    # emitted_logs: merge_lease_released, merge_lease_fenced.
    # error_behavior: Raises MergeLeaseFencedError for stale identity.
    # END_FUNCTION_CONTRACT
    def release(
        self,
        *,
        target_repo_key: str,
        lease_token: str,
        packet_id: str,
        worker_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        current_time = _utc(now or datetime.now(UTC))
        with self._db_factory() as db:
            lease = self._assert_current_in_session(
                db,
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                now=current_time,
            )
            db.delete(lease)
            db.flush()
            _log.info("merge_lease_released", target_repo_key=target_repo_key, packet_id=packet_id)
            return True

    # START_FUNCTION_CONTRACT
    # name: assert_current
    # purpose: Validate the current fencing token immediately before a guarded
    #          mutation step.
    # inputs: target_repo_key, lease_token, packet_id, worker_id — holder identity.
    # returns: None when the lease is current and unexpired.
    # side_effects: Read-only DB query.
    # emitted_logs: merge_lease_fenced on rejection.
    # error_behavior: Raises MergeLeaseFencedError for any mismatch or expiry.
    # END_FUNCTION_CONTRACT
    def assert_current(
        self,
        *,
        target_repo_key: str,
        lease_token: str,
        packet_id: str,
        worker_id: str | None = None,
        now: datetime | None = None,
    ) -> None:
        current_time = _utc(now or datetime.now(UTC))
        with self._db_factory() as db:
            self._assert_current_in_session(
                db,
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                now=current_time,
            )

    # START_FUNCTION_CONTRACT
    # name: run_mutation
# purpose: Execute one target-repository mutation only while the current
#          merge fencing token is valid and renew it for the callback lifetime.
    # inputs: lease identity, step_name, and a synchronous mutation callback.
    # returns: Callback result.
    # side_effects: Runs the caller's checkout/fetch/merge/push operation.
    # emitted_logs: merge_mutation_start, merge_mutation_done.
# error_behavior: Raises MergeLeaseFencedError before a stale callback or
#                 after heartbeat/expiry fencing is detected.
    # END_FUNCTION_CONTRACT
    def run_mutation(
        self,
        *,
        target_repo_key: str,
        lease_token: str,
        packet_id: str,
        worker_id: str | None,
        step_name: str,
        operation: Callable[[], _T],
    ) -> _T:
        self.assert_current(
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
        )
        heartbeat_stop = threading.Event()
        heartbeat_errors: list[BaseException] = []
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            kwargs={
                "target_repo_key": target_repo_key,
                "lease_token": lease_token,
                "packet_id": packet_id,
                "worker_id": worker_id,
                "stop_event": heartbeat_stop,
                "errors": heartbeat_errors,
            },
            name=f"merge-heartbeat-{packet_id}",
            daemon=True,
        )
        heartbeat.start()
        _log.info("merge_mutation_start", target_repo_key=target_repo_key, step=step_name)
        try:
            result = operation()
        finally:
            heartbeat_stop.set()
            heartbeat.join()
        if heartbeat_errors:
            raise MergeLeaseFencedError(str(heartbeat_errors[0]))
        self.assert_current(
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
        )
        _log.info("merge_mutation_done", target_repo_key=target_repo_key, step=step_name)
        return result

    def _heartbeat_loop(
        self,
        *,
        target_repo_key: str,
        lease_token: str,
        packet_id: str,
        worker_id: str | None,
        stop_event: threading.Event,
        errors: list[BaseException],
    ) -> None:
        """Renew one lease while its guarded synchronous mutation is running."""
        interval = max(0.05, min(self._ttl_seconds / 3, 1.0))
        while not stop_event.wait(interval):
            try:
                self.renew(
                    target_repo_key=target_repo_key,
                    lease_token=lease_token,
                    packet_id=packet_id,
                    worker_id=worker_id,
                )
            except MergeLeaseFencedError as error:
                errors.append(error)
                _log.warn(
                    "merge_lease_heartbeat_failed",
                    target_repo_key=target_repo_key,
                    packet_id=packet_id,
                    error=str(error)[:200],
                )
                return
            except Exception as error:
                _log.warn(
                    "merge_lease_heartbeat_failed",
                    target_repo_key=target_repo_key,
                    packet_id=packet_id,
                    error=str(error)[:200],
                )

    # START_FUNCTION_CONTRACT
    # name: accepted_merge_order
    # purpose: Return accepted packets for one target repo in deterministic
    #          Wave.order, Packet.created_at, Packet.id order.
    # inputs: db — optional session; target_repo_root/key — logical target;
    #         packet_ids — optional explicit accepted queue subset.
    # returns: Ordered Packet ORM rows.
    # side_effects: Read-only DB queries.
    # emitted_logs: None.
    # error_behavior: Propagates database errors.
    # END_FUNCTION_CONTRACT
    def accepted_merge_order(
        self,
        db=None,
        *,
        target_repo_root: str | Path | None = None,
        target_repo_key: str | None = None,
        packet_ids: Sequence[str] | None = None,
    ) -> list[Packet]:
        key = self._resolve_repo_key(target_repo_key, target_repo_root)
        if db is not None:
            return self._accepted_merge_order_in_session(db, key=key, packet_ids=packet_ids)
        with self._db_factory() as session:
            return self._accepted_merge_order_in_session(session, key=key, packet_ids=packet_ids)

    # START_FUNCTION_CONTRACT
    # name: can_merge_now
    # purpose: Check whether packet_id is the current accepted merge candidate
    #          for its target repository without waiting for a whole wave.
    # inputs: packet_id and target_repo_root/key identifying the queue.
    # returns: True only for the first accepted packet in deterministic order.
    # side_effects: Read-only DB queries.
    # emitted_logs: None.
    # error_behavior: Propagates database errors.
    # END_FUNCTION_CONTRACT
    def can_merge_now(
        self,
        packet_id: str,
        *,
        target_repo_root: str | Path | None = None,
        target_repo_key: str | None = None,
    ) -> bool:
        ordered = self.accepted_merge_order(
            target_repo_root=target_repo_root,
            target_repo_key=target_repo_key,
        )
        return bool(ordered and ordered[0].id == packet_id)

    # START_FUNCTION_CONTRACT
    # name: _acquire_in_session
    # purpose: Perform one atomic merge lease lookup, safe takeover check, and insert.
    # inputs: db, canonical key, target path, packet identity, and UTC time.
    # returns: Newly inserted MergeLease row.
    # side_effects: DB row delete/insert and flush.
    # emitted_logs: merge_lease_acquired, merge_lease_busy.
    # error_behavior: Raises typed lease errors.
    # END_FUNCTION_CONTRACT
    def _acquire_in_session(
        self,
        db,
        *,
        key: str,
        target_repo_root: str | Path | None,
        packet_id: str,
        worker_id: str | None,
        now: datetime,
    ) -> MergeLease:
        existing = (
            db.query(MergeLease)
            .with_for_update()
            .filter_by(target_repo_key=key)
            .first()
        )
        if existing is not None and _utc(existing.expires_at) > now:
            _log.info("merge_lease_busy", target_repo_key=key, packet_id=packet_id)
            raise MergeLeaseBusyError(f"merge slot busy for target_repo_key={key}")
        if existing is not None:
            takeover_root = target_repo_root or key
            sanity = self.check_repo_sanity(
                takeover_root,
                expected_target_repo_key=key,
            )
            if not sanity.ok:
                raise MergeLeaseTakeoverError(
                    f"expired merge lease takeover blocked: {sanity.error}"
                )
            db.delete(existing)
            db.flush()

        lease = MergeLease(
            target_repo_key=key,
            lease_token=f"mlease_{uuid4().hex}",
            packet_id=packet_id,
            worker_id=worker_id,
            acquired_at=now,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
            heartbeat_at=now,
        )
        db.add(lease)
        try:
            db.flush()
        except IntegrityError as error:
            raise MergeLeaseBusyError(f"merge slot busy for target_repo_key={key}") from error
        _log.info(
            "merge_lease_acquired",
            target_repo_key=key,
            packet_id=packet_id,
            worker_id=worker_id or "",
            lease_token=lease.lease_token,
        )
        return lease

    # START_FUNCTION_CONTRACT
    # name: _accepted_merge_order_in_session
    # purpose: Query and sort accepted packets for one canonical target key.
    # inputs: db, target key, and optional packet ID subset.
    # returns: Deterministically ordered Packet rows.
    # side_effects: Read-only DB queries.
    # emitted_logs: None.
    # error_behavior: Propagates database errors.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _accepted_merge_order_in_session(
        db,
        *,
        key: str,
        packet_ids: Sequence[str] | None,
    ) -> list[Packet]:
        query = db.query(Packet).filter(Packet.state == PacketState.ACCEPTED.value)
        if packet_ids is not None:
            query = query.filter(Packet.id.in_(list(packet_ids)))
        packets = [packet for packet in query.all() if _packet_matches_repo(packet, key)]
        wave_ids = {packet.wave_id for packet in packets}
        waves = {
            wave.id: wave.order
            for wave in db.query(Wave).filter(Wave.id.in_(wave_ids)).all()
        } if wave_ids else {}
        packets.sort(
            key=lambda packet: (
                waves.get(packet.wave_id, 2**31 - 1),
                _naive_utc(packet.created_at),
                packet.id,
            )
        )
        return packets

    # START_FUNCTION_CONTRACT
    # name: _assert_current_in_session
    # purpose: Validate the current database lease identity and TTL.
    # inputs: db, target key, token, packet, worker, and current UTC time.
    # returns: Current MergeLease row.
    # side_effects: Read-only DB query.
    # emitted_logs: merge_lease_fenced on rejection.
    # error_behavior: Raises MergeLeaseFencedError for every mismatch.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _assert_current_in_session(
        db,
        *,
        target_repo_key: str,
        lease_token: str,
        packet_id: str,
        worker_id: str | None,
        now: datetime,
    ) -> MergeLease:
        lease = db.query(MergeLease).filter_by(target_repo_key=target_repo_key).first()
        reason = ""
        if lease is None:
            reason = "merge lease not found"
        elif lease.lease_token != lease_token:
            reason = "merge lease token mismatch"
        elif lease.packet_id != packet_id:
            reason = "merge lease packet mismatch"
        elif worker_id is not None and lease.worker_id != worker_id:
            reason = "merge lease worker mismatch"
        elif _utc(lease.expires_at) <= now:
            reason = "merge lease expired"
        if reason:
            _log.warn("merge_lease_fenced", target_repo_key=target_repo_key, reason=reason)
            raise MergeLeaseFencedError(reason)
        return lease

    # START_FUNCTION_CONTRACT
    # name: _resolve_repo_key
    # purpose: Resolve either an explicit canonical key or a target root path.
    # inputs: Optional target_repo_key and target_repo_root.
    # returns: Canonical target repository key.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises ValueError when neither is supplied.
    # END_FUNCTION_CONTRACT
    @classmethod
    def _resolve_repo_key(
        cls,
        target_repo_key: str | None,
        target_repo_root: str | Path | None,
    ) -> str:
        if target_repo_root is not None:
            return cls.normalize_target_repo_key(target_repo_root)
        if target_repo_key:
            return cls.normalize_target_repo_key(target_repo_key)
        raise ValueError("target_repo_key or target_repo_root is required")

    # START_FUNCTION_CONTRACT
    # name: _sanity_failure
    # purpose: Build and log a non-destructive failed repo sanity result.
    # inputs: Canonical key, repo path, flags, and failure reason.
    # returns: RepoSanity with ok=False.
    # side_effects: Structured log only.
    # emitted_logs: merge_repo_sanity.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _sanity_failure(
        target_repo_key: str,
        repo_root: Path,
        *,
        is_git: bool,
        is_clean: bool = False,
        merge_in_progress: bool = False,
        error: str,
    ) -> RepoSanity:
        _log.warn("merge_repo_sanity", target_repo_key=target_repo_key, ok=False, reason=error)
        return RepoSanity(
            ok=False,
            target_repo_key=target_repo_key,
            repo_root=str(repo_root),
            is_git=is_git,
            is_clean=is_clean,
            merge_in_progress=merge_in_progress,
            error=error,
        )

    # START_FUNCTION_CONTRACT
    # name: _run_git
    # purpose: Call a GitService read-only command when the adapter returns a
    #          concrete GitResult; tolerate lightweight injected test doubles.
    # inputs: git argument list and repository path.
    # returns: GitResult or None for non-conforming test doubles.
    # side_effects: Delegated read-only git command.
    # emitted_logs: None.
    # error_behavior: Returns None for unsupported adapter results.
    # END_FUNCTION_CONTRACT
    def _run_git(self, args: list[str], repo: Path) -> GitResult | None:
        result = self._git._run(args, repo)
        return result if isinstance(result, GitResult) else None

    # START_FUNCTION_CONTRACT
    # name: _git_ref_exists
    # purpose: Detect merge/cherry-pick/revert/bisect state without changing it.
    # inputs: ref name and repository path.
    # returns: True when the git state ref exists.
    # side_effects: Read-only git command.
    # emitted_logs: None.
    # error_behavior: False for unsupported test doubles or absent refs.
    # END_FUNCTION_CONTRACT
    def _git_ref_exists(self, ref: str, repo: Path) -> bool:
        result = self._run_git(["rev-parse", "-q", "--verify", ref], repo)
        return bool(result and result.success)

    # START_FUNCTION_CONTRACT
    # name: _begin_atomic_transaction
    # purpose: Reserve the SQLite write lock before inspecting/replacing a lease.
    # inputs: Newly opened SQLAlchemy Session.
    # returns: None.
    # side_effects: Starts a SQLite BEGIN IMMEDIATE transaction.
    # emitted_logs: None.
    # error_behavior: Propagates database lock errors for bounded retry.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _begin_atomic_transaction(db) -> None:
        if db.get_bind().dialect.name == "sqlite" and not db.in_transaction():
            db.execute(text("BEGIN IMMEDIATE"))

    # START_FUNCTION_CONTRACT
    # name: _is_lock_contention
    # purpose: Identify retryable SQLite lock failures during lease acquisition.
    # inputs: OperationalError.
    # returns: True for SQLite lock/busy messages.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: False for unrelated database errors.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _is_lock_contention(error: OperationalError) -> bool:
        message = str(error).lower()
        return "database is locked" in message or "database table is locked" in message


# END_BLOCK_MERGE_COORDINATOR_SERVICE


# START_FUNCTION_CONTRACT
# name: _packet_matches_repo
# purpose: Treat an absent packet target override as the caller's target and
#          match explicit target_repo_root metadata canonically.
# inputs: Packet row and canonical target_repo_key.
# returns: True when packet belongs to the target merge queue.
# side_effects: None.
# emitted_logs: None.
# error_behavior: False for malformed explicit target metadata.
# END_FUNCTION_CONTRACT
def _packet_matches_repo(packet: Packet, target_repo_key: str) -> bool:
    spec = packet.spec_json if isinstance(packet.spec_json, dict) else {}
    declared = spec.get("target_repo_root") or spec.get("target_repo")
    if not declared:
        return True
    try:
        return MergeCoordinatorService.normalize_target_repo_key(declared) == target_repo_key
    except (TypeError, ValueError, OSError):
        return False


# START_FUNCTION_CONTRACT
# name: _naive_utc
# purpose: Normalize DB timestamps for deterministic cross-dialect sorting.
# inputs: Optional datetime.
# returns: Naive UTC datetime, or datetime.min for missing timestamps.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None for datetime input.
# END_FUNCTION_CONTRACT
def _naive_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min
    normalized = _utc(value)
    return normalized.replace(tzinfo=None)


# START_FUNCTION_CONTRACT
# name: _utc
# purpose: Make SQLite-naive timestamps comparable with UTC-aware values.
# inputs: datetime value.
# returns: UTC-aware datetime.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None for datetime input.
# END_FUNCTION_CONTRACT
def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
