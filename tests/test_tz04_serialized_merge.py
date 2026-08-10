# ############################################################################
# AI_HEADER: test_tz04_serialized_merge — TZ04 serialized merge acceptance tests
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify DB-backed target-repository merge serialization, fencing,
#          takeover sanity checks, deterministic accepted ordering, and the
#          TZ03 parallel-lease release after MERGED.
# inputs: Temporary SQLite databases, target paths, and a recording Git double.
# returns: Pytest acceptance results.
# side_effects: Creates temporary DB/repository directories and lease rows.
# emitted_logs: None.
# error_behavior: Assertions identify a violated TZ04 invariant.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: RecordingGit
#   - function: test_same_repo_has_one_holder_and_second_does_not_mutate
#   - function: test_path_aliases_share_merge_lease
#   - function: test_different_repositories_can_mutate_concurrently
#   - function: test_stale_token_cannot_continue_after_takeover
#   - function: test_takeover_refuses_dirty_or_in_progress_repo
#   - function: test_accepted_merge_order_is_wave_created_at_id
#   - function: test_successful_merge_releases_parallel_lease
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db, init_db
from grace_control.db.schema import (
    Feature,
    MergeLease,
    Packet,
    PacketState,
    ParallelLease,
    Wave,
)
from grace_control.services.git_service import GitRepoInfo, GitResult
from grace_control.services.merge_coordinator_service import (
    MergeCoordinatorService,
    MergeLeaseFencedError,
    MergeLeaseTakeoverError,
)
from grace_control.services.merge_service import MergeService
from grace_control.services.parallel_lease_service import ParallelLeaseService

_log = GraceLogger("test_tz04_serialized_merge")


# START_BLOCK_RECORDING_GIT
class RecordingGit:
    """Git double that records guarded target mutation overlap."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active_mutations = 0
        self.max_active_mutations = 0
        self.steps: list[tuple[str, str]] = []
        self.dirty = False
        self.merge_in_progress = False

    # START_FUNCTION_CONTRACT
    # name: validate_repo
    # purpose: Present a clean known repository to the coordinator sanity check.
    # inputs: path — target repository path.
    # returns: GitRepoInfo describing a clean git repository.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def validate_repo(self, path: Path) -> GitRepoInfo:
        return GitRepoInfo(
            path=path.resolve(),
            is_git=True,
            current_branch="main",
            is_clean=not self.dirty,
        )

    # START_FUNCTION_CONTRACT
    # name: _run
    # purpose: Answer coordinator read-only sanity commands and branch cleanup listing.
    # inputs: args — git arguments; cwd — repository path.
    # returns: GitResult.
    # side_effects: Records no target mutation.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def _run(self, args: list[str], cwd: Path, timeout: int | None = None) -> GitResult:
        if args == ["rev-parse", "--show-toplevel"]:
            return GitResult(True, str(cwd.resolve()), "", 0)
        if args == ["status", "--porcelain"]:
            return GitResult(True, " M dirty\n" if self.dirty else "", "", 0)
        if args[:4] == ["rev-parse", "-q", "--verify", "MERGE_HEAD"]:
            return GitResult(self.merge_in_progress, "head" if self.merge_in_progress else "", "", 0 if self.merge_in_progress else 1)
        if args[:3] == ["rev-parse", "-q", "--verify"]:
            return GitResult(False, "", "", 1)
        if args[:2] == ["branch", "--list"]:
            return GitResult(True, "", "", 0)
        return GitResult(True, "", "", 0)

    # START_FUNCTION_CONTRACT
    # name: _mutate
    # purpose: Record one target mutation and expose overlap if callers race.
    # inputs: step — checkout/fetch/merge/push label.
    # returns: Successful GitResult.
    # side_effects: Updates in-memory recorder state.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def _mutate(self, step: str) -> GitResult:
        with self._lock:
            self.active_mutations += 1
            self.max_active_mutations = max(self.max_active_mutations, self.active_mutations)
            self.steps.append(("start", step))
        time.sleep(0.04)
        with self._lock:
            self.steps.append(("done", step))
            self.active_mutations -= 1
        return GitResult(True, "", "", 0)

    # START_FUNCTION_CONTRACT
    # name: checkout
    # purpose: Record checkout mutation.
    # inputs: repo, branch — target checkout.
    # returns: GitResult.
    # side_effects: Recorder mutation event.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def checkout(self, repo: Path, branch: str) -> GitResult:
        return self._mutate("checkout")

    # START_FUNCTION_CONTRACT
    # name: fetch
    # purpose: Record fetch mutation.
    # inputs: repo, remote — target remote.
    # returns: GitResult.
    # side_effects: Recorder mutation event.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def fetch(self, repo: Path, remote: str = "origin") -> GitResult:
        return self._mutate("fetch")

    # START_FUNCTION_CONTRACT
    # name: merge
    # purpose: Record merge mutation.
    # inputs: repo, branch, target_branch — merge refs.
    # returns: GitResult.
    # side_effects: Recorder mutation event.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def merge(self, repo: Path, branch: str, target_branch: str) -> GitResult:
        return self._mutate("merge")

    # START_FUNCTION_CONTRACT
    # name: push
    # purpose: Record push mutation.
    # inputs: repo, remote, branch — push refs.
    # returns: GitResult.
    # side_effects: Recorder mutation event.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def push(self, repo: Path, remote: str = "origin", branch: str | None = None) -> GitResult:
        return self._mutate("push")

    # START_FUNCTION_CONTRACT
    # name: current_sha
    # purpose: Return a stable target HEAD for merge result assertions.
    # inputs: repo — target repository path.
    # returns: Stable commit SHA string.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def current_sha(self, repo: Path) -> str:
        return "a" * 40

# END_BLOCK_RECORDING_GIT


# START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: _database
# purpose: Initialize an isolated file-backed SQLite database at Alembic head.
# inputs: tmp_path — pytest temporary directory.
# returns: Database path.
# side_effects: Creates SQLite schema and migration metadata.
# emitted_logs: None.
# error_behavior: Propagates initialization errors.
# END_FUNCTION_CONTRACT
def _database(tmp_path: Path) -> Path:
    path = tmp_path / "tz04.db"
    init_db(f"sqlite:///{path}")
    return path


# START_FUNCTION_CONTRACT
# name: _seed_packets
# purpose: Seed one feature, waves, and accepted packets for merge tests.
# inputs: tmp_path, packet_specs — packet ID, wave ID, created timestamp, target root.
# returns: Database path.
# side_effects: Inserts feature/wave/packet rows.
# emitted_logs: None.
# error_behavior: Propagates database errors.
# END_FUNCTION_CONTRACT
def _seed_packets(
    tmp_path: Path,
    packet_specs: list[tuple[str, str, datetime, Path]],
) -> Path:
    path = _database(tmp_path)
    wave_ids = sorted({item[1] for item in packet_specs})
    with get_db() as db:
        db.add(Feature(id="feature-1", slug="feature-1", title="Feature 1", spec_json={}, status="active"))
        for order, wave_id in enumerate(wave_ids, start=1):
            db.add(Wave(
                id=wave_id,
                feature_id="feature-1",
                slug=wave_id,
                title=wave_id,
                order=order,
                status="IN_PROGRESS",
            ))
        for packet_id, wave_id, created_at, target_root in packet_specs:
            db.add(Packet(
                id=packet_id,
                feature_id="feature-1",
                wave_id=wave_id,
                slug=packet_id,
                title=packet_id,
                spec_json={"target_repo_root": str(target_root), "scope": [f"src/{packet_id}.py"]},
                state=PacketState.ACCEPTED.value,
                attempt_count=1,
                max_attempts=3,
                created_at=created_at,
                updated_at=created_at,
            ))
    return path


# START_FUNCTION_CONTRACT
# name: _lease
# purpose: Insert a TZ03 parallel resource lease for an accepted packet.
# inputs: packet_id, target_root — packet and target identity.
# returns: None.
# side_effects: Inserts a parallel_leases row.
# emitted_logs: parallel_lease_acquired.
# error_behavior: Propagates database errors.
# END_FUNCTION_CONTRACT
def _lease(packet_id: str, target_root: Path) -> None:
    with get_db() as db:
        ParallelLeaseService(ttl_seconds=300).acquire(
            db,
            packet_id=packet_id,
            feature_id="feature-1",
            wave_id="wave-1",
            worker_id="worker-1",
            claimed_attempt=1,
            scope=[f"src/{packet_id}.py"],
            conflict_keys=[],
            base_sha="a" * 40,
        )

# END_BLOCK_HELPERS


# START_BLOCK_TESTS
# START_FUNCTION_CONTRACT
# name: test_same_repo_has_one_holder_and_second_does_not_mutate
# purpose: Prove the DB lease prevents a second same-repo holder and target step.
# inputs: tmp_path — pytest temporary directory.
# returns: None on success.
# side_effects: Creates leases and records a guarded target mutation.
# emitted_logs: None.
# error_behavior: Assertion failure on concurrent same-repo mutation.
# END_FUNCTION_CONTRACT
def test_same_repo_has_one_holder_and_second_does_not_mutate(tmp_path):
    _database(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    git = RecordingGit()
    coordinator = MergeCoordinatorService(git=git)
    first = coordinator.acquire(target_repo_root=target, packet_id="packet-a", worker_id="worker-a")
    second = coordinator.try_acquire(
        target_repo_root=target,
        packet_id="packet-b",
        worker_id="worker-b",
    )
    assert second is None
    assert git.steps == []

    coordinator.run_mutation(
        target_repo_key=first.target_repo_key,
        lease_token=first.lease_token,
        packet_id="packet-a",
        worker_id="worker-a",
        step_name="checkout",
        operation=lambda: git.checkout(target, "main"),
    )
    assert git.steps == [("start", "checkout"), ("done", "checkout")]
    coordinator.release(
        target_repo_key=first.target_repo_key,
        lease_token=first.lease_token,
        packet_id="packet-a",
        worker_id="worker-a",
    )


# START_FUNCTION_CONTRACT
# name: test_path_aliases_share_merge_lease
# purpose: Prove equivalent target path spellings resolve to one logical repo key.
# inputs: tmp_path — pytest temporary directory.
# returns: None on success.
# side_effects: Creates and releases one merge lease.
# emitted_logs: None.
# error_behavior: Assertion failure if a path alias bypasses serialization.
# END_FUNCTION_CONTRACT
def test_path_aliases_share_merge_lease(tmp_path):
    _database(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    alias = target / ".." / target.name
    coordinator = MergeCoordinatorService(git=RecordingGit())
    first = coordinator.acquire(target_repo_root=target, packet_id="packet-a")
    assert first.target_repo_key == coordinator.normalize_target_repo_key(alias)
    assert coordinator.try_acquire(target_repo_root=alias, packet_id="packet-b") is None
    coordinator.release(
        target_repo_key=first.target_repo_key,
        lease_token=first.lease_token,
        packet_id="packet-a",
    )


# START_FUNCTION_CONTRACT
# name: test_different_repositories_can_mutate_concurrently
# purpose: Prove independent target repo leases do not serialize each other.
# inputs: tmp_path — pytest temporary directory.
# returns: None on success.
# side_effects: Creates two leases and records overlapping mutations.
# emitted_logs: None.
# error_behavior: Assertion failure when independent repos serialize.
# END_FUNCTION_CONTRACT
def test_different_repositories_can_mutate_concurrently(tmp_path):
    _database(tmp_path)
    target_a = tmp_path / "target-a"
    target_b = tmp_path / "target-b"
    target_a.mkdir()
    target_b.mkdir()
    git = RecordingGit()
    coordinator = MergeCoordinatorService(git=git)
    lease_a = coordinator.acquire(target_repo_root=target_a, packet_id="packet-a", worker_id="worker-a")
    lease_b = coordinator.acquire(target_repo_root=target_b, packet_id="packet-b", worker_id="worker-b")

    def mutate(lease, packet_id, target):
        return coordinator.run_mutation(
            target_repo_key=lease.target_repo_key,
            lease_token=lease.lease_token,
            packet_id=packet_id,
            worker_id=lease.worker_id,
            step_name="merge",
            operation=lambda: git.merge(target, "agent", "main"),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(
            lambda args: mutate(*args),
            [(lease_a, "packet-a", target_a), (lease_b, "packet-b", target_b)],
        ))
    assert git.max_active_mutations == 2


# START_FUNCTION_CONTRACT
# name: test_stale_token_cannot_continue_after_takeover
# purpose: Prove expired takeover receives a new token and fences old mutation.
# inputs: tmp_path — pytest temporary directory.
# returns: None on success.
# side_effects: Reclaims a lease and records only the new-holder mutation.
# emitted_logs: None.
# error_behavior: Assertion failure if stale holder reaches callback.
# END_FUNCTION_CONTRACT
def test_stale_token_cannot_continue_after_takeover(tmp_path):
    _database(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    git = RecordingGit()
    coordinator = MergeCoordinatorService(git=git, ttl_seconds=30)
    first = coordinator.acquire(target_repo_root=target, packet_id="packet-a", worker_id="worker-a")
    with get_db() as db:
        db.query(MergeLease).filter_by(target_repo_key=first.target_repo_key).one().expires_at = (
            datetime.now(UTC) - timedelta(seconds=1)
        )
    second = coordinator.acquire(target_repo_root=target, packet_id="packet-b", worker_id="worker-b")
    assert second.lease_token != first.lease_token

    with pytest.raises(MergeLeaseFencedError):
        coordinator.run_mutation(
            target_repo_key=first.target_repo_key,
            lease_token=first.lease_token,
            packet_id="packet-a",
            worker_id="worker-a",
            step_name="push",
            operation=lambda: git.push(target, "origin", "main"),
        )
    assert git.steps == []
    coordinator.run_mutation(
        target_repo_key=second.target_repo_key,
        lease_token=second.lease_token,
        packet_id="packet-b",
        worker_id="worker-b",
        step_name="push",
        operation=lambda: git.push(target, "origin", "main"),
    )
    assert git.steps == [("start", "push"), ("done", "push")]


# START_FUNCTION_CONTRACT
# name: test_takeover_refuses_dirty_or_in_progress_repo
# purpose: Prove expired lease takeover never resets or aborts unsafe target state.
# inputs: tmp_path, repo_state — dirty or in-progress target state.
# returns: None on success.
# side_effects: Attempts a non-destructive takeover and inspects the old lease.
# emitted_logs: None.
# error_behavior: Assertion failure if unsafe takeover is allowed.
# END_FUNCTION_CONTRACT
@pytest.mark.parametrize("repo_state", ["dirty", "merge_in_progress"])
def test_takeover_refuses_dirty_or_in_progress_repo(tmp_path, repo_state):
    _database(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    git = RecordingGit()
    coordinator = MergeCoordinatorService(git=git)
    first = coordinator.acquire(target_repo_root=target, packet_id="packet-a", worker_id="worker-a")
    with get_db() as db:
        db.query(MergeLease).filter_by(target_repo_key=first.target_repo_key).one().expires_at = (
            datetime.now(UTC) - timedelta(seconds=1)
        )
    setattr(git, repo_state, True)

    with pytest.raises(MergeLeaseTakeoverError):
        coordinator.acquire(target_repo_root=target, packet_id="packet-b", worker_id="worker-b")
    with get_db() as db:
        current = db.query(MergeLease).filter_by(target_repo_key=first.target_repo_key).one()
        assert current.lease_token == first.lease_token
    assert not any(step in {"reset", "abort"} for _kind, step in git.steps)


# START_FUNCTION_CONTRACT
# name: test_accepted_merge_order_is_wave_created_at_id
# purpose: Verify deterministic accepted ordering and no dependency on whole-wave completion.
# inputs: tmp_path — pytest temporary directory.
# returns: None on success.
# side_effects: Inserts accepted packet metadata and reads merge order.
# emitted_logs: None.
# error_behavior: Assertion failure on ordering regression.
# END_FUNCTION_CONTRACT
def test_accepted_merge_order_is_wave_created_at_id(tmp_path):
    root = tmp_path / "target"
    root.mkdir()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _seed_packets(
        tmp_path,
        [
            ("packet-z", "wave-2", base, root),
            ("packet-b", "wave-1", base + timedelta(seconds=2), root),
            ("packet-a", "wave-1", base + timedelta(seconds=1), root),
        ],
    )
    order = MergeCoordinatorService().accepted_merge_order(target_repo_root=root)
    assert [packet.id for packet in order] == ["packet-a", "packet-b", "packet-z"]


# START_FUNCTION_CONTRACT
# name: test_successful_merge_releases_parallel_lease
# purpose: Verify MERGED releases TZ03 parallel resources only after merge success.
# inputs: tmp_path — pytest temporary directory.
# returns: None on success.
# side_effects: Runs MergeService with recorded target mutations and updates DB state.
# emitted_logs: None.
# error_behavior: Assertion failure on lifecycle or release regression.
# END_FUNCTION_CONTRACT
def test_successful_merge_releases_parallel_lease(tmp_path):
    root = tmp_path / "target"
    root.mkdir()
    _seed_packets(tmp_path, [("packet-a", "wave-1", datetime.now(UTC), root)])
    _lease("packet-a", root)
    git = RecordingGit()
    result = asyncio.run(
        MergeService(git=git).merge_packet(
            packet_id="packet-a",
            target_repo_root=str(root),
            branch_name="agent/packet-a",
            target_branch="main",
            worker_id="worker-1",
        )
    )
    assert result.success is True
    assert [step for kind, step in git.steps if kind == "start"] == [
        "checkout", "fetch", "merge", "push"
    ]
    with get_db() as db:
        assert db.query(Packet).filter_by(id="packet-a").one().state == PacketState.MERGED.value
        assert db.query(ParallelLease).filter_by(packet_id="packet-a").one_or_none() is None
        assert db.query(MergeLease).filter_by(target_repo_key=str(root.resolve())).one_or_none() is None

# END_BLOCK_TESTS
