# ############################################################################
# AI_HEADER: test_tz05_stale_base_recheck — stale-base merge acceptance tests
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify TZ05 target-base persistence, fenced integration recheck,
#          recoverable stale failures, race detection, and cleanup.
# inputs: Temporary Git repositories, Alembic-backed SQLite state, and an
#         injected profile-aware T1 report runner.
# returns: Pytest acceptance results.
# side_effects: Creates temporary repositories, worktrees, branches, database
#               rows, and merge commits under test-only paths.
# emitted_logs: None.
# error_behavior: Assertions identify a violated TZ05 invariant.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_stale_clean_apply_rechecks_and_merges
#   - function: test_stale_conflict_blocks_without_target_mutation
#   - function: test_stale_verification_failure_blocks_without_target_mutation
#   - function: test_unchanged_base_skips_integration_recheck
#   - function: test_target_advance_during_recheck_is_detected_and_rechecked
#   - function: test_packet_run_persists_actual_target_base_at_workspace_creation
#   - function: test_missing_base_sha_blocks_when_safety_enabled
#   - function: test_missing_base_sha_uses_explicit_disabled_compatibility_path
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from grace_control.adapters.packet_executor import PacketExecutionAdapter
from grace_control.agent.backend import ExecutionResult as BackendExecutionResult
from grace_control.config.settings import settings
from grace_control.core.contracts import (
    AcceptanceProfile,
    AcceptanceReport,
    ExecutionPacketContract,
    FinalVerdict,
)
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db, init_db
from grace_control.db.schema import (
    Feature,
    Packet,
    PacketRun,
    PacketState,
    ParallelLease,
    Wave,
)
from grace_control.services.git_service import GitService
from grace_control.services.integration_recheck_service import IntegrationRecheckService
from grace_control.services.merge_coordinator_service import MergeCoordinatorService
from grace_control.services.merge_service import MergeService
from grace_control.services.packet_service import PacketService
from grace_control.services.parallel_lease_service import ParallelLeaseService

_log = GraceLogger("test_tz05_stale_base_recheck")


# START_BLOCK_HELPERS
def _git_commit(git: GitService, repo: Path, message: str) -> str:
    git._run(["add", "."], repo)
    result = git._run(["commit", "-q", "-m", message], repo)
    assert result.success, result.stderr
    return git.current_sha(repo)


def _target_repo(tmp_path: Path, *, conflict: bool = False) -> tuple[Path, str, str, str]:
    repo = tmp_path / "target"
    repo.mkdir()
    git = GitService()
    assert git._run(["init", "-q"], repo).success
    assert git._run(["config", "user.email", "tz05@grace"], repo).success
    assert git._run(["config", "user.name", "TZ05"], repo).success
    (repo / "value.txt").write_text("X\n")
    initial_sha = _git_commit(git, repo, "X")
    assert git._run(["branch", "-M", "main"], repo).success

    assert git._run(["checkout", "-q", "-b", "agent/pkt-05"], repo).success
    if conflict:
        (repo / "value.txt").write_text("packet\n")
    else:
        (repo / "packet.txt").write_text("packet\n")
    packet_sha = _git_commit(git, repo, "packet result")
    assert git._run(["checkout", "-q", "main"], repo).success
    if conflict:
        (repo / "value.txt").write_text("target\n")
    else:
        (repo / "target.txt").write_text("target\n")
    target_sha = _git_commit(git, repo, "target advance")
    return repo, initial_sha, packet_sha, target_sha


def _seed_state(tmp_path: Path, repo: Path, base_sha: str | None) -> None:
    init_db(f"sqlite:///{tmp_path / 'grace.db'}")
    created = datetime.now(UTC)
    spec = {
        "target_repo_root": str(repo),
        "scope": ["packet.txt"],
        "verification": {"t1": []},
        "conflict_keys": ["packet-contract"],
    }
    with get_db() as db:
        db.add(Feature(
            id="feature-05",
            slug="feature-05",
            title="TZ05",
            spec_json={},
            status="active",
        ))
        db.add(Wave(
            id="wave-05",
            feature_id="feature-05",
            slug="wave-05",
            title="TZ05",
            order=1,
            status="IN_PROGRESS",
            created_at=created,
        ))
        db.add(Packet(
            id="packet-05",
            feature_id="feature-05",
            wave_id="wave-05",
            slug="packet-05",
            title="packet-05",
            description="TZ05 packet",
            spec_json=spec,
            state=PacketState.ACCEPTED.value,
            acceptance_profile=AcceptanceProfile.NORMAL.value,
            attempt_count=1,
            max_attempts=3,
            created_at=created,
            updated_at=created,
        ))
        db.add(PacketRun(
            id="packet-05-R01",
            packet_id="packet-05",
            run_number=1,
            status="accepted",
            result_json={
                "parallel_execution": {
                    "base_sha": base_sha,
                    "integration_base_sha": None,
                    "stale_base": False,
                    "conflict_keys": ["packet-contract"],
                    "integration_recheck": "skipped",
                },
            },
            base_sha=base_sha,
            evidence_path=str(tmp_path / "evidence"),
        ))
        ParallelLeaseService(ttl_seconds=300).acquire(
            db,
            packet_id="packet-05",
            feature_id="feature-05",
            wave_id="wave-05",
            worker_id="worker-05",
            claimed_attempt=1,
            scope=["packet.txt"],
            conflict_keys=["packet-contract"],
            base_sha=base_sha,
        )


def _report(accepted: bool) -> AcceptanceReport:
    return AcceptanceReport(
        packet_id="packet-05",
        final_verdict=FinalVerdict.ACCEPTED if accepted else FinalVerdict.REWORK_REQUIRED,
        profile=AcceptanceProfile.NORMAL,
        stages=[],
        summary="integration T1 passed" if accepted else "integration T1 failed",
    )


def _service(repo: Path, verifier) -> MergeService:
    git = GitService()
    coordinator = MergeCoordinatorService(git=git)
    recheck = IntegrationRecheckService(
        git=git,
        coordinator=coordinator,
        verification_runner=verifier,
    )
    return MergeService(
        git=git,
        packets=PacketService(),
        coordinator=coordinator,
        integration_recheck=recheck,
    )


def _worktree_entries(git: GitService, repo: Path) -> str:
    result = git._run(["worktree", "list", "--porcelain"], repo)
    assert result.success, result.stderr
    return result.stdout


def _integration_branches(git: GitService, repo: Path) -> str:
    result = git._run(["branch", "--list", "grace/integration/*"], repo)
    assert result.success, result.stderr
    return result.stdout


def _latest_run() -> PacketRun:
    with get_db() as db:
        run = db.query(PacketRun).filter_by(id="packet-05-R01").one()
        db.expunge(run)
        return run


def _packet_state() -> str:
    with get_db() as db:
        return db.query(Packet).filter_by(id="packet-05").one().state


# START_FUNCTION_CONTRACT
# name: test_packet_run_persists_actual_target_base_at_workspace_creation
# purpose: Prove PacketExecutor persists the real target HEAD immediately after
#          a scoped effective workspace is created, not its synthetic commit.
# inputs: tmp_path — isolated repository, database, and adapter workspace.
# returns: None on success.
# side_effects: Creates a scoped copy and updates one PacketRun row.
# emitted_logs: None.
# error_behavior: Assertion failure on synthetic or missing base SHA.
# END_FUNCTION_CONTRACT
def test_packet_run_persists_actual_target_base_at_workspace_creation(tmp_path: Path):
    repo, _initial_sha, _packet_sha, _target_sha = _target_repo(tmp_path)
    init_db(f"sqlite:///{tmp_path / 'workspace.db'}")
    target_sha = GitService().current_sha(repo)
    with get_db() as db:
        db.add(PacketRun(
            id="packet-05-R01",
            packet_id="packet-05",
            run_number=1,
            status="running",
            result_json={},
        ))

    backend = MagicMock()

    async def run_backend(request):
        return BackendExecutionResult(
            accepted=True,
            domain_status="accepted",
            worktree_path=request.worktree_path,
            branch_name=request.branch_name,
            commit_sha="",
            stdout="",
            stderr="",
            duration_ms=1,
        )

    backend.run = AsyncMock(side_effect=run_backend)
    adapter = PacketExecutionAdapter(
        project_root=repo,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "worktrees",
        backend=backend,
    )
    packet_path = tmp_path / "state" / "packet-05" / "EXECUTION_PACKET.md"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text("packet")
    contract = ExecutionPacketContract(
        packet_id="packet-05",
        title="TZ05",
        allowed_write_scope=["value.txt"],
        frozen_scope=[],
        acceptance_profile=AcceptanceProfile.FAST,
        verification={},
        metadata={"target_repo_root": str(repo), "workspace_mode": "scoped_copy"},
        conflict_keys=["packet-contract"],
    )

    asyncio.run(adapter._call_executor(
        packet_path,
        contract,
        1,
        "main",
        target_sha,
        {"minimal_repo": True, "workspace_mode": "scoped_copy"},
        tmp_path / "state" / "evidence",
        run_id="packet-05-R01",
    ))

    with get_db() as db:
        run = db.query(PacketRun).filter_by(id="packet-05-R01").one()
        assert run.base_sha == target_sha
        assert run.result_json["parallel_execution"]["base_sha"] == target_sha


# END_BLOCK_HELPERS


# START_BLOCK_TESTS
# START_FUNCTION_CONTRACT
# name: test_stale_clean_apply_rechecks_and_merges
# purpose: Prove a stale packet clean-applies to current Y, passes T1, stores
#          integration_base_sha=Y, and then merges.
# inputs: tmp_path — isolated repository and database root.
# returns: None on success.
# side_effects: Creates a temporary integration worktree and merge commit.
# emitted_logs: None.
# error_behavior: Assertion failure on stale-base protocol violation.
# END_FUNCTION_CONTRACT
def test_stale_clean_apply_rechecks_and_merges(tmp_path: Path):
    repo, initial_sha, _packet_sha, target_sha = _target_repo(tmp_path)
    _seed_state(tmp_path, repo, initial_sha)
    calls: list[Path] = []

    def verifier(**kwargs):
        calls.append(Path(kwargs["worktree_path"]))
        return _report(True)

    result = asyncio.run(_service(repo, verifier).merge_packet(
        "packet-05", str(repo), "agent/pkt-05", "main", worker_id="worker-05"
    ))

    assert result.success is True
    assert calls
    assert _packet_state() == PacketState.MERGED.value
    run = _latest_run()
    metadata = run.result_json["parallel_execution"]
    assert metadata["base_sha"] == initial_sha
    assert metadata["integration_base_sha"] == target_sha
    assert metadata["stale_base"] is True
    assert metadata["integration_recheck"] == "passed"
    assert run.integration_base_sha == target_sha
    assert "packet\n" in (repo / "packet.txt").read_text()
    assert "target\n" in (repo / "target.txt").read_text()
    assert "grace/integration/" not in _worktree_entries(GitService(), repo)
    assert _integration_branches(GitService(), repo) == ""


# START_FUNCTION_CONTRACT
# name: test_stale_conflict_blocks_without_target_mutation
# purpose: Prove a stale Git conflict blocks recoverably and preserves target
#          HEAD/content while releasing the parallel lease.
# inputs: tmp_path — isolated repository and database root.
# returns: None on success.
# side_effects: Creates and removes a temporary conflicted worktree.
# emitted_logs: None.
# error_behavior: Assertion failure on target mutation or wrong failure class.
# END_FUNCTION_CONTRACT
def test_stale_conflict_blocks_without_target_mutation(tmp_path: Path):
    repo, initial_sha, _packet_sha, target_sha = _target_repo(tmp_path, conflict=True)
    _seed_state(tmp_path, repo, initial_sha)

    def verifier(**_kwargs):
        raise AssertionError("conflict must not reach T1")

    result = asyncio.run(_service(repo, verifier).merge_packet(
        "packet-05", str(repo), "agent/pkt-05", "main", worker_id="worker-05"
    ))

    git = GitService()
    assert result.success is False
    assert "stale_base_conflict" in result.error
    assert git.current_sha(repo) == target_sha
    assert (repo / "value.txt").read_text() == "target\n"
    assert _packet_state() == PacketState.BLOCKED_RECOVERABLE.value
    with get_db() as db:
        assert db.query(ParallelLease).filter_by(packet_id="packet-05").one_or_none() is None
    run = _latest_run()
    assert run.result_json["failure_class"] == "stale_base_conflict"
    assert run.integration_base_sha == target_sha
    assert run.result_json["parallel_execution"]["integration_recheck"] == "failed"
    assert "base_sha" in run.result_json["integration_recheck_evidence"]
    assert "grace/integration/" not in _worktree_entries(git, repo)
    assert _integration_branches(git, repo) == ""


# START_FUNCTION_CONTRACT
# name: test_stale_verification_failure_blocks_without_target_mutation
# purpose: Prove clean integration with failed profile-aware T1 blocks
#          recoverably without changing target content.
# inputs: tmp_path — isolated repository and database root.
# returns: None on success.
# side_effects: Creates and removes a temporary integration verification tree.
# emitted_logs: None.
# error_behavior: Assertion failure on target mutation or wrong failure class.
# END_FUNCTION_CONTRACT
def test_stale_verification_failure_blocks_without_target_mutation(tmp_path: Path):
    repo, initial_sha, _packet_sha, target_sha = _target_repo(tmp_path)
    _seed_state(tmp_path, repo, initial_sha)

    result = asyncio.run(_service(repo, lambda **_kwargs: _report(False)).merge_packet(
        "packet-05", str(repo), "agent/pkt-05", "main", worker_id="worker-05"
    ))

    assert result.success is False
    assert "integration_verification_failed" in result.error
    assert GitService().current_sha(repo) == target_sha
    assert _packet_state() == PacketState.BLOCKED_RECOVERABLE.value
    run = _latest_run()
    assert run.result_json["failure_class"] == "integration_verification_failed"
    assert run.integration_base_sha == target_sha
    assert run.result_json["parallel_execution"]["integration_recheck"] == "failed"
    assert "verification" in run.result_json["integration_recheck_evidence"]


# START_FUNCTION_CONTRACT
# name: test_unchanged_base_skips_integration_recheck
# purpose: Prove an unchanged target follows normal serialized merge and marks
#          integration recheck as skipped.
# inputs: tmp_path — isolated repository and database root.
# returns: None on success.
# side_effects: Creates a normal merge commit without integration worktree.
# emitted_logs: None.
# error_behavior: Assertion failure on unexpected stale recheck.
# END_FUNCTION_CONTRACT
def test_unchanged_base_skips_integration_recheck(tmp_path: Path):
    repo, _initial_sha, _packet_sha, target_sha = _target_repo(tmp_path)
    _seed_state(tmp_path, repo, target_sha)
    calls: list[bool] = []

    def verifier(**_kwargs):
        calls.append(True)
        return _report(True)

    result = asyncio.run(_service(repo, verifier).merge_packet(
        "packet-05", str(repo), "agent/pkt-05", "main", worker_id="worker-05"
    ))

    assert result.success is True
    assert calls == []
    metadata = _latest_run().result_json["parallel_execution"]
    assert metadata["stale_base"] is False
    assert metadata["integration_recheck"] == "skipped"
    assert metadata["integration_base_sha"] is None


# START_FUNCTION_CONTRACT
# name: test_missing_base_sha_blocks_when_safety_enabled
# purpose: Prove an accepted packet with no trustworthy base snapshot fails
#          closed without changing the target repository.
# inputs: tmp_path — isolated repository and database root.
# returns: None on success.
# side_effects: Creates an accepted NULL-base run and records a recoverable block.
# emitted_logs: None.
# error_behavior: Assertion failure if target mutation or missing-base evidence
#                 is not produced.
# END_FUNCTION_CONTRACT
def test_missing_base_sha_blocks_when_safety_enabled(tmp_path: Path):
    repo, _initial_sha, _packet_sha, target_sha = _target_repo(tmp_path)
    _seed_state(tmp_path, repo, None)
    calls: list[bool] = []

    def verifier(**_kwargs):
        calls.append(True)
        return _report(True)

    with (
        patch.object(GitService, "checkout", side_effect=AssertionError("target checkout must not run")),
        patch.object(GitService, "merge", side_effect=AssertionError("target merge must not run")),
        patch.object(GitService, "push", side_effect=AssertionError("target push must not run")),
    ):
        result = asyncio.run(_service(repo, verifier).merge_packet(
            "packet-05", str(repo), "agent/pkt-05", "main", worker_id="worker-05"
        ))

    git = GitService()
    assert result.success is False
    assert "missing_base_sha" in result.error
    assert calls == []
    assert git.current_sha(repo) == target_sha
    assert (repo / "target.txt").read_text() == "target\n"
    assert _packet_state() == PacketState.BLOCKED_RECOVERABLE.value
    with get_db() as db:
        assert db.query(ParallelLease).filter_by(packet_id="packet-05").one_or_none() is None
    run = _latest_run()
    assert run.result_json["failure_class"] == "integration_verification_failed"
    assert run.result_json["integration_recheck_evidence"]["reason"] == "missing_base_sha"
    metadata = run.result_json["parallel_execution"]
    assert metadata["base_sha"] == ""
    assert metadata["integration_base_sha"] == target_sha
    assert metadata["stale_base"] is True
    assert metadata["integration_recheck"] == "failed"


# START_FUNCTION_CONTRACT
# name: test_missing_base_sha_uses_explicit_disabled_compatibility_path
# purpose: Prove the explicit disabled setting keeps legacy merge behavior and
#          records that stale-base protection was intentionally skipped.
# inputs: tmp_path, monkeypatch — isolated repository and setting override.
# returns: None on success.
# side_effects: Merges the accepted packet through the compatibility path.
# emitted_logs: None.
# error_behavior: Assertion failure if disabled behavior is implicit or blocked.
# END_FUNCTION_CONTRACT
def test_missing_base_sha_uses_explicit_disabled_compatibility_path(
    tmp_path: Path,
    monkeypatch,
):
    repo, _initial_sha, _packet_sha, target_sha = _target_repo(tmp_path)
    _seed_state(tmp_path, repo, None)
    monkeypatch.setattr(settings, "integration_recheck_on_stale_base", False)

    result = asyncio.run(_service(repo, lambda **_kwargs: _report(True)).merge_packet(
        "packet-05", str(repo), "agent/pkt-05", "main", worker_id="worker-05"
    ))

    assert result.success is True
    assert _packet_state() == PacketState.MERGED.value
    assert GitService().current_sha(repo) != target_sha
    metadata = _latest_run().result_json["parallel_execution"]
    assert metadata["base_sha"] == ""
    assert metadata["stale_base"] is False
    assert metadata["integration_recheck"] == "skipped"
    assert metadata["integration_recheck_disabled"] is True
    assert metadata["integration_recheck_skip_reason"] == (
        "GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=false"
    )


# START_FUNCTION_CONTRACT
# name: test_target_advance_during_recheck_is_detected_and_rechecked
# purpose: Prove a target advance during T1 invalidates the first validation,
#          triggers a second validation, and never merges against obsolete Y.
# inputs: tmp_path — isolated repository and database root.
# returns: None on success.
# side_effects: Advances target to Z from the injected verification callback.
# emitted_logs: None.
# error_behavior: Assertion failure if obsolete validation is accepted.
# END_FUNCTION_CONTRACT
def test_target_advance_during_recheck_is_detected_and_rechecked(tmp_path: Path):
    repo, initial_sha, _packet_sha, target_sha = _target_repo(tmp_path)
    _seed_state(tmp_path, repo, initial_sha)
    git = GitService()
    calls: list[str] = []

    def verifier(**_kwargs):
        calls.append(git.current_sha(repo))
        if len(calls) == 1:
            (repo / "race.txt").write_text("Z\n")
            _git_commit(git, repo, "target race advance")
        return _report(True)

    result = asyncio.run(_service(repo, verifier).merge_packet(
        "packet-05", str(repo), "agent/pkt-05", "main", worker_id="worker-05"
    ))

    assert result.success is True
    assert len(calls) >= 2
    assert calls[0] == target_sha
    run = _latest_run()
    assert run.integration_base_sha == git.current_sha(repo) or run.integration_base_sha in calls
    assert (repo / "race.txt").read_text() == "Z\n"
    assert "grace/integration/" not in _worktree_entries(git, repo)
    assert _integration_branches(git, repo) == ""
# END_BLOCK_TESTS
